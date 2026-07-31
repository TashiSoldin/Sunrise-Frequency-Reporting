"""Daily revenue pipeline — Phase 4 orchestrator.

One command, no Claude in the loop: extract the three files from Parcel
Perfect, build the reports, email them to exco. Designed for Windows Task
Scheduler on the BI server (see run_revenue_flash.bat / run_revenue_pm.bat),
writing into the synced SharePoint folder so everything also lands in
"Claude General" automatically.

Two scheduled windows, per Larry (31 Jul 2026):

    07:00  --only flash   Flash Revenue for the previous trading day
    16:30  --only pm      Revenue Dashboard, Billing Detail, Unbilled,
                          Credit Notes — all one day in arrears

    uv run revenue_reports/run_daily.py --only flash \
        --data-dir  "<synced>/Dashboards and Data Analysis/2. Revenue Data" \
        --report-dir "<synced>/Dashboards and Data Analysis"

Other flags:
    --skip-extract   rebuild reports from the existing files only
    --no-email       build and save, but send nothing (safe test runs)
    --dry-run-email  print what would be sent, send nothing
    --to a@b.com     override recipients for a test send

Dates are auto-derived and never include today, because today's data is still
being captured while the reports run:
  - flash          -> latest waybill date strictly before today
  - billing detail -> last fully invoiced day (max invoice date before today)
  - dashboard      -> capped at those same two dates
  - unbilled       -> billing-frontier rule inside build_unbilled
  - credit notes   -> current FY month

The prior-FY INV file and the budget workbook are read from --data-dir using
their standard names. Report generation stays deterministic Python; Claude
remains the tool for changing formats, not producing dailies.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent

sys.path.insert(0, str(HERE))
from data import col, load_export  # noqa: E402
from mailer import flash_subject, pm_subject, send_reports  # noqa: E402

PY_INV_NAME = "INV Date - March25 - Feb26..xlsx"
BUDGET_NAME = "FY26-27_Budget_v30_Sunrise.xlsx"


def fy_start(today: date | None = None) -> date:
    """Most recent 1 March (duplicated from extract_revenue so that
    --skip-extract runs don't need the firebirdsql driver installed)."""
    today = today or date.today()
    return date(today.year if today.month >= 3 else today.year - 1, 3, 1)


def fy_label(start: date) -> str:
    return f"March{start.year % 100} - Feb{(start.year + 1) % 100}"


def run(step: str, args: list[str]) -> str:
    """Run a builder and return the workbook path it printed on its last line."""
    print(f"== {step} ==", flush=True)
    proc = subprocess.run([sys.executable, *args], check=True, cwd=HERE,
                          capture_output=True, text=True)
    if proc.stdout:
        print(proc.stdout, end="", flush=True)
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr, flush=True)
    lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    if not lines:
        raise SystemExit(f"{step}: builder printed no output path")
    return lines[-1]


