"""Extraction verification + discovery — Phase 2/3 iteration 2.

Run on the BI server from the repo root (same .env):

    uv run research/revenue_extract_verify.py

What it does (read-only):
  1. Dumps every DB column used by revenue_reports/extract_revenue.py's
     COLUMN_MAP for waybills dated 22-27 Jul 2026 (the reconciliation window)
     to verify_columns_<today>.csv — drop it in the Claude General folder;
     Claude diffs it per-column against the 28 Jul manual export to confirm
     or correct every VERIFY-marked mapping (surcharge names, CARTAGE, CCNAME,
     VATDESCRIPTION, COLSTATUS, NOTEPRESENT, PODDETAILS, ROUTING_FAILTYPE).
  2. Hunts the "Consolidated" flag: any column named %CONSOL% in any relation.
  3. Dumps surcharge-definition candidates (%SURCH% relations, small ones in
     full) to map SURCHARGE1..9 to their display names independently.
  4. Hunts the credits/receipts data pool: %RECEIPT% relations + columns,
     plus a full list of all user relations (the smoke-test scan missed the
     credits table; the credits export is receipts-side data — negative
     Receipt numbers, Allocated/Unallocated/Bank/Cash columns).
  5. Samples negative-receipt rows from the best candidate table and prints
     type/reason distributions, to finalise CREDITS_SQL_TEMPLATE.

Paste the full output back + drop the CSV in the Claude General folder.
"""

import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from research.revenue_extraction_test import (
    connect,
    list_columns,
    query_df,
)

from revenue_reports.extract_revenue import DB_COLS

WINDOW = ("2026-07-22", "2026-07-27")


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


def main() -> None:
    log = f"verify_output_{date.today().isoformat()}.txt"
    sys.stdout = _Tee(log)
    print(f"(also writing this output to {log})\n")
    conn = connect()

    print("== 1. Column-verification dump ==")
    sql = f"""
        SELECT {', '.join(DB_COLS)}
        FROM VIEW_WBANALYSE
        WHERE WAYDATE BETWEEN DATE '{WINDOW[0]}' AND DATE '{WINDOW[1]}'
          AND WAYBILL NOT LIKE '%~%'
          AND STATUS <> 'Cancelled';
    """
    df = query_df(conn, sql)
    out = f"verify_columns_{date.today().isoformat()}.csv"
    df.to_csv(out, index=False)
    print(f"{len(df)} rows x {len(df.columns)} cols -> {out} "
          "(drop in Claude General folder)")
    print(f"Subtotal sum: {pd.to_numeric(df['SUBTOTAL'], errors='coerce').sum():,.2f}\n")

    print("== 2. 'Consolidated' flag hunt (%CONSOL% columns anywhere) ==")
    cons = query_df(conn, """
        SELECT TRIM(RF.RDB$RELATION_NAME) AS REL, TRIM(RF.RDB$FIELD_NAME) AS FIELD
        FROM RDB$RELATION_FIELDS RF
        JOIN RDB$RELATIONS R ON R.RDB$RELATION_NAME = RF.RDB$RELATION_NAME
        WHERE R.RDB$SYSTEM_FLAG = 0
          AND (RF.RDB$FIELD_NAME LIKE '%CONSOL%' OR RF.RDB$FIELD_NAME LIKE '%CONSIG%GROUP%')
        ORDER BY 1, 2;
    """)
    print(cons.to_string(index=False) if len(cons) else "No matches.")
    print()

    print("== 3. Surcharge definitions (%SURCH% relations) ==")
    surch = query_df(conn, """
        SELECT TRIM(RDB$RELATION_NAME) AS REL FROM RDB$RELATIONS
        WHERE RDB$SYSTEM_FLAG = 0 AND RDB$RELATION_NAME LIKE '%SURCH%'
        ORDER BY 1;
    """)
    print(surch.to_string(index=False) if len(surch) else "No matches.")
    for rel in surch.get("REL", []):
        cols = list_columns(conn, rel)
        print(f"\n{rel}: {', '.join(cols)}")
        try:
            n = query_df(conn, f"SELECT COUNT(*) AS N FROM {rel}")["N"].iloc[0]
            if n <= 60:
                print(query_df(conn, f"SELECT * FROM {rel}").to_string(index=False))
            else:
                print(f"({n} rows — first 20)")
                print(query_df(conn, f"SELECT FIRST 20 * FROM {rel}").to_string(index=False))
        except Exception as e:
            print(f"(could not read: {e})")
    print()

    print("== 4a. %RECEIPT% relations ==")
    rcpt = query_df(conn, """
        SELECT TRIM(RDB$RELATION_NAME) AS REL, RDB$RELATION_TYPE AS RTYPE
        FROM RDB$RELATIONS
        WHERE RDB$SYSTEM_FLAG = 0 AND RDB$RELATION_NAME LIKE '%RECEIPT%'
        ORDER BY 1;
    """)
    print(rcpt.to_string(index=False) if len(rcpt) else "No matches.")
    for rel in rcpt.get("REL", []):
        print(f"\n{rel}: {', '.join(list_columns(conn, rel))}")
    print()

    print("== 4b. All user relations (full list — the credits table is in here) ==")
    rels = query_df(conn, """
        SELECT TRIM(RDB$RELATION_NAME) AS REL, RDB$RELATION_TYPE AS RTYPE
        FROM RDB$RELATIONS WHERE RDB$SYSTEM_FLAG = 0 ORDER BY 1;
    """)
    print(f"{len(rels)} relations:")
    print(", ".join(rels["REL"].tolist()))
    print()

    print("== 4c. Relations with a REASON-like column (credits have Reason codes) ==")
    reason = query_df(conn, """
        SELECT TRIM(RF.RDB$RELATION_NAME) AS REL, TRIM(RF.RDB$FIELD_NAME) AS FIELD
        FROM RDB$RELATION_FIELDS RF
        JOIN RDB$RELATIONS R ON R.RDB$RELATION_NAME = RF.RDB$RELATION_NAME
        WHERE R.RDB$SYSTEM_FLAG = 0
          AND (RF.RDB$FIELD_NAME LIKE '%REASON%' OR RF.RDB$FIELD_NAME LIKE '%ALLOC%')
        ORDER BY 1, 2;
    """)
    print(reason.to_string(index=False) if len(reason) else "No matches.")
    print()

    print("== 5. Negative-receipt sample from best candidate ==")
    # Try the obvious names in order; print whichever exists.
    for cand in ("RECEIPT", "RECEIPTS", "VIEW_RECEIPT", "VIEW_RECEIPTS"):
        cols = list_columns(conn, cand)
        if not cols:
            continue
        print(f"{cand}: {', '.join(cols)}")
        try:
            num_col = "RECEIPT" if "RECEIPT" in cols else cols[0]
            sample = query_df(conn, f"SELECT FIRST 10 * FROM {cand} WHERE {num_col} < 0")
            print(sample.to_string(index=False))
        except Exception as e:
            print(f"(sample failed: {e})")
        break
    else:
        print("No RECEIPT-named table — use the 4b list to pick the candidate.")

    conn.close()
    print("\nDone. Paste this whole output back + drop the CSV in Claude General.")


if __name__ == "__main__":
    main()
