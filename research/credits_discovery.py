"""Credits + Consolidated + Scan Batch discovery — Phase 2/3 iteration 3.

Run on the BI server from the repo root (same .env):

    uv run research/credits_discovery.py

Everything is read-only and small. Output tees to credits_discovery_<date>.txt;
one CSV (scanbatch_<date>.csv) verifies Scan Batch candidates. Drop both in the
Claude General folder.

What it resolves:
  1. Credits "Type"   — RECTYPE code distribution on negative receipts
                        (expect codes for Credit Note / Journal Credit /
                        Bad Debt / Cancelled).
  2. Credits "Reason" — NOTETYPE lookup table contents.
  3. Credits "User Name" — USERCODE lookup columns + sample.
  4. Credits capture date/time — hunt a source (not in RECEIPT's columns).
  5. Full recent credit sample joined to CUSTOMER — eyeball vs credits export.
  6. "Consolidated" flag — WAYREFTYPE contents + WAYREF rows for known
     consolidated=Yes vs =No waybills from the manual export.
  7. "Scan Batch" — IMAGEBATCH1 / PAGEEVENTBATCH dump for the recon window.
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

# From the 28 Jul manual WB export (22-27 Jul window):
CONSOL_YES = ["BSC3254638", "BSC3254926", "BSC3254931", "BSC3254932",
              "BSC3254936", "BSC3254940"]
CONSOL_NO_MULTIREF = ["DKS318310", "BSC3255359", "EZF318290", "102154273"]

CREDITS_START = "2024-03-01"  # credits export spans March24 - Feb27
WINDOW = ("2026-07-22", "2026-07-27")


def show(conn, title: str, sql: str) -> None:
    print(f"== {title} ==")
    try:
        print(query_df(conn, sql).to_string(index=False))
    except Exception as e:  # noqa: BLE001
        print(f"(failed: {e})")
    print()


def main() -> None:
    log = f"credits_discovery_{date.today().isoformat()}.txt"
    sys.stdout = _Tee(log)
    print(f"(also writing this output to {log})\n")
    conn = connect()

    show(conn, "1. RECTYPE distribution on credits (negative receipts)", f"""
        SELECT r.RECTYPE, COUNT(*) AS N, SUM(r.AMOUNT) AS AMOUNT_SUM
        FROM RECEIPT r
        WHERE r.RECEIPT < 0 AND r.RECDATE >= DATE '{CREDITS_START}'
        GROUP BY r.RECTYPE ORDER BY 2 DESC;
    """)
    # RECTYPE on positive receipts too, for contrast
    show(conn, "1b. RECTYPE distribution on positive receipts (contrast)", f"""
        SELECT r.RECTYPE, COUNT(*) AS N
        FROM RECEIPT r
        WHERE r.RECEIPT > 0 AND r.RECDATE >= DATE '{CREDITS_START}'
        GROUP BY r.RECTYPE ORDER BY 2 DESC;
    """)

    print("== 2. NOTETYPE lookup table ==")
    print(f"columns: {', '.join(list_columns(conn, 'NOTETYPE'))}")
    show(conn, "NOTETYPE contents", "SELECT * FROM NOTETYPE;")

    print("== 3. USERCODE lookup ==")
    print(f"columns: {', '.join(list_columns(conn, 'USERCODE'))}")
    show(conn, "USERCODE sample", "SELECT FIRST 10 * FROM USERCODE;")

    print("== 4. Capture date/time hunt ==")
    for rel in ("RECALLOC", "AUDIT", "PAYMENT", "BALANCE"):
        print(f"{rel}: {', '.join(list_columns(conn, rel))}")
    print()

    show(conn, "5. Recent credit sample (joined to CUSTOMER)", """
        SELECT FIRST 8 r.RECEIPT, r.ACCNUM, c.CUSTNAME, r.RECDATE, r.AMOUNT,
               r.VAT, r.DISCOUNT, r.REFERENCE, r.RECTYPE, r.NOTETYPE,
               r.ALLOCATED, r.USERCODE, r.BRANCH, r.EXPHEAD, r.BANK,
               r.APPROVED, r.COMMENT
        FROM RECEIPT r
        LEFT JOIN CUSTOMER c ON c.ACCNUM = r.ACCNUM
        WHERE r.RECEIPT < 0 AND r.RECDATE >= DATE '2026-07-01'
        ORDER BY r.RECDATE DESC;
    """)
    # Which CUSTOMER columns exist for Rep / Cost Centre / Credit Controller?
    print(f"CUSTOMER columns: {', '.join(list_columns(conn, 'CUSTOMER'))}\n")
    print(f"REP columns: {', '.join(list_columns(conn, 'REP'))}\n")

    print("== 6. 'Consolidated' hunt ==")
    print(f"WAYREF columns: {', '.join(list_columns(conn, 'WAYREF'))}")
    print(f"WAYREFTYPE columns: {', '.join(list_columns(conn, 'WAYREFTYPE'))}")
    show(conn, "WAYREFTYPE contents", "SELECT * FROM WAYREFTYPE;")
    wbs = "', '".join(CONSOL_YES + CONSOL_NO_MULTIREF)
    show(conn, "WAYREF rows for known Yes/No waybills "
               f"(Yes: {CONSOL_YES} / No: {CONSOL_NO_MULTIREF})", f"""
        SELECT * FROM WAYREF WHERE WAYBILL IN ('{wbs}');
    """)
    print(f"WAYBILL table columns: {', '.join(list_columns(conn, 'WAYBILL'))}\n")

    print("== 7. Scan Batch candidates ==")
    df = query_df(conn, f"""
        SELECT WAYBILL, PODBATCH, IMAGEBATCH1, PAGEEVENTBATCH
        FROM VIEW_WBANALYSE
        WHERE WAYDATE BETWEEN DATE '{WINDOW[0]}' AND DATE '{WINDOW[1]}'
          AND WAYBILL NOT LIKE '%~%' AND STATUS <> 'Cancelled';
    """)
    out = f"scanbatch_{date.today().isoformat()}.csv"
    df.to_csv(out, index=False)
    print(f"{len(df)} rows -> {out} (drop in Claude General folder)")

    conn.close()
    print("\nDone. Paste this output back + drop both files in Claude General.")


if __name__ == "__main__":
    main()
