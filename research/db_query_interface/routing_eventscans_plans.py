"""QT-000007 line 3 — ROUTING and VIEW_EVENTSCANS query plans and timings.

Measures, on the live database, the query shapes the windowed open path
(line 4) will allow or refuse, each run twice (cold, then warm on a fresh
connection), capturing Firebird's PLAN and the wall-clock. Two shapes per
predicate where it matters, because they cost different things:

  rows  — SELECT FIRST 501 <cols> ...  (what open_query actually does)
  count — SELECT COUNT(*) ...          (the full cost of the window: what an
                                         aggregate over it makes Firebird do)

Safety protocol (this is the production freight database; EVENT is 113M
rows and Firebird 3 cannot be told to stop server-side once a statement is
running):
  * every statement is PREPARED first (explain_plan=True) and its PLAN read
    BEFORE it is executed;
  * a VIEW_EVENTSCANS statement whose plan shows a NATURAL scan on a big
    context (E/T/W/R/POD) is recorded and NOT executed;
  * the single unbounded ROUTING COUNT(*) is the one deliberate natural scan
    (6M rows) — it is the cost the guard exists to prevent;
  * the socket timeout is 60 s; a tripped timeout is recorded as ABORTED.
  * wide EVENT windows run only after the narrower one came back fast
    (adaptive, thresholds stated inline).

Outputs the raw log to stdout; the dated findings file
routing_eventscans_plans_2026-10-21.md is written by hand from that log.

Run from the repo root on the BI server (mid-morning, not 07:00 / 16:30):

    uv run python -u research/db_query_interface/routing_eventscans_plans.py
"""

import json
import re
import sys
import time
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mcp_server.db import connect

TIMEOUT_S = 60
ROWS_SHAPE_LIMIT = 501  # open_query reads ROW_CAP + 1

# Contexts inside VIEW_EVENTSCANS whose NATURAL scan would be the 113M-row
# disaster (or the 14M / 3.1M / 6M / 1.9M ones): EVENT, TRACK, WAYBILL,
# ROUTING, POD. SCANRULE/USERCODE/BRANCH/AGENT/FAILTYPE are lookups.
BIG_CONTEXTS = ("E", "T", "W", "R", "POD", "EVENT", "TRACK", "WAYBILL", "ROUTING")

RESULTS: list[dict] = []


def plan_is_dangerous(plan: str) -> bool:
    for ctx in BIG_CONTEXTS:
        if re.search(rf"(?<![A-Z0-9_]){re.escape(ctx)} NATURAL", plan):
            return True
    return False


def one_run(sql, params, shape):
    """Prepare (plan), execute, fetch; returns (plan, seconds, n, status)."""
    conn = connect(timeout=TIMEOUT_S)
    try:
        with closing(conn.cursor()) as cur:
            # Plan from a prepare with explain_plan=True; the statement is then
            # executed from its text on the same connection — the driver's
            # prepared-statement object carries no result set when prepared
            # with the plan option (verified 21 Oct: 0 rows), so the timed part
            # re-prepares. Prepare cost is a few ms and is inside the timing.
            with closing(conn.cursor()) as pc:
                plan = (pc.prep(sql, explain_plan=True).stmt.plan or "").strip()
            t0 = time.perf_counter()
            try:
                cur.execute(sql, params)
                if shape == "count":
                    row = cur.fetchone()
                    n = row[0] if row else None
                    rows = [row]
                else:
                    rows = cur.fetchmany(ROWS_SHAPE_LIMIT)
                    n = len(rows)
                dt = time.perf_counter() - t0
                return plan, dt, n, "ok", rows
            except Exception as e:
                dt = time.perf_counter() - t0
                msg = str(e)
                if "recv" in msg or "timed out" in msg.lower():
                    return (
                        plan,
                        dt,
                        None,
                        f"ABORTED at {TIMEOUT_S}s (socket timeout)",
                        [],
                    )
                return plan, dt, None, f"ERROR {msg[:160]}", []
    finally:
        try:
            conn.close()
        except Exception:
            pass


