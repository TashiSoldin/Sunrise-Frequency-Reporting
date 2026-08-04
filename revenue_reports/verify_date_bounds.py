r"""Verify the FY ceiling added to extraction_sql (commit 21fef49).

(Raw docstring — the Windows paths below are full of backslashes, and on the
BI server's Python 3.13 an ordinary string emits SyntaxWarning for every one
that is not a valid escape.)

Read-only against the database. Runs SELECTs only, sends nothing, and does not
touch the production export files. Safe to run at any time, including between
the 07:00 and 16:30 jobs.

    .\run_verify_bounds.bat        PowerShell
    run_verify_bounds.bat          cmd

which fills in the paths and copes with uv not being on PATH. By hand, note
that the line continuation differs between shells — backtick in PowerShell,
caret in cmd — so the single-line forms are safer:

    uv run revenue_reports/verify_date_bounds.py --out-dir "<diagnostics folder>"

If uv is not recognised — it is on PATH for the Task Scheduler user but often
not in an interactive shell — use the venv interpreter that "uv sync" built:

    .\.venv\Scripts\python.exe revenue_reports\verify_date_bounds.py --out-dir "..."

Plain "python" will not do: firebirdsql, python-calamine and python-dotenv are
installed in that venv, not system-wide.

Everything printed is also written to that folder, which is the synced working
folder rather than the reports folder — the output is a diagnostic, not
something Larry should find alongside his dailies. Two files, both dated:

    date-bounds check YYYY-MM-DD.txt   the full run, exactly as printed
    dropped rows YYYY-MM-DD.csv        every excluded row, for analysis

Because it syncs, the results can be read off the share afterwards without a
second RDP session. Omit --out-dir to print to the console only.

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

import argparse
import csv
import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from extract_revenue import connect, extraction_sql, fetch, fy_end, fy_start  # noqa: E402

FLOOR_ONLY = "floor only (before the fix)"
BOUNDED = "bounded (after the fix)"


class Tee:
    """Console and file at once, so the run can be read afterwards off the
    share instead of needing a second RDP session to reproduce it."""

    def __init__(self, path: Path | None):
        self.fh = path.open("w", encoding="utf-8") if path else None

    def __call__(self, line: str = "") -> None:
        print(line)
        if self.fh:
            self.fh.write(line + "\n")

    def close(self) -> None:
        if self.fh:
            self.fh.close()


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
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", default=None,
                    help="Folder for the .txt log and dropped-rows .csv. Use the "
                         "synced _diagnostics folder so the results can be read "
                         "off the share afterwards. Omit to print only.")
    args = ap.parse_args()

    out_dir = Path(args.out_dir) if args.out_dir else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
    stamp = date.today().isoformat()
    say = Tee(out_dir / f"date-bounds check {stamp}.txt" if out_dir else None)
    csv_rows: list[dict] = []

    start = fy_start()
    say(f"Date-bounds check — {stamp}")
    say(f"FY window: {start} to {fy_end(start)} (exclusive)")
    say("")
    conn = connect()
    try:
        for basis, date_col, label in (("wb", "WAYDATE", "WAYBILL-DATE FILE"),
                                       ("inv", "INVDATE", "INVOICE-DATE FILE")):
            say("=" * 72)
            say(label)
            say("=" * 72)

            cols_a, rows_a, tot_a, i_d, i_sub = counts(conn, floor_only_sql(basis, start), date_col)
            cols_b, rows_b, tot_b, _, _ = counts(conn, extraction_sql(basis, start), date_col)

            say(f"  {FLOOR_ONLY:28} {len(rows_a):>8,} rows   R{tot_a:>16,.2f}")
            say(f"  {BOUNDED:28} {len(rows_b):>8,} rows   R{tot_b:>16,.2f}")
            say(f"  {'dropped by the ceiling':28} {len(rows_a) - len(rows_b):>8,} rows   "
                f"R{tot_a - tot_b:>16,.2f}")

            i_wb = cols_a.index("WAYBILL")
            keys_b = {(r[cols_b.index("WAYBILL")], r[i_d]) for r in rows_b}
            dropped = [r for r in rows_a if (r[i_wb], r[i_d]) not in keys_b]

            if not dropped:
                say("")
                say("  Nothing dropped — which is what the invoice side should show.")
                say("")
                continue

            years = Counter(d.year for r in dropped if isinstance(d := r[i_d], date))
            statuses = Counter(str(r[cols_a.index("STATUS")]) for r in dropped)
            say("")
            say(f"  Dropped by year: {dict(sorted(years.items()))}")
            say(f"  Dropped by status: {dict(statuses.most_common())}")

            # Account split. On 4 Aug the R3.49m was 99% cash-before-delivery,
            # which never reaches Invoiced because the money is taken up front.
            # Only the named-account slice could mean genuinely unbilled work.
            i_acc, i_cust = cols_a.index("ACCNUM"), cols_a.index("CUSTNAME")
            cbd = [r for r in dropped if str(r[i_acc]).upper().startswith("CBD")]
            named = [r for r in dropped if not str(r[i_acc]).upper().startswith("CBD")]
            v = lambda g: sum(float(r[i_sub] or 0) for r in g)  # noqa: E731
            say("")
            say(f"  cash-before-delivery : {len(cbd):>5,} rows  R{v(cbd):>14,.2f}  (never invoiced by design)")
            say(f"  named accounts       : {len(named):>5,} rows  R{v(named):>14,.2f}  (the only slice worth chasing)")

            i_cap = cols_a.index("CAPTUREDATE")
            near = sum(1 for r in dropped
                       if isinstance(c := r[i_cap], date) and isinstance(d := r[i_d], date)
                       and abs((d.replace(year=c.year) - c).days) <= 3)
            say(f"  within 3 days of their capture date once the year is corrected: "
                f"{near}/{len(dropped)} — a mis-keyed year rather than random corruption")

            say("")
            say("  --- EVERY DROPPED ROW: check none of these is live freight ---")
            for r in sorted(dropped, key=lambda r: str(r[i_d])):
                say(f"    {str(r[i_d]):>12} | {str(r[i_wb])[:16]:<16} | "
                    f"{str(r[cols_a.index('STATUS')])[:22]:<22} | "
                    f"{str(r[i_acc])[:8]:<8} | {str(r[i_cust])[:30]:<30} | "
                    f"R{float(r[i_sub] or 0):>11,.2f} | captured {str(r[i_cap])[:10]}")
                csv_rows.append({
                    "basis": basis, "waybill": r[i_wb], "waybill_or_invoice_date": r[i_d],
                    "status": r[cols_a.index("STATUS")], "account": r[i_acc],
                    "customer": r[i_cust], "subtotal": float(r[i_sub] or 0),
                    "capture_date": r[i_cap], "invoice_date": r[cols_a.index("INVDATE")],
                })

            if basis == "wb":
                def frontier(cols, rows):
                    ds = [d for r in rows
                          if str(r[cols.index("STATUS")]) == "Invoiced"
                          and isinstance(d := r[cols.index("WAYDATE")], date)]
                    return max(ds) if ds else None

                say("")
                say("  Billing frontier (newest Invoiced waybill date):")
                say(f"    {FLOOR_ONLY:28} {frontier(cols_a, rows_a)}")
                say(f"    {BOUNDED:28} {frontier(cols_b, rows_b)}")

                say("")
                say("  --- INVERSE CHECK: rows the FLOOR may be wrongly excluding ---")
                say("  A waybill whose real date is this FY but was keyed into a past")
                say("  year is dropped by the floor, and neither query catches it.")
                _, res = fetch(conn, f"""
                    SELECT COUNT(*), COALESCE(SUM(wba.SUBTOTAL), 0)
                    FROM VIEW_WBANALYSE wba
                    WHERE wba.WAYDATE < DATE '{start.isoformat()}'
                      AND wba.CAPTUREDATE >= DATE '{start.isoformat()}'
                      AND wba.WAYBILL NOT LIKE '%~%'
                      AND wba.STATUS <> 'Cancelled'
                """)
                n, val = res[0][0], float(res[0][1] or 0)
                say(f"    dated before {start} but captured during this FY: "
                    f"{n:,} rows, R{val:,.2f}")
                say("    A handful is normal — genuine late capture of old freight.")
                say("    Hundreds would mean the floor is losing real business, and")
                say("    the same keying problem runs in both directions.")
            say("")
    finally:
        conn.close()

    say("=" * 72)
    say("If the dropped rows are all clearly historic and the invoice side is")
    say("unchanged, the ceiling is doing what it should. Then run:")
    say("")
    say("  uv run revenue_reports/run_daily.py --only pm --no-email \\")
    say('      --data-dir  "<synced>\\Dashboards and Data Analysis\\2. Revenue Data" \\')
    say('      --report-dir "<synced>\\Dashboards and Data Analysis\\2. Revenue Data\\_diagnostics"')
    say("")
    say("and check the unbilled headline reads tens of waybills and tens of")
    say("thousands of rand, not four figures and millions. --no-email means")
    say("nothing reaches exco, and _diagnostics keeps it out of the reports folder.")

    if out_dir:
        csv_path = out_dir / f"dropped rows {stamp}.csv"
        if csv_rows:
            with csv_path.open("w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=list(csv_rows[0]))
                w.writeheader()
                w.writerows(csv_rows)
        say("")
        say(f"Written to {out_dir}")
    say.close()


if __name__ == "__main__":
    main()
