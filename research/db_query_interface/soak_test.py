"""Firebird soak test (Day 5 hardening) — concurrent sessions and sustained
load, verified before handover.

Why: the interface opens a fresh connection per tool call (db.run_select), so
N concurrent Claude questions = N concurrent Firebird sessions on the live
freight system. The quote's risk list says verify connection limits/licensing
with a soak test rather than promise anything.

Production-safe by construction: every query is small and indexed or over a
sub-10k-row table (HUB count, one indexed waybill lookup, one month's
manifest count, CURRENT_TIMESTAMP). The connection probe opens sessions
SEQUENTIALLY, holds them only long enough to count, and closes every one in
a finally block.

Run from the repo root on the BI server:

    uv run python research\\db_query_interface\\soak_test.py [--seconds 60] [--workers 8]
"""

import argparse
import statistics
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mcp_server.db import connect, run_select

PROBE_MAX = 25  # sessions to attempt in the limit probe — modest on purpose


def probe_connection_limit() -> int:
    """Open sessions one at a time until refused or PROBE_MAX, then close all."""
    conns = []
    try:
        for i in range(PROBE_MAX):
            try:
                conns.append(connect(timeout=10))
            except Exception as e:
                print(f"  connection {i + 1} REFUSED: {e}")
                return i
        return len(conns)
    finally:
        for c in conns:
            try:
                c.close()
            except Exception:
                pass


QUERIES = [
    ("db_time", "SELECT CURRENT_TIMESTAMP FROM RDB$DATABASE", ()),
    ("hub_count", "SELECT COUNT(*) FROM HUB", ()),
    (
        "manifest_month",
        (
            "SELECT COUNT(*) FROM MANIFEST WHERE STARTDATE "
            "BETWEEN DATE '2026-07-01' AND DATE '2026-07-31'"
        ),
        (),
    ),
    # filled in by main(): an indexed lookup on a real waybill number
]


def worker(deadline: float, results: list, errors: list) -> None:
    i = 0
    while time.monotonic() < deadline:
        name, sql, params = QUERIES[i % len(QUERIES)]
        i += 1
        started = time.perf_counter()
        try:
            run_select(sql, params, 100, timeout=15)
            results.append((name, time.perf_counter() - started))
        except Exception as e:
            errors.append((name, f"{type(e).__name__}: {e}"))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seconds", type=int, default=60)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    print(f"== connection-limit probe (sequential, up to {PROBE_MAX}) ==")
    n = probe_connection_limit()
    print(
        f"  {n} concurrent sessions opened cleanly"
        + ("" if n < PROBE_MAX else f" (stopped at the probe's own cap, {PROBE_MAX})")
    )

    # A real waybill number for the indexed-lookup leg. Date-RANGE filter,
    # never MAX() over the view: the first version of this probe did exactly
    # that, scanned 3.1M rows and blew its own 30s timeout — the guard's
    # lesson, demonstrated by the soak test's own setup query.
    _, rows = run_select(
        "SELECT FIRST 1 WAYBILL FROM VIEW_WBANALYSE "
        "WHERE WAYDATE BETWEEN CURRENT_DATE - 7 AND CURRENT_DATE",
        timeout=30,
    )
    wb = rows[0][0].strip()
    QUERIES.append(
        (
            "waybill_lookup",
            "SELECT STATUS, EVENTNAME FROM VIEW_WBANALYSE WHERE WAYBILL = ?",
            (wb,),
        )
    )
    print(f"  indexed-lookup leg uses waybill {wb!r}")

    print(f"\n== soak: {args.workers} workers x {args.seconds}s, mixed queries ==")
    results: list = []
    errors: list = []
    deadline = time.monotonic() + args.seconds
    threads = [
        threading.Thread(target=worker, args=(deadline, results, errors), daemon=True)
        for _ in range(args.workers)
    ]
    t0 = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.monotonic() - t0

    print(f"  {len(results)} queries in {elapsed:.0f}s, {len(errors)} errors")
    by_name: dict[str, list[float]] = {}
    for name, dt in results:
        by_name.setdefault(name, []).append(dt)
    for name, times in sorted(by_name.items()):
        times.sort()
        p95 = times[max(0, int(len(times) * 0.95) - 1)]
        print(
            f"  {name:16s} n={len(times):5d}  "
            f"p50={statistics.median(times) * 1000:6.0f}ms  "
            f"p95={p95 * 1000:6.0f}ms  max={times[-1] * 1000:6.0f}ms"
        )
    if errors:
        print("\n  ERRORS (first 10):")
        for name, e in errors[:10]:
            print(f"  {name}: {e}")
        raise SystemExit(1)
    print("\nSOAK TEST PASSED")


if __name__ == "__main__":
    main()
