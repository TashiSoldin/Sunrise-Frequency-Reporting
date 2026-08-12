"""Revenue extraction smoke test — Phase 1 of PLAN.md.

Run this on the BI server (or anywhere with DB access), from the repo root:

    uv run research/revenue_extraction_test.py

Requires the same .env as the notebooks: DB_HOST, DB_NAME, DB_USER, DB_PASSWORD, DB_ROLE.

What it does (read-only, small samples only):
  1. Connects to the Parcel Perfect Firebird DB.
  2. Lists every column of VIEW_WBANALYSE and checks which expected billing
     fields exist (the manual "Analyze Waybills" export is a dump of this view).
  3. Pulls a small recent sample on the waybill-date basis (tilde waybills
     excluded) and prints row count + Subtotal sum, for reconciliation against
     the manual export.
  4. Hunts for candidate credit-notes tables/views (different data pool).

Paste the full output back into the Claude session to design the production
extraction against the real schema.
"""

import os
import sys
from datetime import date

import firebirdsql
import pandas as pd
from dotenv import load_dotenv

SAMPLE_DAYS = 7

# Billing fields we expect to need, per the replication guide. Names are
# guesses until this script confirms them against the real view.
EXPECTED_FIELDS = [
    "WAYDATE",
    "WAYBILL",
    "ACCNUM",
    "CUSTNAME",
    "CHARGEMASS",
    "SUBTOTAL",
    "SALESREP",
    "INVOICEDATE",
    "INVOICENUM",
    "STATUS",
    "SERVICE",
    "REFERENCE",
    "ORIGHUB",
    "DESTHUB",
]


def connect() -> firebirdsql.Connection:
    load_dotenv()
    return firebirdsql.connect(
        host=os.getenv("DB_HOST"),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        role=os.getenv("DB_ROLE"),
        charset="latin1",
        use_unicode=True,
    )


def query_df(conn, sql: str) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()
        cols = [d[0].strip() for d in cur.description]
    return pd.DataFrame(rows, columns=cols)


def list_columns(conn, relation: str) -> list[str]:
    df = query_df(
        conn,
        f"""
        SELECT TRIM(RF.RDB$FIELD_NAME) AS COL
        FROM RDB$RELATION_FIELDS RF
        WHERE RF.RDB$RELATION_NAME = '{relation}'
        ORDER BY RF.RDB$FIELD_POSITION;
        """,
    )
    return df["COL"].tolist()


def main() -> None:
    print("== 1. Connecting ==")
    try:
        conn = connect()
    except Exception as e:
        print(f"CONNECTION FAILED: {e}")
        sys.exit(1)
    print("Connected OK.\n")

    print("== 2. VIEW_WBANALYSE columns ==")
    cols = list_columns(conn, "VIEW_WBANALYSE")
    print(f"{len(cols)} columns:")
    print(", ".join(cols) or "(none — view not found?)")
    present = [f for f in EXPECTED_FIELDS if f in cols]
    missing = [f for f in EXPECTED_FIELDS if f not in cols]
    print(f"\nExpected billing fields PRESENT: {present}")
    print(f"Expected billing fields MISSING: {missing}")
    print("(Missing ones may exist under other names — check the column list above.)\n")

    print(f"== 3. Sample: last {SAMPLE_DAYS} days, waybill-date basis ==")
    sample_cols = ", ".join(present) if present else "*"
    sample = query_df(
        conn,
        f"""
        SELECT {sample_cols}
        FROM VIEW_WBANALYSE wba
        WHERE wba.WAYDATE >= DATEADD(-{SAMPLE_DAYS} DAY TO CURRENT_DATE)
        AND wba.WAYDATE <= CURRENT_DATE
        AND wba.WAYBILL NOT LIKE '%~%';
        """,
    )
    print(f"Rows: {len(sample)}")
    if "SUBTOTAL" in sample.columns:
        print(f"Subtotal sum: {pd.to_numeric(sample['SUBTOTAL'], errors='coerce').sum():,.2f}")
    if "STATUS" in sample.columns:
        print(f"Status values: {sample['STATUS'].value_counts().to_dict()}")
    print(sample.head(5).to_string())
    out = f"revenue_sample_{date.today().isoformat()}.csv"
    sample.to_csv(out, index=False)
    print(f"Sample written to {out} — compare against the manual WB export.\n")

    print("== 4. Candidate credit-notes tables/views ==")
    candidates = query_df(
        conn,
        """
        SELECT TRIM(RDB$RELATION_NAME) AS REL, RDB$RELATION_TYPE AS RTYPE
        FROM RDB$RELATIONS
        WHERE RDB$SYSTEM_FLAG = 0
        AND (RDB$RELATION_NAME LIKE '%CREDIT%'
             OR RDB$RELATION_NAME LIKE '%CNOTE%'
             OR RDB$RELATION_NAME LIKE '%JOURNAL%'
             OR RDB$RELATION_NAME LIKE '%INVOICE%'
             OR RDB$RELATION_NAME LIKE '%DEBTOR%')
        ORDER BY 1;
        """,
    )
    print(candidates.to_string(index=False) if len(candidates) else "No matches.")
    for rel in candidates.get("REL", []):
        print(f"\n{rel}: {', '.join(list_columns(conn, rel))}")

    conn.close()
    print("\nDone. Paste this whole output back to Claude.")


if __name__ == "__main__":
    main()
