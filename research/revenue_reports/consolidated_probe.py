"""Consolidated flag probe + credits trial — Phase 2/3 iteration 4.

Run on the BI server from the repo root (same .env):

    uv run research/consolidated_probe.py

Output tees to consolidated_probe_<date>.txt; writes two CSVs. Drop all three
in the Claude General folder.

What it resolves:
  1. "Consolidated" — the last unmapped builder-consumed column. Not
     derivable from Ref Count / First Ref / account level (tested locally).
     Dumps WAYBILL.* + INVWAY rows for known Yes/No waybills so the
     differing field can be spotted by direct comparison.
  2. BRANCH and COSTCNTR name lookups (credits export shows names, RECEIPT
     holds codes).
  3. Credits trial: runs the production CREDITS_SQL for RECDATE >= 2026-06-01
     to credits_trial_<date>.csv — reconciled locally against the manual
     "Credits - March24 - Feb27.xls" (types, reasons, joins, arithmetic).
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from research.revenue_extract_verify import _Tee
from research.revenue_extraction_test import (
    connect,
    list_columns,
    query_df,
)
from revenue_reports.extract_revenue import CREDITS_SQL

# Iteration 5 sample: DIVERSE account/service pairs — each Yes has a No from
# the SAME account + service (first sample was confounded: one account/invoice).
CONSOL_YES = ["32755097", "HFX050626050", "260624-132759", "32745911",
              "80428858", "102154157", "102154149", "46248360"]
CONSOL_NO = ["32802147", "COL0308439", "260715-094431", "32787419",
             "61279", "SL0288439C", "102154318", "46241679"]


def show(conn, title: str, sql: str) -> None:
    print(f"== {title} ==")
    try:
        print(query_df(conn, sql).to_string(index=False))
    except Exception as e:
        print(f"(failed: {e})")
    print()


def main() -> None:
    log = f"consolidated_probe_{date.today().isoformat()}.txt"
    sys.stdout = _Tee(log)
    print(f"(also writing this output to {log})\n")
    conn = connect()
    wbs = "', '".join(CONSOL_YES + CONSOL_NO)

    print("== 1a. WAYBILL.* for known Yes/No waybills -> CSV ==")
    try:
        df = query_df(conn, f"SELECT * FROM WAYBILL WHERE WAYBILL IN ('{wbs}')")
        out = f"waybill_probe_{date.today().isoformat()}.csv"
        df.to_csv(out, index=False)
        print(f"{len(df)} rows x {len(df.columns)} cols -> {out}")
        print(f"(Yes: {CONSOL_YES} / No: {CONSOL_NO})")
    except Exception as e:
        print(f"(failed: {e})")
    print()

    print("== 1b. INVWAY / PROINVWAY columns + rows for those waybills ==")
    for rel in ("INVWAY", "PROINVWAY"):
        print(f"{rel}: {', '.join(list_columns(conn, rel))}")
    show(conn, "INVWAY rows",
         f"SELECT * FROM INVWAY WHERE WAYBILL IN ('{wbs}');")

    print("== 1c. CUSTOMER consolidation-ish fields for those accounts ==")
    show(conn, "CUSTOMER fields", f"""
        SELECT ACCNUM, INVWAYBILL, INVGROUP, CCINVSPLIT, CONPERPIECE,
               INVREQ, REDELMODE
        FROM CUSTOMER
        WHERE ACCNUM IN (SELECT ACCNUM FROM WAYBILL
                         WHERE WAYBILL IN ('{wbs}'));
    """)

    show(conn, "2a. BRANCH lookup", "SELECT * FROM BRANCH;")
    print(f"COSTCNTR columns: {', '.join(list_columns(conn, 'COSTCNTR'))}")
    show(conn, "2b. COSTCNTR lookup", "SELECT FIRST 30 * FROM COSTCNTR;")

    print("== 3. Credits trial (production CREDITS_SQL, from 2026-06-01) ==")
    try:
        df = query_df(conn, CREDITS_SQL.format(start="2026-06-01"))
        out = f"credits_trial_{date.today().isoformat()}.csv"
        df.to_csv(out, index=False)
        print(f"{len(df)} rows -> {out}")
    except Exception as e:
        print(f"(FAILED — paste this error back: {e})")

    conn.close()
    print("\nDone. Drop the txt + both CSVs in the Claude General folder.")


if __name__ == "__main__":
    main()
