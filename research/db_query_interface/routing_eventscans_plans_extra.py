"""QT-000007 line 3 — follow-up measurements after the main run.

Run after routing_eventscans_plans.py, same protocol (plan first, 60 s
timeout, nothing executed whose plan scans a big relation):

  0. MON$STATEMENTS: is the sizing statement the main run ABORTED at 60 s
     (per-type count over one day, PLAN ... ORDER EV_TYPEDATETIME) still
     executing server-side? A socket timeout does not stop Firebird 3.
  1. VIEW_EVENTSCANS EVENTDATE windows of 2 and 3 days (count) — the 1-day
     and 7-day points bracket the ~5 s warm line; the rule should sit on a
     measured width, not an interpolated one.
  2. VIEW_EVENTSCANS WAYBILL IN (24) — the IN-list cost on the view.
  3. VIEW_EVENTSCANS MANIFEST = 37733 — count (the main run read 501 rows).
  4. ROUTING: what BOOKDATE covers vs AGENTDATE over the same 31 days, by
     MTYPE — BOOKDATE is indexed and cheap but sparse (1,282 vs 48,680 rows).

    uv run python -u research/db_query_interface/routing_eventscans_plans_extra.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.db_query_interface.routing_eventscans_plans import fetch, measure

VCOLS = "WAYBILL, TRACKNO, EVENTDATE, EVENTTIME, NAME, HUB, MANIFEST, ACCNUM, WAYDATE, ORIGHUB, DESTHUB"


def main():
    print("extra run", time.strftime("%Y-%m-%d %H:%M:%S"))
    print("\n== MON$STATEMENTS — active statements visible to this login ==")
    try:
        rows = fetch(
            "SELECT s.MON$STATEMENT_ID, s.MON$ATTACHMENT_ID, s.MON$STATE, s.MON$TIMESTAMP, "
            "CAST(SUBSTRING(s.MON$SQL_TEXT FROM 1 FOR 90) AS VARCHAR(90)) "
            "FROM MON$STATEMENTS s WHERE s.MON$STATE = 1 ORDER BY s.MON$TIMESTAMP",
            n=50,
        )
        for r in rows:
            print("   ", r)
        if not rows:
            print("    (none active)")
    except Exception as e:
        print("    MON$ not readable:", str(e)[:160])

    wbs = [
        r[0]
        for r in fetch(
            "SELECT FIRST 50 WAYBILL FROM VIEW_WBANALYSE WHERE WAYDATE = DATE '2026-10-13' "
            "AND WAYBILL NOT LIKE '~%' AND WAYBILL NOT LIKE '%/%' AND ACCNUM = 'S135' ORDER BY WAYBILL",
            n=50,
        )
    ]
    inl = ", ".join(f"'{w}'" for w in wbs)
    print(f"\nsample waybills: {len(wbs)}")

    for name, (a, b) in (
        ("2 days", ("2026-09-28", "2026-09-29")),
        ("3 days", ("2026-10-13", "2026-10-15")),
    ):
        measure(
            f"X1 VIEW_EVENTSCANS EVENTDATE BETWEEN {name} — count",
            f"SELECT COUNT(*) FROM VIEW_EVENTSCANS WHERE EVENTDATE BETWEEN DATE '{a}' AND DATE '{b}'",
            shape="count",
        )
    measure(
        f"X2 VIEW_EVENTSCANS by WAYBILL IN ({len(wbs)})",
        f"SELECT FIRST 501 {VCOLS} FROM VIEW_EVENTSCANS WHERE WAYBILL IN ({inl})",
    )
    measure(
        "X3 VIEW_EVENTSCANS MANIFEST = 37733 — count",
        "SELECT COUNT(*) FROM VIEW_EVENTSCANS WHERE MANIFEST = 37733",
        shape="count",
    )
    measure(
        "X4 ROUTING BOOKDATE 31 days by MTYPE",
        "SELECT MTYPE, COUNT(*) FROM ROUTING WHERE BOOKDATE BETWEEN DATE '2026-08-31' AND DATE '2026-09-30' GROUP BY 1",
        shape="rows",
    )
    measure(
        "X4b ROUTING AGENTDATE 31 days by MTYPE",
        "SELECT MTYPE, COUNT(*), COUNT(BOOKDATE) FROM ROUTING WHERE AGENTDATE BETWEEN DATE '2026-08-31' AND DATE '2026-09-30' GROUP BY 1",
        shape="rows",
    )
    from research.db_query_interface.routing_eventscans_plans import RESULTS

    for r in RESULTS:
        if r["label"].startswith("X4"):
            print("   ", r["label"], "->", [tuple(x) for x in r.get("_rows", [])])


if __name__ == "__main__":
    main()