def plan_only(sql):
    conn = connect(timeout=TIMEOUT_S)
    try:
        with closing(conn.cursor()) as cur:
            ps = cur.prep(sql, explain_plan=True)
            return (ps.stmt.plan or "").strip()
    finally:
        try:
            conn.close()
        except Exception:
            pass


def measure(label, sql, params=(), shape="rows", allow_natural=False, runs=2):
    print(f"\n### {label}")
    print(f"    SQL: {sql}")
    if params:
        print(f"    params: {params}")
    plan = plan_only(sql)
    print(f"    {plan}")
    rec = {
        "label": label,
        "sql": sql,
        "params": list(params),
        "shape": shape,
        "plan": plan,
        "runs": [],
    }
    if plan_is_dangerous(plan) and not allow_natural:
        print("    NOT EXECUTED — plan shows a NATURAL scan on a big relation")
        rec["runs"].append({"status": "not executed (natural scan on a big relation)"})
        RESULTS.append(rec)
        return rec
    for i in range(runs):
        tag = "cold" if i == 0 else "warm"
        plan2, dt, n, status, rows = one_run(sql, params, shape)
        if plan2 != plan:
            print(f"    (plan on run {i + 1} differs: {plan2})")
        nstr = f"rows={n}" if shape == "rows" else f"count={n}"
        print(f"    {tag}: {dt * 1000:,.0f} ms  {nstr}  {status}")
        rec["runs"].append(
            {"tag": tag, "ms": round(dt * 1000), "n": n, "status": status}
        )
        rec["_rows"] = rows
        if status != "ok":
            break
    RESULTS.append(rec)
    return rec


def warm_ms(rec):
    ok = [r for r in rec["runs"] if r.get("status") == "ok"]
    return ok[-1]["ms"] if ok else None


def fetch(sql, params=(), n=200):
    conn = connect(timeout=TIMEOUT_S)
    try:
        with closing(conn.cursor()) as cur:
            cur.execute(sql, params)
            return cur.fetchmany(n)
    finally:
        conn.close()


