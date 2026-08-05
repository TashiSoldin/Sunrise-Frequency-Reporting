"""Consolidated flag — iteration 6: merge-list tables.

WAYBILL.* showed no structural discriminator across 8 diverse Yes/No pairs,
so the flag isn't stored on the waybill row. Best remaining candidates are
the merge/consolidation tables: WBMRGLST, CUMRGLST, AGCUSTCONSOL.

Run on the BI server from the repo root:

    uv run research/wbmrglst_probe.py
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from research.consolidated_probe import CONSOL_NO, CONSOL_YES
from research.revenue_extract_verify import _Tee
from research.revenue_extraction_test import (
    connect,
    list_columns,
    query_df,
)


def main() -> None:
    log = f"wbmrglst_probe_{date.today().isoformat()}.txt"
    sys.stdout = _Tee(log)
    print(f"(also writing this output to {log})\n")
    conn = connect()
    wbs = "', '".join(CONSOL_YES + CONSOL_NO)
    print(f"Yes: {CONSOL_YES}\nNo:  {CONSOL_NO}\n")

    for rel in ("WBMRGLST", "CUMRGLST", "AGCUSTCONSOL", "CUACTLST"):
        cols = list_columns(conn, rel)
        print(f"== {rel} ==\ncolumns: {', '.join(cols) or '(none)'}")
        if not cols:
            continue
        try:
            n = query_df(conn, f"SELECT COUNT(*) AS N FROM {rel}")["N"].iloc[0]
            print(f"row count: {n}")
            print(query_df(conn, f"SELECT FIRST 10 * FROM {rel}").to_string(index=False))
            if "WAYBILL" in cols:
                hits = query_df(conn, f"SELECT * FROM {rel} WHERE WAYBILL IN ('{wbs}')")
                print(f"rows for probe waybills: {len(hits)}")
                if len(hits):
                    print(hits.to_string(index=False))
        except Exception as e:  # noqa: BLE001
            print(f"(failed: {e})")
        print()

    conn.close()
    print("Done. Paste this output back (or drop the txt in Claude General).")


if __name__ == "__main__":
    main()
