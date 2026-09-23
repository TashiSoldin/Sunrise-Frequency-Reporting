"""Credit note -> invoice / waybill link probe (Reuven's 15 Sep change request).

Run on the BI server from the repo root (same .env as the scheduled reports;
self-contained — imports only revenue_reports/extract_revenue.py):

    uv run research/revenue_reports/credit_note_links_probe.py

Read-only, small. Output tees to credit_note_links_probe_<date>.txt in the
current directory — paste it back / drop it in Claude General.

What it answers:
  1. Full column lists (name, type, length) for RECEIPT, RECALLOC, NOTETYPE,
     INVOICE and WAYBILL — Reuven's first question, straight from RDB$.
  2. Max declared and max USED length of RECEIPT.REFERENCE and RECEIPT.COMMENT
     on credit notes — Reuven's second question.
  3. Whether a stored credit-note -> invoice link exists:
       a. RECALLOC rows for negative receipts (allocations to invoices?)
       b. VIEW_WBANALYSE.RECEIPT pointing at negative receipts (waybill side)
     with coverage counts for FY27 credit notes, so the answer is a number
     ("N of M credit notes have a stored link"), not a guess.
  4. A 15-row sample joining all three, for eyeballing against Parcel Perfect.
     Every pass over VIEW_WBANALYSE is bounded by WAYDATE (the indexed path) —
     an unbounded correlated lookup on RECEIPT runs for a very long time.
     RECALLOC's column names are not in the 6 Aug survey (outside the MCP
     allowlist), so 3a/4 assume RECEIPT + INVOICE; if they fail, step 1's
     RECALLOC listing gives the real names and the failure is itself a finding.
"""

import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "revenue_reports"))
from extract_revenue import connect, fetch


class _Tee:
    """Print to the console and to a log file at the same time."""

    def __init__(self, path: str):
        self._file = open(path, "w", encoding="utf-8")
        self._stdout = sys.__stdout__

    def write(self, s: str) -> None:
        self._stdout.write(s)
        self._file.write(s)

    def flush(self) -> None:
        self._stdout.flush()
        self._file.flush()


def _table(cols: list[str], rows: list[tuple]) -> str:
    """Plain fixed-width rendering — no pandas dependency."""
    if not rows:
        return "(no rows)"
    cells = [[("" if v is None else str(v)) for v in r] for r in rows]
    widths = [max(len(c), *(len(r[i]) for r in cells)) for i, c in enumerate(cols)]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    return "\n".join([fmt.format(*cols)] + [fmt.format(*r) for r in cells])


FY_START = "2026-03-01"
WB_FROM = "2025-03-01"  # waybills a credit note might relate to: this FY and last

COLUMNS_SQL = """
SELECT TRIM(rf.RDB$FIELD_NAME) AS COLUMN_NAME,
       rf.RDB$FIELD_POSITION AS POS,
       CASE f.RDB$FIELD_TYPE
         WHEN 7 THEN 'SMALLINT' WHEN 8 THEN 'INTEGER' WHEN 10 THEN 'FLOAT'
         WHEN 12 THEN 'DATE' WHEN 13 THEN 'TIME' WHEN 14 THEN 'CHAR'
         WHEN 16 THEN 'BIGINT/NUMERIC' WHEN 27 THEN 'DOUBLE PRECISION'
         WHEN 35 THEN 'TIMESTAMP' WHEN 37 THEN 'VARCHAR' WHEN 261 THEN 'BLOB'
         ELSE CAST(f.RDB$FIELD_TYPE AS VARCHAR(10)) END AS DATA_TYPE,
       f.RDB$CHARACTER_LENGTH AS CHAR_LEN,
       f.RDB$FIELD_SCALE AS SCALE,
       CASE WHEN COALESCE(rf.RDB$NULL_FLAG, 0) = 1 THEN 'NOT NULL' ELSE '' END AS NULLS
FROM RDB$RELATION_FIELDS rf
JOIN RDB$FIELDS f ON f.RDB$FIELD_NAME = rf.RDB$FIELD_SOURCE
WHERE rf.RDB$RELATION_NAME = '{rel}'
ORDER BY rf.RDB$FIELD_POSITION;
"""


def show(conn, title: str, sql: str) -> None:
    print(f"== {title} ==")
    try:
        cols, rows = fetch(conn, sql)
        print(_table(cols, rows))
    except Exception as e:
        print(f"(failed: {e})")
    print()