def main():
    out_json = Path(__file__).with_name("routing_eventscans_plans_2026-10-21.json")
    print(
        "QT-000007 line 3 — plans and timings, run", time.strftime("%Y-%m-%d %H:%M:%S")
    )
    print(
        "timeout per statement:",
        TIMEOUT_S,
        "s; rows shape fetches FIRST",
        ROWS_SHAPE_LIMIT,
    )

    # --- samples from tables that are NOT the ones under test ---------------
    # Waybills captured a week ago (VIEW_WBANALYSE by WAYDATE, indexed) so the
    # ROUTING / EVENT pages for them are cold on the first run.
    wbs = [
        r[0]
        for r in fetch(
            "SELECT FIRST 50 WAYBILL FROM VIEW_WBANALYSE WHERE WAYDATE = DATE '2026-10-13' "
            "AND WAYBILL NOT LIKE '~%' AND WAYBILL NOT LIKE '%/%' AND ACCNUM = 'S135' ORDER BY WAYBILL",
            n=50,
        )
    ]
    wb1 = wbs[0]
    wb5 = wbs[:5]
    wb50 = wbs[:50]
    print(
        f"\nsample waybills: {len(wbs)} from VIEW_WBANALYSE WAYDATE 2026-10-13 ACCNUM S135; wb1={wb1}"
    )

    # A parcel tracking number for the same waybill, from TRACK by its PK
    # (TRACK is 14M rows; the PK lookup is keyed, not a scan).
    try:
        trk = fetch(
            "SELECT FIRST 5 TRACKNO, PARCELNO FROM TRACK WHERE WAYBILL = ?", (wb1,), n=5
        )
        print(f"TRACK rows for {wb1}: {trk}")
        trackno = trk[0][0] if trk else wb1
    except Exception as e:
        print("TRACK not readable by this login:", str(e)[:120])
        trackno = wb1

    # The event-type lookup the view's NAME column comes from.
    try:
        rules = fetch("SELECT EVENTTYPE, NAME FROM SCANRULE ORDER BY EVENTTYPE", n=200)
        print(f"SCANRULE: {len(rules)} rows")
        for et, nm in rules:
            print(f"    {et!r:8} {nm}")
        collect_type = next(
            (
                et
                for et, nm in rules
                if (nm or "").strip().lower() == "collected from origin address"
            ),
            None,
        )
    except Exception as e:
        print("SCANRULE not readable by this login:", str(e)[:120])
        rules, collect_type = [], None
    print("event type for 'Collected from Origin Address':", collect_type)

    D1 = ("2026-10-19", "2026-10-19")  # 1 day (Monday)
    D7 = ("2026-10-05", "2026-10-11")  # 7 days, disjoint from D1
    D31 = ("2026-08-31", "2026-09-30")  # 31 days, disjoint from both
    inl5 = ", ".join(f"'{w}'" for w in wb5)
    inl50 = ", ".join(f"'{w}'" for w in wb50)

    RCOLS = "WAYBILL, LEG, MBRANCH, MTYPE, MANIFEST, AGENT, AGENTDATE, BOOKDATE, ORIGHUB, DESTHUB, STATUS"

    print("\n\n======================= ROUTING =======================")
    measure(
        "R1 ROUTING by WAYBILL = one",
        f"SELECT FIRST 501 {RCOLS} FROM ROUTING WHERE WAYBILL = ?",
        (wb1,),
    )
    measure(
        "R2 ROUTING by WAYBILL IN (5)",
        f"SELECT FIRST 501 {RCOLS} FROM ROUTING WHERE WAYBILL IN ({inl5})",
    )
    measure(
        "R2b ROUTING by WAYBILL IN (50)",
        f"SELECT FIRST 501 {RCOLS} FROM ROUTING WHERE WAYBILL IN ({inl50})",
    )
    measure(
        "R3 ROUTING by MANIFEST+MBRANCH+MTYPE (trip 37733, branch 0, M)",
        f"SELECT FIRST 501 {RCOLS} FROM ROUTING WHERE MANIFEST = 37733 AND MBRANCH = 0 AND MTYPE = 'M'",
    )
    measure(
        "R3b ROUTING by MANIFEST+MBRANCH+MTYPE (trip 1016558, branch 1, M)",
        f"SELECT FIRST 501 {RCOLS} FROM ROUTING WHERE MANIFEST = 1016558 AND MBRANCH = 1 AND MTYPE = 'M'",
    )
    measure(
        "R3c ROUTING by MANIFEST alone (37733)",
        "SELECT COUNT(*) FROM ROUTING WHERE MANIFEST = 37733",
        shape="count",
    )
    for name, (a, b), days in (
        ("1 day", D1, 1),
        ("7 days", D7, 7),
        ("31 days", D31, 31),
    ):
        measure(
            f"R4 ROUTING AGENTDATE BETWEEN {name} — count",
            f"SELECT COUNT(*) FROM ROUTING WHERE AGENTDATE BETWEEN DATE '{a}' AND DATE '{b}'",
            shape="count",
        )
        measure(
            f"R4 ROUTING AGENTDATE BETWEEN {name} — rows",
            f"SELECT FIRST 501 {RCOLS} FROM ROUTING WHERE AGENTDATE BETWEEN DATE '{a}' AND DATE '{b}'",
        )
    for name, (a, b), days in (
        ("1 day", D1, 1),
        ("7 days", D7, 7),
        ("31 days", D31, 31),
    ):
        measure(
            f"R5 ROUTING BOOKDATE BETWEEN {name} — count",
            f"SELECT COUNT(*) FROM ROUTING WHERE BOOKDATE BETWEEN DATE '{a}' AND DATE '{b}'",
            shape="count",
        )
        measure(
            f"R5 ROUTING BOOKDATE BETWEEN {name} — rows",
            f"SELECT FIRST 501 {RCOLS} FROM ROUTING WHERE BOOKDATE BETWEEN DATE '{a}' AND DATE '{b}'",
        )
    # Wider AGENTDATE windows only if 31 days was cheap (knee-finding).
    r31 = next(
        r
        for r in RESULTS
        if r["label"].startswith("R4 ROUTING AGENTDATE BETWEEN 31 days — count")
    )
    if (warm_ms(r31) or 10**9) < 2500:
        for name, (a, b) in (
            ("62 days", ("2026-07-31", "2026-09-30")),
            ("92 days", ("2026-07-01", "2026-09-30")),
        ):
            measure(
                f"R4x ROUTING AGENTDATE BETWEEN {name} — count",
                f"SELECT COUNT(*) FROM ROUTING WHERE AGENTDATE BETWEEN DATE '{a}' AND DATE '{b}'",
                shape="count",
            )
    # The thing the guard prevents: one unbounded count, once, abort at 60 s.
    measure(
        "R6 ROUTING unbounded COUNT(*)",
        "SELECT COUNT(*) FROM ROUTING",
        shape="count",
        allow_natural=True,
        runs=1,
    )
    # A date-window aggregate of the kind a user would actually ask (not just COUNT).
    measure(
        "R7 ROUTING 7-day AGENTDATE aggregate by MTYPE/hub pair",
        f"SELECT MTYPE, ORIGHUB, DESTHUB, COUNT(*), COUNT(DISTINCT WAYBILL) FROM ROUTING "
        f"WHERE AGENTDATE BETWEEN DATE '{D7[0]}' AND DATE '{D7[1]}' GROUP BY 1, 2, 3",
        shape="rows",
    )

    print("\n\n======================= VIEW_EVENTSCANS =======================")
    VCOLS = "WAYBILL, TRACKNO, EVENTDATE, EVENTTIME, NAME, HUB, MANIFEST, ACCNUM, WAYDATE, ORIGHUB, DESTHUB"
    measure(
        "V1 VIEW_EVENTSCANS by WAYBILL = one, ordered (tool a shape)",
        f"SELECT FIRST 501 {VCOLS} FROM VIEW_EVENTSCANS WHERE WAYBILL = ? ORDER BY EVENTDATE, EVENTTIME",
        (wb1,),
    )
    measure(
        "V1b VIEW_EVENTSCANS by WAYBILL IN (5)",
        f"SELECT FIRST 501 {VCOLS} FROM VIEW_EVENTSCANS WHERE WAYBILL IN ({inl5})",
    )
    measure(
        "V2 VIEW_EVENTSCANS by TRACKNO = one",
        f"SELECT FIRST 501 {VCOLS} FROM VIEW_EVENTSCANS WHERE TRACKNO = ?",
        (trackno,),
    )
    # EVENTDATE windows: rows shape first (cheap if indexed), then count 1 day,
    # then 7 days only if 1 day came back under 8 s warm.
    measure(
        "V3 VIEW_EVENTSCANS EVENTDATE BETWEEN 1 day — rows",
        f"SELECT FIRST 501 {VCOLS} FROM VIEW_EVENTSCANS WHERE EVENTDATE BETWEEN DATE '{D1[0]}' AND DATE '{D1[1]}'",
    )
    v1c = measure(
        "V3 VIEW_EVENTSCANS EVENTDATE BETWEEN 1 day — count",
        f"SELECT COUNT(*) FROM VIEW_EVENTSCANS WHERE EVENTDATE BETWEEN DATE '{D1[0]}' AND DATE '{D1[1]}'",
        shape="count",
    )
    if (warm_ms(v1c) or 10**9) < 8000:
        measure(
            "V3 VIEW_EVENTSCANS EVENTDATE BETWEEN 7 days — rows",
            f"SELECT FIRST 501 {VCOLS} FROM VIEW_EVENTSCANS WHERE EVENTDATE BETWEEN DATE '{D7[0]}' AND DATE '{D7[1]}'",
        )
        v7c = measure(
            "V3 VIEW_EVENTSCANS EVENTDATE BETWEEN 7 days — count",
            f"SELECT COUNT(*) FROM VIEW_EVENTSCANS WHERE EVENTDATE BETWEEN DATE '{D7[0]}' AND DATE '{D7[1]}'",
            shape="count",
        )
        if (warm_ms(v7c) or 10**9) < 2000:
            measure(
                "V3x VIEW_EVENTSCANS EVENTDATE BETWEEN 31 days — count",
                f"SELECT COUNT(*) FROM VIEW_EVENTSCANS WHERE EVENTDATE BETWEEN DATE '{D31[0]}' AND DATE '{D31[1]}'",
                shape="count",
            )
    else:
        print("    (7-day EVENTDATE window skipped: 1-day count was not under 8 s)")
    # WAYDATE windows (WAYDATE is WAYBILL.WAYDATE — the outer join side).
    measure(
        "V4 VIEW_EVENTSCANS WAYDATE BETWEEN 1 day — rows",
        f"SELECT FIRST 501 {VCOLS} FROM VIEW_EVENTSCANS WHERE WAYDATE BETWEEN DATE '{D1[0]}' AND DATE '{D1[1]}'",
    )
    v1c = measure(
        "V4 VIEW_EVENTSCANS WAYDATE BETWEEN 1 day — count",
        f"SELECT COUNT(*) FROM VIEW_EVENTSCANS WHERE WAYDATE BETWEEN DATE '{D1[0]}' AND DATE '{D1[1]}'",
        shape="count",
    )
    if (warm_ms(v1c) or 10**9) < 8000:
        measure(
            "V4 VIEW_EVENTSCANS WAYDATE BETWEEN 7 days — count",
            f"SELECT COUNT(*) FROM VIEW_EVENTSCANS WHERE WAYDATE BETWEEN DATE '{D7[0]}' AND DATE '{D7[1]}'",
            shape="count",
        )
    else:
        print("    (7-day WAYDATE window skipped: 1-day count was not under 8 s)")
    # ACCNUM + 7-day window, both date columns.
    measure(
        "V5 VIEW_EVENTSCANS ACCNUM + WAYDATE 7 days — rows",
        f"SELECT FIRST 501 {VCOLS} FROM VIEW_EVENTSCANS WHERE ACCNUM = 'S135' AND WAYDATE BETWEEN DATE '{D7[0]}' AND DATE '{D7[1]}'",
    )
    measure(
        "V5 VIEW_EVENTSCANS ACCNUM + WAYDATE 7 days — count",
        f"SELECT COUNT(*) FROM VIEW_EVENTSCANS WHERE ACCNUM = 'S135' AND WAYDATE BETWEEN DATE '{D7[0]}' AND DATE '{D7[1]}'",
        shape="count",
    )
    measure(
        "V5b VIEW_EVENTSCANS ACCNUM + EVENTDATE 7 days — count",
        f"SELECT COUNT(*) FROM VIEW_EVENTSCANS WHERE ACCNUM = 'S135' AND EVENTDATE BETWEEN DATE '{D7[0]}' AND DATE '{D7[1]}'",
        shape="count",
    )
    # Predicates a user might think are windows but which the planner cannot push.
    measure(
        "V6 VIEW_EVENTSCANS by NAME only (no window) — plan only",
        "SELECT FIRST 501 WAYBILL FROM VIEW_EVENTSCANS WHERE NAME = 'Collected from Origin Address'",
    )
    measure(
        "V6b VIEW_EVENTSCANS by HUB + EVENTDATE 1 day — count",
        f"SELECT COUNT(*) FROM VIEW_EVENTSCANS WHERE HUB = 'JNB' AND EVENTDATE BETWEEN DATE '{D1[0]}' AND DATE '{D1[1]}'",
        shape="count",
    )
    measure(
        "V6c VIEW_EVENTSCANS by MANIFEST (37733) — plan + rows",
        f"SELECT FIRST 501 {VCOLS} FROM VIEW_EVENTSCANS WHERE MANIFEST = 37733",
    )

    print(
        "\n\n======================= Reuven's two event tools (quote input) ======================="
    )
    # (a) every scan for one waybill, ordered — via the view (V1 above) and
    #     directly on EVENT (parcel-level TRACKNOs come from TRACK).
    measure(
        "E1 EVENT direct: all scans for one waybill incl. parcel tracknos, ordered",
        "SELECT e.EVENTDATE, e.EVENTTIME, e.EVENTTYPE, e.HUB, e.MANIFEST, e.TRACKNO FROM EVENT e WHERE e.TRACKNO = ? "
        "UNION ALL "
        "SELECT e.EVENTDATE, e.EVENTTIME, e.EVENTTYPE, e.HUB, e.MANIFEST, e.TRACKNO FROM EVENT e "
        "JOIN TRACK t ON t.TRACKNO = e.TRACKNO WHERE t.WAYBILL = ? AND t.TRACKNO <> ? "
        "ORDER BY 1, 2",
        (wb1, wb1, wb1),
    )
    # (b) scans per day and per hub for ONE event type over 1 / 7 / 31 days.
    #     First: how many events per type on one day (sizes the worst case).
    bytype = measure(
        "E2a EVENT: events per type on one day (sizing)",
        f"SELECT EVENTTYPE, COUNT(*) FROM EVENT WHERE EVENTDATE = DATE '{D1[0]}' GROUP BY 1 ORDER BY 2 DESC",
        shape="rows",
    )
    rows = bytype.get("_rows") or []
    print(
        "    per-type counts on",
        D1[0],
        ":",
        [(et.strip() if isinstance(et, str) else et, c) for et, c in rows[:12]],
    )
    heavy_type = rows[0][0] if rows else None
    types_to_test = [t for t in (collect_type, heavy_type) if t]
    for et in types_to_test:
        for name, (a, b) in (("1 day", D1), ("7 days", D7), ("31 days", D31)):
            r = measure(
                f"E2 EVENT direct: per day per hub, EVENTTYPE={et!r}, {name}",
                "SELECT EVENTDATE, HUB, COUNT(*) FROM EVENT WHERE EVENTTYPE = ? "
                f"AND EVENTDATE BETWEEN DATE '{a}' AND DATE '{b}' GROUP BY 1, 2 ORDER BY 1, 2",
                (et,),
                shape="rows",
            )
            if (warm_ms(r) or 10**9) > 8000:
                print("    (wider windows for this type skipped: over 8 s)")
                break
    # The same shape through the view by NAME (plan first; executes only if pushed).
    if collect_type:
        measure(
            "E3 VIEW_EVENTSCANS: per day per hub by NAME, 1 day",
            "SELECT EVENTDATE, HUB, COUNT(*) FROM VIEW_EVENTSCANS WHERE NAME = 'Collected from Origin Address' "
            f"AND EVENTDATE BETWEEN DATE '{D1[0]}' AND DATE '{D1[1]}' GROUP BY 1, 2 ORDER BY 1, 2",
            shape="rows",
        )

    # --- summary table --------------------------------------------------------
    print("\n\n======================= SUMMARY =======================")
    print(f"{'label':<78} {'shape':<5} {'cold ms':>8} {'warm ms':>8} {'n':>9}  plan")
    for r in RESULTS:
        runs = r["runs"]
        cold = next((x["ms"] for x in runs if x.get("tag") == "cold"), None)
        warm = next((x["ms"] for x in runs if x.get("tag") == "warm"), None)
        n = next((x.get("n") for x in reversed(runs) if x.get("n") is not None), None)
        st = next(
            (x["status"] for x in runs if x.get("status") not in ("ok", None)), ""
        )
        cs = f"{cold:,}" if cold is not None else "-"
        ws = f"{warm:,}" if warm is not None else "-"
        ns = f"{n:,}" if isinstance(n, int) else "-"
        print(
            f"{r['label'][:78]:<78} {r['shape']:<5} {cs:>8} {ws:>8} {ns:>9}  {r['plan'][:110]} {st}"
        )
    for r in RESULTS:
        r.pop("_rows", None)
    out_json.write_text(json.dumps(RESULTS, indent=1, default=str), encoding="utf-8")
    print("\nraw results:", out_json)


if __name__ == "__main__":
    main()
