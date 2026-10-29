"""db.connect hands the caller's per-read timeout to the driver (hot-fix, 29 Oct 2026).

Regression introduced by 9eeb6400 (seventh review V6): db.connect passes
connect_timeout into firebirdsql.connect(timeout=...), and firebirdsql 1.3
keeps that one value as Connection.timeout (fbcore.py, Connection.__init__:
``self.timeout = float(timeout) if timeout is not None else None``), which
ConnectionResponseMixin._recv_channel select()s on before EVERY read and turns
into OperationalError("Can not recv() packets") when it trips. The
``raw.settimeout(timeout)`` line only reset the socket, so every connection
carried a hidden per-read limit: 10 s on the report paths (connect(None)),
5 s on the open path. revenue_summary failed on every call from 23 Oct.

(a) pins the hand-over on a stub that models the driver's one line;
(b) runs the real driver's _recv_channel over a socketpair whose far end stays
    silent for longer than connect_timeout: it must wait, not raise.
Both fail on a3adf362 and pass with the fix.
"""

import socket
import threading
import time

import firebirdsql
import firebirdsql.fbcore
import pytest
from firebirdsql.stream import SocketStream

from mcp_server import db


def _stub_probe(monkeypatch):
    class Probe:
        def close(self):
            pass

    monkeypatch.setattr(
        db.socket, "create_connection", lambda addr, timeout=None: Probe()
    )
    monkeypatch.setattr(db, "load_dotenv", lambda: None)
    monkeypatch.setenv("DB_HOST", "h")
    monkeypatch.setenv("DB_PORT", "3050")


# --- (a) stubbed driver ---------------------------------------------------------------


class _DriverLikeConn:
    """What firebirdsql.connect(timeout=t) leaves behind: Connection.timeout
    holds t (fbcore.py Connection.__init__), and the socket was created with
    the same value (stream.py SocketStream.__init__)."""

    def __init__(self, timeout):
        self.timeout = float(timeout) if timeout is not None else None
        self.sock = SocketStream.__new__(SocketStream)
        self.sock._sock = socket.socket()
        self.sock._sock.settimeout(self.timeout)
        self.sock.read_translator = None
        self.sock.write_translator = None


@pytest.fixture
def stubbed(monkeypatch):
    _stub_probe(monkeypatch)
    made = []

    def fake_connect(**kw):
        conn = _DriverLikeConn(kw["timeout"])
        made.append(conn)
        return conn

    monkeypatch.setattr(db.firebirdsql, "connect", fake_connect)
    yield made
    for conn in made:
        conn.sock._sock.close()


class TestStubbed:
    def test_a_report_path_connection_has_no_per_read_timeout(self, stubbed):
        conn = db.connect(None)
        assert conn.timeout is None  # the driver's per-read limit
        assert conn.sock._sock.gettimeout() is None  # the socket's

    def test_the_open_path_connection_keeps_its_own_per_read_timeout(self, stubbed):
        conn = db.connect(15, connect_timeout=5.0)
        assert conn.timeout == 15.0
        assert conn.sock._sock.gettimeout() == 15.0

    def test_the_connect_budget_still_reaches_the_handshake(self, stubbed, monkeypatch):
        """V6 kept: the probe and the handshake run under connect_timeout."""
        seen = {}
        real = db.firebirdsql.connect
        monkeypatch.setattr(
            db.firebirdsql,
            "connect",
            lambda **kw: seen.update(handshake=kw["timeout"]) or real(**kw),
        )
        db.connect(15, connect_timeout=5.0)
        assert seen["handshake"] == 5.0


# --- (b) the real driver over a socketpair ------------------------------------------

CONNECT_TIMEOUT_S = 0.5
SILENCE_S = 1.5  # longer than connect_timeout, far shorter than the open path's 15 s


class _Wire(firebirdsql.fbcore.Connection):
    """The real Connection minus the handshake: __del__ would otherwise try a
    wire detach on an attachment that never existed."""

    def close(self):
        pass


def _real_connection_over(sock, timeout):
    """A real firebirdsql Connection whose wire is `sock`, exactly as the
    driver leaves it after firebirdsql.connect(timeout=timeout) — minus the
    handshake, which is not what is under test. _recv_channel is the real one."""
    conn = _Wire.__new__(_Wire)
    conn.timeout = float(timeout) if timeout is not None else None
    conn.sock = SocketStream.__new__(SocketStream)
    conn.sock._sock = sock
    conn.sock._sock.settimeout(conn.timeout)
    conn.sock.read_translator = None
    conn.sock.write_translator = None
    return conn


@pytest.fixture
def wire(monkeypatch):
    _stub_probe(monkeypatch)
    near, far = socket.socketpair()
    monkeypatch.setattr(
        db.firebirdsql,
        "connect",
        lambda **kw: _real_connection_over(near, kw["timeout"]),
    )
    yield far
    near.close()
    far.close()


def _answer_after(far, delay_s, payload):
    def go():
        time.sleep(delay_s)
        far.sendall(payload)

    t = threading.Thread(target=go, daemon=True)
    t.start()
    return t


class TestRealDriver:
    @pytest.mark.parametrize(
        "per_read", [None, 15.0], ids=["report path (None)", "open path (15 s)"]
    )
    def test_a_read_outlives_the_connect_timeout(self, wire, per_read):
        conn = db.connect(per_read, connect_timeout=CONNECT_TIMEOUT_S)
        assert isinstance(conn, firebirdsql.fbcore.Connection)
        t = _answer_after(wire, SILENCE_S, b"\x00\x00\x00\x07")
        started = time.perf_counter()
        try:
            got = conn._recv_channel(4)  # a3adf362: OperationalError after 0.5 s
        finally:
            t.join()  # the far end must not outlive the fixture's sockets
        waited = time.perf_counter() - started
        assert got == b"\x00\x00\x00\x07"
        assert waited >= SILENCE_S - 0.1

    def test_the_open_path_per_read_limit_still_trips(self, wire):
        """The hand-over is to the CALLER's value, not to no limit at all."""
        conn = db.connect(0.3, connect_timeout=CONNECT_TIMEOUT_S)
        with pytest.raises(firebirdsql.OperationalError, match="Can not recv"):
            conn._recv_channel(4)
