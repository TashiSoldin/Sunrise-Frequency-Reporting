"""Fleet probe — can a vehicle utilisation figure actually be built, and from what.

Run on the BI server from the repo root (same .env):

    uv run research/fleet_probe.py --out-dir "<Database Reference folder>"

Read-only, and bounded: every query over a large table is filtered to a date
window (default 90 days) or grouped, so nothing scans ROUTING's 6 million rows
or EVENT's 113 million.

WHY THIS EXISTS. Larry asked on the 6 Aug acceptance call for the vehicle
utilisation tables. The schema survey the same day found there is no such table:
utilisation would be a figure we compute from what freight a vehicle carried
against what it can carry. Before anyone agrees a definition with him, we need
to know which definitions the data can actually support. A definition that rests
on a column which is empty in practice is the plausible-looking wrong number
this project has already produced three times.

It also tests two structural hypotheses that came out of reading the schema
against the Parcel Perfect manuals. Both are guesses until this run:

  1. MANIFEST.MTYPE separates line-haul manifests from delivery tripsheets.
     The manuals describe them as different legs -- manifest is hub to hub,
     tripsheet is "waybills loaded for final delivery with a specific
     driver/vehicle on a specific day" -- but there is no tripsheet table
     beyond the denied three-column TRIPSHEET_EXPORT, and PP presents both
     under Consolidate. If the hypothesis holds, one table carries both legs.

  2. AGENT.OWNRESOURCE (with AGENTTYPE and MTYPE) separates Sunrise's own
     vehicles from third-party agents. AGENT is the driver/vehicle entity --
     "Assign to Agent, choose the driver/vehicle" -- but third-party line-haul
     and collection agents are AGENT rows too, so its 1 220 rows are not 1 220
     vehicles. Dividing freight by a fleet that includes other people's trucks
     would be wrong in a way that still looks reasonable.

And it maps the join. VIEW_WBANALYSE carries no manifest number and neither
does WAYBILL; ROUTING does, one row per waybill per leg, with MTYPE, MANIFEST,
AGENT, CHARGEMASS, VOLMASS and hubs. That makes ROUTING the waybill-to-trip
link -- which also matters to line haul (QT-000005), where the July trial could
only recover last-touch manifests off the staff export's Last Manifest column.

WHAT IT WRITES, into --out-dir:

    fleet_probe_<date>.txt          the full log
    fleet_population_<date>.csv     per MTYPE, how populated each candidate
                                    utilisation column actually is

WHAT TO DO WITH THE OUTPUT. Read the population table first. Any column below
about 80% populated cannot carry a definition Larry would rely on, and should
be ruled out before it is offered to him rather than after.
"""

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from research.revenue_extraction_test import connect, query_df


class _Tee:
    """Duplicate stdout to a file so the whole run lands on disk too."""

    def __init__(self, path: str):
        self.file = open(path, "w", encoding="utf-8")
        self.stdout = sys.stdout

    def write(self, s):
        self.stdout.write(s)
        self.file.write(s)

    def flush(self):
        self.stdout.flush()
        self.file.flush()


# The columns a utilisation figure could be built on, and what each would mean.
# Ruled in or out by how populated they turn out to be, not by how sensible
# they sound.
CANDIDATES = {
    "CHARGEMASS": "chargeable mass carried on the trip",
    "ACTKG": "actual mass carried on the trip",
    "VOLCM": "volume carried on the trip",
    "VOLMASS": "volumetric mass carried on the trip",
    "PIECES": "pieces carried on the trip",
    "NOWB": "waybills on the trip",
    "STARTKM": "odometer at departure",
    "ENDKM": "odometer at return",
    "DRIVER": "which driver ran the trip",
    "ROUTE": "which route the trip ran",
    "DEPARTTIME": "when the trip left",
}


