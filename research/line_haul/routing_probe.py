"""Line-haul recon: does aggregating waybills through ROUTING beat reading
MANIFEST's own totals? Tested against a known RSL control-table trip.

Why (6 Aug findings, Tasks row "Line haul: link RSL control table…"): the old
Last-Manifest route recovered only 102 of trip 37733's 124 RSL waybills (82%
ceiling — last-touch only). ROUTING (6M rows, one row per waybill per leg)
carries the FULL waybill↔manifest history, so the ceiling should lift. This
probe prints, side by side, for one manifest:

  1. MANIFEST's own totals (NOWB, PIECES, CHARGEMASS, ACTKG, SUBTOTAL/TOTAL)
  2. ROUTING's aggregate (rows, distinct waybills, mass sums)
  3. Revenue for ROUTING's waybills joined through VIEW_WBANALYSE
     (count, SUM(SUBTOTAL), SUM(TOTAL), SUM(CHARGEMASS))

Compare against the July RSL control table's row for the trip (124 waybills;
revenue) — whichever side matches better is the aggregation the line-haul
extraction gets built on. Do NOT conclude in prose beyond the numbers: the
comparison against RSL "Revenue" needs Akha/staff to say what RSL counts.

Production-safe: read-only (db.run_select → read-committed read-only
transaction), equality-filtered on one manifest number, aggregates only —
no row pulls beyond a 20-row leg breakdown. ROUTING is deliberately OFF the
open path's allowlist; this probe runs below that fence by hand, like the
schema survey did.

Run from the repo root on the BI server:

    uv run python research\\line_haul\\routing_probe.py [--manifest 37733] [--mtype M]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mcp_server.db import run_select

TIMEOUT_S = 60


def q(sql, params=()):
    cols, rows = run_select(sql, params, max_rows=100, timeout=TIMEOUT_S)
    return cols, rows


def show(title, cols, rows):
    print(f"\n== {title} ==")
    if not rows:
        print("  (no rows)")
        return
    for r in rows:
        print("  " + " | ".join(f"{c}={v}" for c, v in zip(cols, r)))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", type=int, default=37733)
    ap.add_argument("--mtype", default="M")
    a = ap.parse_args()

    # 0. ROUTING's real column list (it is off the allowlist, so the schema
    #    context has nothing on it) — printed so any name drift below is a
    #    one-line fix rather than a mystery.
    cols, rows = q(
        "SELECT TRIM(rf.RDB$FIELD_NAME) FROM RDB$RELATION_FIELDS rf "
        "WHERE rf.RDB$RELATION_NAME = 'ROUTING' ORDER BY rf.RDB$FIELD_POSITION"
    )
    routing_cols = [r[0] for r in rows]
    print("ROUTING columns:", ", ".join(routing_cols))

    # 1. MANIFEST's own totals for the trip.
    show(
        f"MANIFEST {a.manifest} (MTYPE={a.mtype!r}) — the trip's own totals",
        *q(
            "SELECT BRANCH, MANIFEST, MTYPE, AGENT, AGENTDATE, STARTDATE, "
            "ORIGHUB, DESTHUB, NOWB, PIECES, CHARGEMASS, ACTKG, VOLCM, "
            "SUBTOTAL, TOTAL FROM MANIFEST "
            "WHERE MANIFEST = ? AND MTYPE = ?",
            (a.manifest, a.mtype),
        ),
    )

    # 2. ROUTING's aggregate for the same trip.
    show(
        f"ROUTING aggregate for MANIFEST {a.manifest} (MTYPE={a.mtype!r})",
        *q(
            "SELECT COUNT(*) AS ROWS_, COUNT(DISTINCT WAYBILL) AS WAYBILLS, "
            "SUM(CHARGEMASS) AS CHARGEMASS, SUM(VOLMASS) AS VOLMASS "
            "FROM ROUTING WHERE MANIFEST = ? AND MTYPE = ?",
            (a.manifest, a.mtype),
        ),
    )
    show(
        "ROUTING leg breakdown (first 20)",
        *q(
            "SELECT FIRST 20 LEG, COUNT(*) AS ROWS_, "
            "COUNT(DISTINCT WAYBILL) AS WAYBILLS "
            "FROM ROUTING WHERE MANIFEST = ? AND MTYPE = ? "
            "GROUP BY LEG ORDER BY LEG",
            (a.manifest, a.mtype),
        ),
    )

    # 3. Revenue for ROUTING's waybills, joined through VIEW_WBANALYSE.
    #    Falls back to WAYBILLORIG if the plain join finds nothing — the two
    #    number columns exist side by side on the view and the join key has
    #    not been pinned before.
    for key in ("WAYBILL", "WAYBILLORIG"):
        cols, rows = q(
            f"SELECT COUNT(*) AS WAYBILLS, SUM(w.SUBTOTAL) AS SUBTOTAL, "
            f"SUM(w.TOTAL) AS TOTAL, SUM(w.CHARGEMASS) AS CHARGEMASS "
            f"FROM VIEW_WBANALYSE w WHERE w.{key} IN ("
            f"SELECT DISTINCT r.WAYBILL FROM ROUTING r "
            f"WHERE r.MANIFEST = ? AND r.MTYPE = ?)",
            (a.manifest, a.mtype),
        )
        show(f"Revenue via VIEW_WBANALYSE joined on {key}", cols, rows)
        if rows and rows[0][0]:
            break

    print(
        "\nCompare against the July RSL control table's row for this trip "
        "(124 waybills expected for 37733; Last-Manifest recovered 102). "
        "Save this output dated under research/line_haul/."
    )


if __name__ == "__main__":
    main()
