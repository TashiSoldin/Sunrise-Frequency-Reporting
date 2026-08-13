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
from contextlib import closing

import firebirdsql
from dotenv import load_dotenv

from mcp_server.sql_guard import assert_select_only

# One query never returns more than this many rows. The health tool needs 1;
# a real cap policy per tool arrives with the tools (Days 2-5).
MAX_ROWS = 1000


def connect() -> firebirdsql.Connection:
    load_dotenv()
    return firebirdsql.connect(
        host=os.getenv("DB_HOST"),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        role=os.getenv("DB_ROLE"),
        charset="latin1",
        use_unicode=True,
        isolation_level=firebirdsql.ISOLATION_LEVEL_READ_COMMITED_RO,
    )


def run_select(
    sql: str, params: tuple = (), max_rows: int = MAX_ROWS
) -> tuple[list[str], list[tuple]]:
    """Run one guarded SELECT and return (column_names, rows), capped."""
    assert_select_only(sql)
    try:
        conn = connect()
    except Exception as e:
        # Said in the tool error the client relays: a raw WinError/socket
        # message must never be mistaken for an answer about the data.
        raise ConnectionError(
            f"the Parcel Perfect database is unreachable ({e}) — the query "
            "did not run, so this says nothing about the data asked for"
        ) from e
    with closing(conn), closing(conn.cursor()) as cur:
        cur.execute(sql, params)
        columns = [d[0] for d in cur.description]
        rows = cur.fetchmany(max_rows)
    return columns, rows
