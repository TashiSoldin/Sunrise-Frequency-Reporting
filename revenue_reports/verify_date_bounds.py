"""Verify the FY ceiling added to extraction_sql (commit 21fef49).

Read-only. Runs SELECTs against Parcel Perfect, writes nothing, sends nothing,
and does not touch the production export files. Safe to run at any time,
including between the 07:00 and 16:30 jobs.

    uv run revenue_reports/verify_date_bounds.py

What it answers, in order:

  1. Does the ceiling drop what we think it drops?  Every row it removes is
     listed with its capture and invoice dates, so you can see for yourself
     that they are old mis-keyed records and not live freight. If anything in
     that list looks like real recent business, STOP — the ceiling is wrong.

  2. Does it drop anything it shouldn't?  A waybill whose true date is this FY
     but was keyed into a past year is excluded by the FLOOR, and neither the
     old query nor the new one would catch it. The check reports how many rows
     sit just below the floor with a recent capture date, which is what that
     mistake would look like.

  3. Is the invoice side genuinely unaffected?  It should be identical on both
     queries. The dashboard and billing detail are invoice-based, so a change
     here would mean the blast radius is wider than assessed.

  4. Where does the billing frontier land?  The unbilled report derives it from
     the newest Invoiced waybill date. Printed for both queries.

Expected on the 4 Aug 2026 data: ~340 WB rows dropped carrying ~R3.49m, zero
INV rows dropped, frontier moving from 9473-07-06 to the day after the last
genuinely invoiced waybill.

What the dropped rows turned out to be, so the list is not alarming on sight:
mis-keyed YEARS, not junk records — 2022 typed as 2522 accounts for 218 of
them and 2023 as 2523 for 33 more, and 134 of the 338 carry a waybill date
within three days of their capture date once the year is corrected. 299 of
them, R3.45m of the R3.49m, are cash-before-delivery accounts, which never
reach Invoiced status because the money is taken up front. Only R36,892 across
39 waybills sits on named accounts, and that is the only slice where "never
invoiced" might actually mean "never billed".
"""

from __future__ import annotations

import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from extract_revenue import connect, extraction_sql, fetch, fy_end, fy_start  # noqa: E402

FLOOR_ONLY = "floor only (before the fix)"
BOUNDED = "bounded (after the fix)"


def floor_only_sql(basis: str, start: date) -> str:
    """The previous query: the bounded one with its ceiling line removed."""
    sql = extraction_sql(basis, start)
    ceiling = f"          AND wba.{ {'wb': 'WAYDATE', 'inv': 'INVDATE'}[basis] } < DATE '{fy_end(start).isoformat()}'\n"
    if ceiling not in sql:
        raise SystemExit(
            "Could not find the ceiling clause to remove — extraction_sql has "
            "changed shape. Update this script before trusting its output."
        )
    return sql.replace(ceiling, "")


def counts(conn, sql: str, date_col: str):
    cols, rows = fetch(conn, sql)
    i_d, i_sub = cols.index(date_col), cols.index("SUBTOTAL")
    total = sum(float(r[i_sub] or 0) for r in rows)
    return cols, rows, total, i_d, i_sub


