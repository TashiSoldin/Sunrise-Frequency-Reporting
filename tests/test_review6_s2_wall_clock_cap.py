"""Sixth Fable review (22 Oct 2026), findings S2 (a) and S5: the time cap is a
wall-clock bound, not the driver's per-read socket timeout.

An in-limit probe (a one-day EVENTDATE window with MANIFEST > 0) sent nothing
for a long time and the "15 s" cap let it run 30 s. The fetch now runs in a
worker thread with a hard deadline; on expiry the answer is refused at once
and the worker's connection is cancelled (a best-effort Firebird op_cancel)
and its socket closed, so the worker dies instead of lingering.

Firebird 3.0.13 has no SET STATEMENT TIMEOUT and firebirdsql 1.3 exposes no
cancel call or statement-timeout attribute, so the cancel is the raw opcode
plus the socket close — pinned here at the packet level, never against the
production database.
"""

import socket
import threading
import time

import pytest

from mcp_server import db
from mcp_server.open_query import (
    TIMEOUT_S,
    _DeadlineExceeded,
    _run_with_deadline,
    run_open_query,
)

SQL = "SELECT NAME FROM HOLIDAY"


def _sleeping_run(seconds):
    def run(sql, params=(), max_rows=None, timeout=None):
        time.sleep(seconds)
        return ["NAME"], [("x",)]

    return run


class TestTheDeadlineMechanism:
    def test_a_fast_fetch_returns_its_result(self):
        assert _run_with_deadline(
            _sleeping_run(0), SQL, 2.0, cancel=lambda i: False
        ) == (
            ["NAME"],
            [("x",)],
        )

    def test_a_slow_fetch_raises_at_the_deadline_and_cancels_the_worker(self):
        cancelled = []
        t0 = time.perf_counter()
        with pytest.raises(_DeadlineExceeded):
            _run_with_deadline(_sleeping_run(5), SQL, 0.3, cancel=cancelled.append)
        assert time.perf_counter() - t0 < 1.0
        assert len(cancelled) == 1 and isinstance(cancelled[0], int)
        assert cancelled[0] != threading.get_ident()  # the worker's ident, not ours

    def test_an_error_in_the_worker_is_re_raised_on_the_caller(self):
        def broken(sql, params=(), max_rows=None, timeout=None):
            raise ValueError("Dynamic SQL Error")

        with pytest.raises(ValueError, match="Dynamic SQL Error"):
            _run_with_deadline(broken, SQL, 2.0, cancel=lambda i: False)


class TestTheCapIsWallClock:
    def test_a_statement_sleeping_past_the_cap_is_refused_inside_the_cap_plus_a_second(
        self,
    ):
        """The proof the brief asked for: a harmless fake fetch that sleeps
        well past TIMEOUT_S comes back as a time-cap refusal in ~TIMEOUT_S of
        wall-clock, not whenever the sleep ends."""
        t0 = time.perf_counter()
        out = run_open_query("slow", SQL, run=_sleeping_run(TIMEOUT_S + 10))
        elapsed = time.perf_counter() - t0
        assert out["refused"] and "time cap" in out["reason"]
        assert "wall-clock" in out["reason"] and "cancelled and closed" in out["reason"]
        assert TIMEOUT_S - 0.5 <= elapsed <= TIMEOUT_S + 1.5, elapsed
        assert out["reason"].endswith("rather than fetching rows)")


class _FakeRaw:
    def __init__(self):
        self.shut = None
        self.closed = False

    def shutdown(self, how):
        self.shut = how

    def close(self):
        self.closed = True


class _FakeStream:
    def __init__(self):
        self.sent = b""
        self._sock = _FakeRaw()

    def send(self, b):
        self.sent += b


class _FakeConn:
    def __init__(self):
        self.sock = _FakeStream()


class TestCancelThread:
    def test_nothing_registered_is_a_quiet_false(self):
        assert db.cancel_thread(123456789) is False

    def test_sends_op_cancel_raise_then_shuts_and_closes_the_socket(self):
        conn = _FakeConn()
        ident = 4242
        with db._ACTIVE_LOCK:
            db._ACTIVE[ident] = conn
        try:
            assert db.cancel_thread(ident) is True
        finally:
            with db._ACTIVE_LOCK:
                db._ACTIVE.pop(ident, None)
        # op_cancel (91) then fb_cancel_raise (3), big-endian XDR ints
        assert conn.sock.sent == (91).to_bytes(4, "big") + (3).to_bytes(4, "big")
        assert conn.sock._sock.shut == socket.SHUT_RDWR
        assert conn.sock._sock.closed is True

    def test_a_connection_that_refuses_the_packet_is_still_closed(self):
        conn = _FakeConn()

        def boom(b):
            raise OSError("gone")

        conn.sock.send = boom
        with db._ACTIVE_LOCK:
            db._ACTIVE[77] = conn
        try:
            assert db.cancel_thread(77) is True
        finally:
            with db._ACTIVE_LOCK:
                db._ACTIVE.pop(77, None)
        assert conn.sock._sock.closed is True

    def test_run_select_registers_the_connection_under_its_thread(self, monkeypatch):
        seen = {}

        class Cur:
            description = [("NAME",)]

            def execute(self, sql, params):
                with db._ACTIVE_LOCK:
                    seen["registered"] = db._ACTIVE.get(threading.get_ident())

            def fetchmany(self, n):
                return [("x",)]

            def close(self):
                pass

        class Conn:
            def cursor(self):
                return Cur()

            def close(self):
                pass

        conn = Conn()
        monkeypatch.setattr(db, "connect", lambda timeout=None: conn)
        assert db.run_select(SQL) == (["NAME"], [("x",)])
        assert seen["registered"] is conn
        with db._ACTIVE_LOCK:
            assert (
                threading.get_ident() not in db._ACTIVE
            )  # unregistered after the fetch
