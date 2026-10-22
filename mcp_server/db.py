"""Firebird access for the MCP server.

connect() follows the pattern in revenue_reports/extract_revenue.py —
credentials from the gitignored .env, charset latin1 — with one difference:
the transaction is opened READ COMMITTED **read-only**, so Firebird itself
refuses a write even if a statement slipped past the guard.

INTERIM (12 Aug 2026): these are the BI-role credentials shared with the
scheduled reports. A dedicated second login is with Innate (SYSDBA needed);
switch DB_USER/DB_PASSWORD in .env when it lands — to be replaced before
handover, never shipped as the final state.
"""

import os
import select as _select_module
import socket
import threading
from contextlib import closing

import firebirdsql
import firebirdsql.fbcore
from dotenv import load_dotenv
from firebirdsql.wireprotocol import Packer

from mcp_server.sql_guard import assert_select_only

# Upstream bug in firebirdsql 1.x: fbcore's timeout path calls
# select.select(...) without ever importing select, so ANY connection with a
# timeout dies with NameError at the first read. Verified against the
# installed package (fbcore.py line ~579, no `import select` at the top).
# Injecting the module is the whole fix; harmless if a fixed version lands.
if not hasattr(firebirdsql.fbcore, "select"):
    firebirdsql.fbcore.select = _select_module

# One query never returns more than this many rows. The health tool needs 1;
# a real cap policy per tool arrives with the tools (Days 2-5).
MAX_ROWS = 1000


# How long the TCP probe below waits before declaring the host unreachable.
CONNECT_TIMEOUT_S = 10


def connect(timeout: float | None = None) -> firebirdsql.Connection:
    """timeout is the socket timeout in seconds — a read that blocks longer
    raises. It caps how long we WAIT, not what Firebird executes: an
    abandoned aggregate may keep running server-side after the socket
    closes, which is why the open path's real load bound is its allowlist.

    Left None for the heavy report paths on purpose: their fetches stream
    for minutes and must not be cut. The unreachable-host case (13 Aug Day 2
    review: a host that drops packets rather than refusing hangs the driver
    indefinitely, where a refusing one fails in ~2s) is covered for EVERY
    caller by the bounded TCP probe below, which converts the hang into a
    clean ConnectionError within CONNECT_TIMEOUT_S."""
    load_dotenv()
    probe = socket.create_connection(
        (os.getenv("DB_HOST"), int(os.getenv("DB_PORT", "3050"))),
        timeout=CONNECT_TIMEOUT_S,
    )
    probe.close()
    return firebirdsql.connect(
        host=os.getenv("DB_HOST"),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        role=os.getenv("DB_ROLE"),
        charset="latin1",
        use_unicode=True,
        isolation_level=firebirdsql.ISOLATION_LEVEL_READ_COMMITED_RO,
        timeout=timeout,
    )


def run_select(
    sql: str,
    params: tuple = (),
    max_rows: int = MAX_ROWS,
    timeout: float | None = None,
) -> tuple[list[str], list[tuple]]:
    """Run one guarded SELECT and return (column_names, rows), capped.

    The connection is registered under the calling thread's ident for the
    duration of the fetch so a caller on another thread can cancel it on a
    wall-clock deadline (cancel_thread)."""
    assert_select_only(sql)
    try:
        conn = connect(timeout)
    except Exception as e:
        # Said in the tool error the client relays: a raw WinError/socket
        # message must never be mistaken for an answer about the data.
        raise ConnectionError(
            f"the Parcel Perfect database is unreachable ({e}) — the query "
            "did not run, so this says nothing about the data asked for"
        ) from e
    ident = threading.get_ident()
    with _ACTIVE_LOCK:
        _ACTIVE[ident] = conn
    try:
        with closing(conn.cursor()) as cur:
            cur.execute(sql, params)
            columns = [d[0] for d in cur.description]
            rows = cur.fetchmany(max_rows)
        return columns, rows
    finally:
        with _ACTIVE_LOCK:
            _ACTIVE.pop(ident, None)
        # A timed-out query leaves the socket dead; close() then raises its
        # own "Can not recv() packets" over the wire detach and would MASK
        # the real error. The cleanup failure carries no information.
        try:
            conn.close()
        except Exception:
            pass


# --- wall-clock cancel (sixth review S2/S5, 22 Oct 2026) ----------------------
# The driver's `timeout` is a per-read socket timeout: a statement that sends
# nothing for a while (a scan, a bitmap AND over a big index) is waited on
# read after read, and one in-limit probe ran 30 s against a "15 s" cap. The
# open path now runs the fetch in a worker thread with a wall-clock deadline
# and calls cancel_thread(worker ident) on expiry.
#
# Firebird 3.0.13 has no SET STATEMENT TIMEOUT, and firebirdsql 1.3 exposes
# neither a cancel call nor a statement-timeout attribute — only the opcode.
# So the cancel is two best-effort steps: an op_cancel / fb_cancel_raise
# packet on the worker's own connection (in the wire protocol since Firebird
# 2.5; the server reads it out of band while the request runs), then a hard
# shutdown + close of the socket, which unblocks the worker's recv and makes
# the server drop the attachment when it next touches the connection. Which
# of the two the server acts on first is not provable from here; neither can
# be made worse by the other.
_ACTIVE: dict[int, firebirdsql.Connection] = {}
_ACTIVE_LOCK = threading.Lock()
_OP_CANCEL = 91  # firebirdsql.wireprotocol.WireProtocol.op_cancel
_FB_CANCEL_RAISE = 3  # ibase.h: fb_cancel_raise


def cancel_thread(ident: int) -> bool:
    """Cancel and close the connection that thread `ident` is fetching on.
    Returns False when that thread has no registered connection (already
    finished, or a test double). Never raises."""
    with _ACTIVE_LOCK:
        conn = _ACTIVE.get(ident)
    if conn is None:
        return False
    stream = getattr(conn, "sock", None)
    try:
        p = Packer()
        p.pack_int(_OP_CANCEL)
        p.pack_int(_FB_CANCEL_RAISE)
        stream.send(p.get_buffer())
    except Exception:
        pass
    raw = getattr(stream, "_sock", None)
    try:
        raw.shutdown(socket.SHUT_RDWR)
    except Exception:
        pass
    try:
        raw.close()
    except Exception:
        pass
    return True