def show(conn, title: str, sql: str) -> None:
    print(f"== {title} ==")
    try:
        df = query_df(conn, sql)
        print(df.to_string(index=False) if len(df) else "(no rows)")
    except Exception as e:
        print(f"(failed: {type(e).__name__}: {e})")
    print()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", default=".", help="where the output files land")
    ap.add_argument("--days", type=int, default=90,
                    help="window for the population checks (default 90)")
    args = ap.parse_args()

    today = date.today()
    since = (today - timedelta(days=args.days)).isoformat()
    until = today.isoformat()
    # Bounded at BOTH ends. The 6 Aug run was bounded only below, and MANIFEST
    # turned out to hold AGENTDATEs in 2027 and 4015 — empty shells carrying no
    # freight, which sat inside the window and dragged every population
    # percentage down. That is the fourth time on this project that an
    # unbounded date has produced a wrong number, and it did not raise.
    window = f"m.AGENTDATE >= DATE '{since}' AND m.AGENTDATE <= DATE '{until}'"
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / f"fleet_probe_{today.isoformat()}.txt"
    sys.stdout = _Tee(str(log_path))
    print(f"(also writing this output to {log_path})")
    print(f"window for population checks: {since} to {until} (bounded both ends)\n")

    conn = connect()

    # ---- how dirty is the date column? --------------------------------------
    show(conn, "0. MANIFEST.AGENTDATE sanity — how much of it is junk", f"""
        SELECT m.MTYPE,
               COUNT(*) AS ROWS_TOTAL,
               SUM(CASE WHEN m.AGENTDATE < DATE '2015-01-01' THEN 1 ELSE 0 END) AS BEFORE_2015,
               SUM(CASE WHEN m.AGENTDATE > DATE '{until}' THEN 1 ELSE 0 END) AS IN_THE_FUTURE,
               SUM(CASE WHEN m.AGENTDATE > DATE '{until}' AND COALESCE(m.NOWB, 0) = 0
                        THEN 1 ELSE 0 END) AS FUTURE_AND_EMPTY
        FROM MANIFEST m
        GROUP BY m.MTYPE;
    """)
    print("READ THIS AS: FUTURE_AND_EMPTY rows are shells — a trip record with a\n"
          "mis-keyed date and no freight on it. They are excluded from everything\n"
          "below by the upper bound, but they are worth seeing rather than\n"
          "silently filtering: they are also what any max() over this column\n"
          "would land on.\n")

    # ---- hypothesis 1: does MTYPE separate manifests from tripsheets? --------
    show(conn, "1. MANIFEST by MTYPE, within the window", f"""
        SELECT m.MTYPE,
               COUNT(*) AS TRIPS,
               MIN(m.AGENTDATE) AS FIRST_DATE,
               MAX(m.AGENTDATE) AS LAST_DATE,
               COUNT(DISTINCT m.AGENT) AS AGENTS,
               COUNT(DISTINCT m.ORIGHUB) AS ORIG_HUBS,
               COUNT(DISTINCT m.DESTHUB) AS DEST_HUBS
        FROM MANIFEST m
        WHERE {window}
        GROUP BY m.MTYPE
        ORDER BY 2 DESC;
    """)
    print("READ THIS AS: if one MTYPE runs hub-to-hub across many hub pairs and\n"
          "another concentrates on a single origin hub with many agents, that is\n"
          "line haul versus delivery tripsheets. If there is only one MTYPE, the\n"
          "hypothesis is wrong and tripsheets live somewhere else.\n")

    show(conn, "2. ROUTING by MTYPE (cross-check on the same code)", f"""
        SELECT r.MTYPE, COUNT(*) AS LEGS,
               COUNT(DISTINCT r.MANIFEST) AS TRIPS,
               COUNT(DISTINCT r.WAYBILL) AS WAYBILLS
        FROM ROUTING r
        WHERE r.AGENTDATE >= DATE '{since}'
        GROUP BY r.MTYPE
        ORDER BY 2 DESC;
    """)

    # ---- hypothesis 2: which AGENT rows are our own vehicles? ---------------
    show(conn, "3. AGENT by OWNRESOURCE / AGENTTYPE / MTYPE", """
        SELECT a.OWNRESOURCE, a.AGENTTYPE, a.MTYPE, a.USEDRIVER,
               COUNT(*) AS AGENTS,
               SUM(CASE WHEN a.DISABLE = 1 THEN 1 ELSE 0 END) AS DISABLED,
               SUM(CASE WHEN a.REGNO IS NOT NULL AND a.REGNO <> '' THEN 1 ELSE 0 END) AS HAS_REGNO,
               SUM(CASE WHEN a.CAPACITY > 0 THEN 1 ELSE 0 END) AS HAS_CAPACITY,
               SUM(CASE WHEN a.VOLCAPACITY > 0 THEN 1 ELSE 0 END) AS HAS_VOLCAPACITY
        FROM AGENT a
        GROUP BY a.OWNRESOURCE, a.AGENTTYPE, a.MTYPE, a.USEDRIVER
        ORDER BY 5 DESC;
    """)
    print("READ THIS AS: the capacity columns are the denominator of any\n"
          "utilisation ratio. If HAS_CAPACITY is small, no mass-against-capacity\n"
          "definition is available for most of the fleet, whatever the manifests\n"
          "say. That is a finding to take to Larry, not a problem to work around.\n")

    # The 6 Aug run found REGNO empty on all 1 220 agents and CAPACITY set on
    # one. But the agent NAMES read like "DBN OCD - KR12JP GP 5T" — hub, a
    # three-letter class, then what looks like a registration and a size. If
    # that convention holds it is where the fleet is actually described, and
    # it is a convention rather than data, so Larry has to confirm it.
    show(conn, "3b. Does the agent NAME convention hold against OWNRESOURCE?", """
        SELECT a.OWNRESOURCE,
               COUNT(*) AS AGENTS,
               SUM(CASE WHEN a.NAME LIKE '%OCD%' THEN 1 ELSE 0 END) AS NAME_OCD,
               SUM(CASE WHEN a.NAME LIKE '%ACD%' THEN 1 ELSE 0 END) AS NAME_ACD,
               SUM(CASE WHEN a.NAME LIKE '%LH%'  THEN 1 ELSE 0 END) AS NAME_LH,
               SUM(CASE WHEN a.DISABLE = 1 THEN 1 ELSE 0 END) AS DISABLED,
               SUM(CASE WHEN COALESCE(a.DISABLE, 0) <> 1 THEN 1 ELSE 0 END) AS ACTIVE
        FROM AGENT a
        GROUP BY a.OWNRESOURCE;
    """)
    print("READ THIS AS: OCD against OWNRESOURCE = 1 is the test. On 6 Aug it\n"
          "held directionally but not universally — OCD appeared on 75 of 360\n"
          "own-resource agents and 2 of 860 others — so the flag is the reliable\n"
          "discriminator and the name is a partial convention on top of it.\n"
          "A tonnage count was here and has been removed: it matched any name\n"
          "ending in T, which is not the same question, and 'GP BK' carries a\n"
          "size that does not end in T at all. A bad measure is worse than none.\n"
          "Parsing names is a judgement either way — put it to Larry.\n")

    show(conn, "4. Agents that actually ran trips in the window", f"""
        SELECT FIRST 25 a.AGENT, a.NAME, a.REGNO, a.VEHICLE, a.CAPACITY,
               a.VOLCAPACITY, a.OWNRESOURCE, a.AGENTTYPE,
               COUNT(m.MANIFEST) AS TRIPS
        FROM AGENT a
        JOIN MANIFEST m ON m.AGENT = a.AGENT
        WHERE {window}
        GROUP BY 1, 2, 3, 4, 5, 6, 7, 8
        ORDER BY 9 DESC;
    """)

    # ---- can any definition be built? --------------------------------------
    print(f"== 5. How populated is each candidate column, by MTYPE "
          f"(last {args.days} days) ==")
    parts = []
    for c in CANDIDATES:
        if c in ("DRIVER", "ROUTE", "DEPARTTIME"):
            parts.append(f"SUM(CASE WHEN m.{c} IS NOT NULL THEN 1 ELSE 0 END) AS {c}_SET")
        else:
            parts.append(
                f"SUM(CASE WHEN m.{c} IS NOT NULL AND m.{c} <> 0 THEN 1 ELSE 0 END) AS {c}_SET"
            )
    pop = None
    try:
        pop = query_df(conn, f"""
            SELECT m.MTYPE, COUNT(*) AS TRIPS, {", ".join(parts)}
            FROM MANIFEST m
            WHERE {window}
            GROUP BY m.MTYPE;
        """)
    except Exception as e:
        print(f"(failed: {type(e).__name__}: {e})\n")

    if pop is not None and len(pop):
        rows = []
        for _, r in pop.iterrows():
            trips = int(r["TRIPS"]) or 1
            print(f"\n  MTYPE {r['MTYPE']!r} — {int(r['TRIPS']):,} trips")
            for c, meaning in CANDIDATES.items():
                n = int(r[f"{c}_SET"])
                pct = 100.0 * n / trips
                verdict = "usable" if pct >= 80 else ("patchy" if pct >= 20 else "EMPTY")
                print(f"    {c:<12} {n:>8,}  {pct:5.1f}%  {verdict:<7} {meaning}")
                rows.append({"MTYPE": r["MTYPE"], "TRIPS": int(r["TRIPS"]),
                             "COLUMN": c, "POPULATED": n, "PERCENT": round(pct, 1),
                             "VERDICT": verdict, "MEANS": meaning})
        out = out_dir / f"fleet_population_{today.isoformat()}.csv"
        __import__("pandas").DataFrame(rows).to_csv(out, index=False)
        print(f"\n  -> {out}")
    print()

    # ---- does the join hold? ------------------------------------------------
    # Aggregate each side separately and join the aggregates. The 6 Aug version
    # joined MANIFEST to ROUTING and then did SUM(m.NOWB) over the result, which
    # counts every trip's NOWB once per leg — it reported 4 165 109 waybills
    # across 1 377 trips. Fanned-out sums are the same failure as an unbounded
    # date: a large plausible-looking number that nothing raises on.
    show(conn, "6. ROUTING legs against MANIFEST trips (aggregates joined, no fan-out)", f"""
        SELECT t.MTYPE, t.TRIPS, t.NOWB_TOTAL,
               r.TRIPS_SEEN_IN_ROUTING, r.LEGS
        FROM (
            SELECT m.MTYPE, COUNT(*) AS TRIPS, SUM(COALESCE(m.NOWB, 0)) AS NOWB_TOTAL
            FROM MANIFEST m
            WHERE {window}
            GROUP BY m.MTYPE
        ) t
        LEFT JOIN (
            SELECT rr.MTYPE,
                   COUNT(DISTINCT rr.MANIFEST) AS TRIPS_SEEN_IN_ROUTING,
                   COUNT(*) AS LEGS
            FROM ROUTING rr
            WHERE EXISTS (
                -- Matched on MTYPE as well as MANIFEST. Manifest numbers are
                -- not unique across MTYPE: filtering on the number alone let
                -- R-leg numbers pull in M-leg routing rows, and the 6 Aug run
                -- reported more trips seen in ROUTING (1 441) than existed in
                -- the window (1 376). About 5% over, and it read as a finding.
                SELECT 1 FROM MANIFEST m2
                WHERE m2.MANIFEST = rr.MANIFEST
                  AND m2.MTYPE = rr.MTYPE
                  AND m2.AGENTDATE >= DATE '{since}'
                  AND m2.AGENTDATE <= DATE '{until}'
            )
            GROUP BY rr.MTYPE
        ) r ON r.MTYPE = t.MTYPE;
    """)
    print("READ THIS AS: LEGS should land near NOWB_TOTAL, and\n"
          "TRIPS_SEEN_IN_ROUTING near TRIPS. A large gap means the join needs\n"
          "more than MANIFEST + MTYPE — check MBRANCH — and any trip-level figure\n"
          "built on it would be quietly short.\n")

    show(conn, "7. Recent trips end to end, for eyeballing", f"""
        SELECT FIRST 15 m.MANIFEST, m.MTYPE, m.AGENTDATE, m.AGENT, m.DRIVER,
               m.ROUTE, m.ORIGHUB, m.DESTHUB, m.NOWB, m.PIECES, m.CHARGEMASS,
               m.ACTKG, m.VOLCM, m.STARTKM, m.ENDKM, m.CLOSED, m.ALLDELIVERED
        FROM MANIFEST m
        WHERE {window} AND COALESCE(m.NOWB, 0) > 0
        ORDER BY m.AGENTDATE DESC, m.MANIFEST DESC;
    """)
    print("Filtered to trips that carried something. The 6 Aug run showed mostly\n"
          "empty shells dated 2027 and 4015, which told you about the date column\n"
          "rather than about a trip.\n")

    conn.close()
    print("Done. Drop the txt and csv in the Database Reference folder and paste "
          "the log back.\nNothing here is a utilisation figure — it is the check "
          "on which definitions are available to offer Larry.")


if __name__ == "__main__":
    main()