def main() -> None:
    start = fy_start()
    print(f"FY window: {start} to {fy_end(start)} (exclusive)\n")
    conn = connect()
    try:
        for basis, date_col, label in (("wb", "WAYDATE", "WAYBILL-DATE FILE"),
                                       ("inv", "INVDATE", "INVOICE-DATE FILE")):
            print("=" * 72)
            print(label)
            print("=" * 72)

            cols_a, rows_a, tot_a, i_d, i_sub = counts(conn, floor_only_sql(basis, start), date_col)
            cols_b, rows_b, tot_b, _, _ = counts(conn, extraction_sql(basis, start), date_col)

            print(f"  {FLOOR_ONLY:28} {len(rows_a):>8,} rows   R{tot_a:>16,.2f}")
            print(f"  {BOUNDED:28} {len(rows_b):>8,} rows   R{tot_b:>16,.2f}")
            print(f"  {'dropped by the ceiling':28} {len(rows_a) - len(rows_b):>8,} rows   "
                  f"R{tot_a - tot_b:>16,.2f}")

            keys_b = {(r[cols_b.index('WAYBILL')], r[i_d]) for r in rows_b}
            dropped = [r for r in rows_a if (r[cols_a.index('WAYBILL')], r[i_d]) not in keys_b]

            if not dropped:
                print("\n  Nothing dropped — as expected on the invoice side.\n")
                continue

            years = Counter(d.year for r in dropped if isinstance(d := r[i_d], date))
            print(f"\n  Dropped by year: {dict(sorted(years.items()))}")
            print(f"  Dropped by status: "
                  f"{dict(Counter(str(r[cols_a.index('STATUS')]) for r in dropped).most_common())}")

            print("\n  --- EVERY DROPPED ROW: check none of these is live freight ---")
            show = ["WAYBILL", "STATUS", "CUSTNAME", "SUBTOTAL"]
            idx = {c: cols_a.index(c) for c in show if c in cols_a}
            cap = cols_a.index("CAPTUREDATE") if "CAPTUREDATE" in cols_a else None
            inv = cols_a.index("INVDATE") if "INVDATE" in cols_a else None
            for r in sorted(dropped, key=lambda r: str(r[i_d]))[:400]:
                bits = [f"{str(r[i_d]):>12}"]
                bits += [f"{str(r[idx[c]])[:26]:<26}" if c == "CUSTNAME"
                         else f"{str(r[idx[c]])[:20]:<20}" for c in show if c in idx]
                if cap is not None:
                    bits.append(f"captured {str(r[cap])[:10]}")
                if inv is not None and basis == "wb":
                    bits.append(f"invoiced {str(r[inv])[:10]}")
                print("   ", " | ".join(bits))
            if len(dropped) > 400:
                print(f"    ... and {len(dropped) - 400} more")

            if basis == "wb":
                def frontier(cols, rows):
                    ds = [d for r in rows
                          if str(r[cols.index("STATUS")]) == "Invoiced"
                          and isinstance(d := r[cols.index("WAYDATE")], date)]
                    return max(ds) if ds else None

                print("\n  Billing frontier (newest Invoiced waybill date):")
                print(f"    {FLOOR_ONLY:28} {frontier(cols_a, rows_a)}")
                print(f"    {BOUNDED:28} {frontier(cols_b, rows_b)}")

                print("\n  --- INVERSE CHECK: rows the FLOOR may be wrongly excluding ---")
                print("  A waybill whose real date is this FY but was keyed into a past")
                print("  year is dropped by the floor, and neither query catches it.")
                _, res = fetch(conn, f"""
                    SELECT COUNT(*), COALESCE(SUM(wba.SUBTOTAL), 0)
                    FROM VIEW_WBANALYSE wba
                    WHERE wba.WAYDATE < DATE '{start.isoformat()}'
                      AND wba.CAPTUREDATE >= DATE '{start.isoformat()}'
                      AND wba.WAYBILL NOT LIKE '%~%'
                      AND wba.STATUS <> 'Cancelled'
                """)
                n, val = res[0][0], float(res[0][1] or 0)
                print(f"    dated before {start} but captured during this FY: "
                      f"{n:,} rows, R{val:,.2f}")
                print("    A handful is normal — genuine late capture of old freight.")
                print("    Hundreds would mean the floor is losing real business, and")
                print("    the same keying problem runs in both directions.")
            print()
    finally:
        conn.close()

    print("=" * 72)
    print("If the dropped rows are all clearly historic and the invoice side is")
    print("unchanged, the ceiling is doing what it should. Then run:")
    print()
    print("  uv run revenue_reports/run_daily.py --only pm --no-email \\")
    print('      --data-dir "<synced>\\Dashboards and Data Analysis\\2. Revenue Data" \\')
    print('      --report-dir "%TEMP%\\verify"')
    print()
    print("and check the unbilled headline reads tens of waybills and tens of")
    print("thousands of rand, not four figures and millions. --no-email means")
    print("nothing reaches exco.")


if __name__ == "__main__":
    main()
