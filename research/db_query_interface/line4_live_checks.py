"""QT-000007 line 4 — live checks of the windowed open path from the worktree.

Calls run_open_query directly (the running connector on 9443 still serves the
old code until the merge), one of each allowed form on each table, the GROUP
BY NAME shape on the view over 2 days, two refusals, and a bounded look at how
many ROUTING rows carry a DELOTP. Timings are printed for the Decisions entry;
no row values are printed beyond counts.

    uv run python -u research/db_query_interface/line4_live_checks.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mcp_server.open_query import run_open_query

CHECKS = [
    (
        "R key WAYBILL =",
        "SELECT WAYBILL, LEG, MBRANCH, MTYPE, MANIFEST, AGENTDATE FROM ROUTING WHERE WAYBILL = '102155314'",
    ),
    (
        "R key WAYBILL IN (3)",
        "SELECT WAYBILL, LEG, MANIFEST FROM ROUTING WHERE WAYBILL IN ('102155314', '102155340', '102155341')",
    ),
    (
        "R key MANIFEST alone",
        "SELECT COUNT(*), COUNT(DISTINCT WAYBILL) FROM ROUTING WHERE MANIFEST = 37733",
    ),
    (
        "R key MANIFEST + MBRANCH + MTYPE",
        "SELECT COUNT(*), COUNT(DISTINCT WAYBILL) FROM ROUTING r WHERE r.MANIFEST = 37733 AND r.MBRANCH = 0 AND r.MTYPE = 'M'",
    ),
    (
        "R window AGENTDATE 31 d aggregate",
        "SELECT MTYPE, COUNT(*), COUNT(DISTINCT WAYBILL) FROM ROUTING WHERE AGENTDATE BETWEEN '2026-09-01' AND '2026-10-01' GROUP BY 1",
    ),
    (
        "R window >= / < 7 d",
        "SELECT COUNT(*) FROM ROUTING WHERE AGENTDATE >= DATE '2026-10-05' AND AGENTDATE < DATE '2026-10-12'",
    ),
    (
        "R join to VIEW_WBANALYSE on the ROUTING alias",
        "SELECT FIRST 5 r.WAYBILL, r.LEG, w.CUSTNAME FROM ROUTING r JOIN VIEW_WBANALYSE w ON w.WAYBILL = r.WAYBILL WHERE r.WAYBILL IN ('102155314', '102155340')",
    ),
    (
        "V key WAYBILL =",
        "SELECT EVENTDATE, EVENTTIME, NAME, HUB, MANIFEST FROM VIEW_EVENTSCANS WHERE WAYBILL = '102155314' ORDER BY EVENTDATE, EVENTTIME",
    ),
    (
        "V key TRACKNO =",
        "SELECT EVENTDATE, EVENTTIME, NAME, HUB FROM VIEW_EVENTSCANS WHERE TRACKNO = '1021553140001'",
    ),
    ("V key MANIFEST =", "SELECT COUNT(*) FROM VIEW_EVENTSCANS WHERE MANIFEST = 37733"),
    (
        "V window EVENTDATE 1 d + HUB",
        "SELECT NAME, COUNT(*) FROM VIEW_EVENTSCANS WHERE EVENTDATE BETWEEN '2026-10-19' AND '2026-10-19' AND HUB = 'JNB' GROUP BY 1 ORDER BY 2 DESC",
    ),
    (
        "V GROUP BY NAME over 2 days",
        "SELECT NAME, COUNT(*) FROM VIEW_EVENTSCANS WHERE EVENTDATE BETWEEN DATE '2026-10-14' AND DATE '2026-10-15' GROUP BY NAME ORDER BY 2 DESC",
    ),
    ("REFUSE R unwindowed count", "SELECT COUNT(*) FROM ROUTING"),
    (
        "REFUSE V WAYDATE window",
        "SELECT COUNT(*) FROM VIEW_EVENTSCANS WHERE WAYDATE BETWEEN '2026-10-19' AND '2026-10-19'",
    ),
    (
        "REFUSE R 32-day window",
        "SELECT COUNT(*) FROM ROUTING WHERE AGENTDATE BETWEEN '2026-09-01' AND '2026-10-02'",
    ),
    (
        "REFUSE V star",
        "SELECT FIRST 1 * FROM VIEW_EVENTSCANS WHERE WAYBILL = '102155314'",
    ),
    (
        "R DELOTP named -> refused",
        "SELECT DELOTP FROM ROUTING WHERE WAYBILL = '102155314'",
    ),
    (
        "R DELOTP population, 7 d (bounded)",
        "SELECT COUNT(*), COUNT(DELOTP) FROM ROUTING WHERE AGENTDATE BETWEEN '2026-10-05' AND '2026-10-11'",
    ),
]


def main():
    print("line 4 live checks", time.strftime("%Y-%m-%d %H:%M:%S"))
    for label, sql in CHECKS:
        t0 = time.perf_counter()
        out = run_open_query(label, sql)
        ms = round((time.perf_counter() - t0) * 1000)
        if out.get("ok"):
            win = [n for n in out["notes"] if n.startswith("Window applied")]
            first = out["rows"][0] if out["rows"] else None
            shown = (
                first
                if label.startswith(
                    ("R key MANIFEST", "R window", "V key MANIFEST", "R DELOTP pop")
                )
                or "COUNT" in sql.upper().split("FROM")[0]
                else "(rows not shown)"
            )
            print(
                f"  OK      {label:<48} {out['row_count']:>4} rows  {out['elapsed_ms']:>6} ms db / {ms:>6} ms total  first={shown}"
            )
            for w in win:
                print(f"          {w}")
            if label.startswith("V GROUP BY NAME"):
                print(f"          top: {[tuple(r) for r in out['rows'][:3]]}")
        else:
            print(f"  REFUSED {label:<48} ({ms} ms) {out['reason'][:160]}")


if __name__ == "__main__":
    main()