def latest_dates(wb_file: Path, inv_file: Path) -> tuple[date, date]:
    """(latest waybill date before today, last fully invoiced day).

    Both exclude today. The 07:00 flash asked for "the day preceding" — taking
    the latest waybill date strictly before today gives yesterday on a normal
    weekday and rolls back to Friday on a Monday (or over a public holiday),
    so the report is never built for a day with no trading.
    """
    today = date.today()

    def norm(v):
        return v.date() if isinstance(v, datetime) else v

    h, rows = load_export(str(wb_file))
    iwd = col(h, "Waybill Date")
    wb_latest = max((norm(r[iwd]) for r in rows
                     if isinstance(norm(r[iwd]), date) and norm(r[iwd]) < today),
                    default=today)
    h, rows = load_export(str(inv_file))
    iid = col(h, "Invoice Date")
    # Guard: never build a billing detail for a day still being invoiced —
    # today's invoice runs land through the day, so a same-day billing detail
    # would be a partial. Use the newest fully-elapsed invoiced day.
    inv_latest = max((norm(r[iid]) for r in rows
                      if isinstance(norm(r[iid]), date) and norm(r[iid]) < today),
                     default=today)
    return wb_latest, inv_latest


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", required=True,
                    help='The "2. Revenue Data" folder (extracts land here)')
    ap.add_argument("--report-dir", required=True,
                    help="Where the report workbooks are written")
    ap.add_argument("--only", choices=["all", "flash", "pm"], default="all",
                    help="flash = 07:00 run; pm = 16:30 run; all = both")
    ap.add_argument("--skip-extract", action="store_true",
                    help="Rebuild reports from the existing files only")
    ap.add_argument("--no-email", action="store_true",
                    help="Build and save the reports but send no email")
    ap.add_argument("--dry-run-email", action="store_true",
                    help="Print what would be emailed without sending")
    ap.add_argument("--to", default=None,
                    help="Comma-separated recipient override (test sends)")
    args = ap.parse_args()

    data_dir, report_dir = Path(args.data_dir), Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    to = [a.strip() for a in args.to.split(",")] if args.to else None

    if not args.skip_extract:
        run("extract (WB / INV / credits)",
            ["extract_revenue.py", "--out-dir", str(data_dir)])

    label = fy_label(fy_start())
    wb_file = data_dir / f"WB Date - {label}..xlsx"
    inv_file = data_dir / f"INV Date - {label}..xlsx"
    cred_start = fy_start().year - 2
    credits_file = data_dir / f"Credits - March{cred_start % 100} - Feb{(fy_start().year + 1) % 100}.xlsx"
    py_inv = data_dir / PY_INV_NAME
    budget = data_dir / BUDGET_NAME
    for f in (wb_file, inv_file, credits_file, py_inv, budget):
        if not f.exists():
            raise SystemExit(f"Missing input: {f}")

    wb_day, inv_day = latest_dates(wb_file, inv_file)
    print(f"flash day (waybill basis): {wb_day} | billing day (invoice basis): {inv_day}")

    if args.only in ("all", "flash"):
        flash = run("flash", ["build_flash.py", "--date", wb_day.isoformat(),
                              "--wb-file", str(wb_file), "--out-dir", str(report_dir)])
        if not args.no_email:
            send_reports(
                subject=flash_subject(wb_day),
                intro=("Please find attached the Flash Revenue report for "
                       f"{wb_day.strftime('%A, %d %B %Y')}."),
                attachments=[flash], to=to, dry_run=args.dry_run_email)

    if args.only in ("all", "pm"):
        billing = run("billing detail",
                      ["build_billing_detail.py", "--date", inv_day.isoformat(),
                       "--inv-file", str(inv_file),
                       "--credits-file", str(credits_file),
                       "--out-dir", str(report_dir)])
        dashboard = run("dashboard",
                        ["build_dashboard.py", "--inv-file", str(inv_file),
                         "--py-inv-file", str(py_inv), "--wb-file", str(wb_file),
                         "--credits-file", str(credits_file),
                         "--budget-file", str(budget),
                         "--inv-asof", inv_day.isoformat(),
                         "--wb-asof", wb_day.isoformat(),
                         "--out-dir", str(report_dir)])
        unbilled = run("unbilled", ["build_unbilled.py", "--wb-file", str(wb_file),
                                    "--out-dir", str(report_dir)])
        credits = run("credit notes",
                      ["build_credit_notes.py", "--credits-file", str(credits_file),
                       "--out-dir", str(report_dir)])
        if not args.no_email:
            send_reports(
                subject=pm_subject(inv_day),
                intro=("Please find attached the daily revenue reports for "
                       f"{inv_day.strftime('%A, %d %B %Y')}."),
                attachments=[dashboard, billing, unbilled, credits],
                to=to, dry_run=args.dry_run_email)

    print("Daily pipeline complete.", flush=True)


if __name__ == "__main__":
    main()