def main() -> None:
    log = f"credit_note_links_probe_{date.today().isoformat()}.txt"
    sys.stdout = _Tee(log)
    print(f"(also writing this output to {log})\n")
    conn = connect()

    # 1. Column lists straight from the system tables.
    for rel in ("RECEIPT", "RECALLOC", "NOTETYPE", "INVOICE", "WAYBILL"):
        show(conn, f"1. Columns on {rel}", COLUMNS_SQL.format(rel=rel))

    # 2. Reason / Comment lengths — declared (above) and actually used.
    show(
        conn,
        "2. Max USED length of REFERENCE and COMMENT on credit notes",
        f"""
        SELECT MAX(CHAR_LENGTH(r.REFERENCE)) AS REFERENCE_MAX_USED,
               MAX(CHAR_LENGTH(r.COMMENT))   AS COMMENT_MAX_USED,
               COUNT(*) AS CREDIT_NOTES
        FROM RECEIPT r
        WHERE r.RECEIPT < 0 AND r.RECDATE >= DATE '{FY_START}';
    """,
    )
    show(conn, "2b. NOTETYPE (Reason code) lookup contents", "SELECT * FROM NOTETYPE;")

    # 3a. RECALLOC — does it link negative receipts to invoices?
    show(
        conn,
        "3a. RECALLOC sample for credit notes (negative receipts)",
        """
        SELECT FIRST 15 ra.*
        FROM RECALLOC ra
        WHERE ra.RECEIPT < 0
        ORDER BY ra.RECEIPT DESC;
    """,
    )
    show(
        conn,
        "3a-ii. Coverage: FY27 credit notes with >= 1 RECALLOC row",
        f"""
        SELECT COUNT(*) AS CREDIT_NOTES,
               SUM(CASE WHEN EXISTS (SELECT 1 FROM RECALLOC ra
                                     WHERE ra.RECEIPT = r.RECEIPT)
                        THEN 1 ELSE 0 END) AS WITH_ALLOCATION
        FROM RECEIPT r
        WHERE r.RECEIPT < 0 AND r.RECTYPE IN ('N', 'J')
          AND r.RECDATE >= DATE '{FY_START}';
    """,
    )

    # 3b. Waybill side — VIEW_WBANALYSE.RECEIPT pointing at a credit note.
    # ONE bounded pass over the view (WAYDATE is the indexed access path the
    # extraction uses; a correlated EXISTS per credit note over a 134-column
    # view with no index on RECEIPT is what makes this probe look "stuck").
    show(
        conn,
        "3b. Waybills whose RECEIPT points at a credit note "
        "(VIEW_WBANALYSE, WAYDATE >= 2025-03-01, one pass)",
        f"""
        SELECT COUNT(*) AS WAYBILLS,
               COUNT(DISTINCT w.RECEIPT) AS DISTINCT_CREDIT_NOTES
        FROM VIEW_WBANALYSE w
        WHERE w.WAYDATE >= DATE '{WB_FROM}' AND w.RECEIPT < 0;
    """,
    )
    show(
        conn,
        "3b-ii. Coverage: FY27 credit notes (N/J) with >= 1 such waybill",
        f"""
        SELECT COUNT(*) AS CREDIT_NOTES,
               SUM(CASE WHEN x.RECEIPT IS NULL THEN 0 ELSE 1 END) AS WITH_WAYBILL
        FROM RECEIPT r
        LEFT JOIN (SELECT DISTINCT w.RECEIPT FROM VIEW_WBANALYSE w
                   WHERE w.WAYDATE >= DATE '{WB_FROM}' AND w.RECEIPT < 0) x
               ON x.RECEIPT = r.RECEIPT
        WHERE r.RECEIPT < 0 AND r.RECTYPE IN ('N', 'J')
          AND r.RECDATE >= DATE '{FY_START}';
    """,
    )
    show(
        conn,
        "3b-iii. Waybills per credit note (distribution, same window)",
        f"""
        SELECT x.N_WB, COUNT(*) AS CREDIT_NOTES FROM (
          SELECT w.RECEIPT, COUNT(*) AS N_WB
          FROM VIEW_WBANALYSE w
          WHERE w.WAYDATE >= DATE '{WB_FROM}' AND w.RECEIPT < 0
          GROUP BY w.RECEIPT) x
        GROUP BY x.N_WB ORDER BY x.N_WB;
    """,
    )

    # 4. Eyeball sample: September credit notes + allocation + waybill(s).
    show(
        conn,
        "4. Sample: September credit notes with RECALLOC and waybill links",
        f"""
        SELECT FIRST 15 r.RECEIPT, r.RECDATE, r.ACCNUM, r.AMOUNT,
               r.REFERENCE, r.COMMENT, r.NOTETYPE,
               ra.INVOICE AS ALLOC_INVOICE,
               w.WAYBILL, w.INVOICE AS WB_INVOICE
        FROM RECEIPT r
        LEFT JOIN RECALLOC ra ON ra.RECEIPT = r.RECEIPT
        LEFT JOIN VIEW_WBANALYSE w
               ON w.RECEIPT = r.RECEIPT AND w.WAYDATE >= DATE '{WB_FROM}'
        WHERE r.RECEIPT < 0 AND r.RECTYPE IN ('N', 'J')
          AND r.RECDATE >= DATE '2026-09-01'
        ORDER BY r.RECDATE DESC, r.RECEIPT DESC;
    """,
    )

    conn.close()
    print("\nDone. Paste this output back or drop the .txt in Claude General.")


if __name__ == "__main__":
    main()
