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
    --cc a@b.com     override the cc list

Logging follows the same pattern as report_generation.py: one rotating file
under logs/run_revenue/, rolled at midnight and kept for 30 days, plus the
console. The batch files therefore do no log management of their own.

Dates are auto-derived and never include today, because today's data is still
being captured while the reports run:
  - flash          -> last waybill day that actually traded (not merely the
                      latest date present: weekends and public holidays carry
                      a handful of waybills worth little or nothing)
  - billing detail -> last day whose invoice run has finished
  - dashboard      -> capped at those same two dates
  - unbilled       -> billing-frontier rule inside build_unbilled
  - credit notes   -> the month of the last invoiced day, so every PM report
                      keys off the same reporting date

The prior-FY INV file and the budget workbook are read from --data-dir using
their standard names. Report generation stays deterministic Python; Claude
remains the tool for changing formats, not producing dailies.
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import time
from datetime import date, datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent

sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO_ROOT / "report_generation"))

from day_guards import last_trading_day
from mailer import flash_subject, pm_subject, send_reports
from utils.log_execution_time_decorator import log_execution_time

from data import col, load_export

LOGS_DIR = REPO_ROOT / "logs" / "run_revenue"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        TimedRotatingFileHandler(
            LOGS_DIR / "run_revenue.log",
            when="midnight",
            interval=1,
            backupCount=30,  # Keep logs for 30 days
        ),
        # stdout, not StreamHandler's stderr default — the bats trap stderr in
        # bootstrap.log for failures that predate logging.
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

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
    logger.info(f"Running {step}")
    start_time = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, *args], cwd=HERE, capture_output=True, text=True
    )

    for line in proc.stdout.splitlines():
        if line.strip():
            logger.info(line.rstrip())

    if proc.returncode != 0:
        logger.error(f"{step} failed with exit code {proc.returncode}")
        if proc.stderr.strip():
            logger.error(proc.stderr.rstrip())
        raise SystemExit(proc.returncode)

    if proc.stderr.strip():
        logger.warning(proc.stderr.rstrip())

    lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    if not lines:
        logger.error(f"{step} printed no output path")
        raise SystemExit(1)

    logger.info(f"{step} took {time.perf_counter() - start_time:.6f} seconds")
    return lines[-1]


# last_trading_day and its guard constants moved to day_guards.py (Day 4 of
# the query interface — the fourth consumer of the "ignore what is too small
# to mean anything" rule; see the module docstring there).


def latest_dates(wb_file: Path, inv_file: Path) -> tuple[date, date]:
    """(last traded waybill day, last fully invoiced day). Both exclude today.

    The 07:00 flash asked for "the day preceding": on a normal weekday that is
    yesterday, and on a Monday it rolls back over the weekend to Friday. The
    billing detail needs the newest day whose invoice run has finished, because
    invoicing lands through the day and a same-day detail would be a partial.
    """
    today = date.today()

    def norm(v):
        return v.date() if isinstance(v, datetime) else v

    h, rows = load_export(str(wb_file))
    iwd, isub = col(h, "Waybill Date"), col(h, "Subtotal")
    wb_latest = last_trading_day(((norm(r[iwd]), r[isub]) for r in rows), today)

    h, rows = load_export(str(inv_file))
    iid, isub = col(h, "Invoice Date"), col(h, "Subtotal")
    inv_latest = last_trading_day(((norm(r[iid]), r[isub]) for r in rows), today)
    return wb_latest, inv_latest


@log_execution_time
def generate_reports(args: argparse.Namespace) -> None:
    data_dir, report_dir = Path(args.data_dir), Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    to = [a.strip() for a in args.to.split(",")] if args.to else None
    cc = [a.strip() for a in args.cc.split(",")] if args.cc else None

    if not args.skip_extract:
        logger.info("Extracting data from database")
        run(
            "extract (WB / INV / credits)",
            ["extract_revenue.py", "--out-dir", str(data_dir)],
        )

    label = fy_label(fy_start())
    wb_file = data_dir / f"WB Date - {label}..xlsx"
    inv_file = data_dir / f"INV Date - {label}..xlsx"
    cred_start = fy_start().year - 2
    credits_file = (
        data_dir / f"Credits - March{cred_start % 100} - "
        f"Feb{(fy_start().year + 1) % 100}.xlsx"
    )
    py_inv = data_dir / PY_INV_NAME
    budget = data_dir / BUDGET_NAME
    for f in (wb_file, inv_file, credits_file, py_inv, budget):
        if not f.exists():
            logger.error(f"Missing input: {f}")
            raise SystemExit(1)

    wb_day, inv_day = latest_dates(wb_file, inv_file)
    logger.info(
        f"Flash day (waybill basis): {wb_day}; billing day (invoice basis): {inv_day}"
    )

    if args.only in ("all", "flash"):
        flash = run(
            "flash",
            [
                "build_flash.py",
                "--date",
                wb_day.isoformat(),
                "--wb-file",
                str(wb_file),
                "--out-dir",
                str(report_dir),
            ],
        )
        if not args.no_email:
            logger.info("Sending flash revenue email")
            send_reports(
                subject=flash_subject(wb_day),
                intro=(
                    "Please find attached the Flash Revenue report for "
                    f"{wb_day.strftime('%A, %d %B %Y')}."
                ),
                attachments=[flash],
                to=to,
                cc=cc,
                dry_run=args.dry_run_email,
            )

    if args.only in ("all", "pm"):
        # The Flash Comparison tab reads that day's FROZEN flash workbook — the
        # one written by the 07:00 run the morning after the day it covers —
        # rather than recomputing from the live export, which keeps firming up
        # as waybills are captured. Skipped if that file isn't there, e.g. the
        # first run of a new deployment or a morning the flash didn't run.
        flash_name = (
            f"Flash Revenue - {inv_day.day:02d} {inv_day.strftime('%b %Y')}.xlsx"
        )
        flash_path = report_dir / flash_name
        billing_args = [
            "build_billing_detail.py",
            "--date",
            inv_day.isoformat(),
            "--inv-file",
            str(inv_file),
            "--credits-file",
            str(credits_file),
            "--out-dir",
            str(report_dir),
        ]
        if flash_path.exists():
            billing_args += ["--flash-file", str(flash_path)]
        else:
            logger.warning(
                f"No frozen flash at {flash_name} — billing detail "
                f"will build without the Flash Comparison tab"
            )
        billing = run("billing detail", billing_args)
        dashboard = run(
            "dashboard",
            [
                "build_dashboard.py",
                "--inv-file",
                str(inv_file),
                "--py-inv-file",
                str(py_inv),
                "--wb-file",
                str(wb_file),
                "--credits-file",
                str(credits_file),
                "--budget-file",
                str(budget),
                "--inv-asof",
                inv_day.isoformat(),
                "--wb-asof",
                wb_day.isoformat(),
                "--out-dir",
                str(report_dir),
            ],
        )
        unbilled = run(
            "unbilled",
            [
                "build_unbilled.py",
                "--wb-file",
                str(wb_file),
                "--out-dir",
                str(report_dir),
            ],
        )
        credits = run(
            "credit notes",
            [
                "build_credit_notes.py",
                "--credits-file",
                str(credits_file),
                "--month",
                inv_day.strftime("%Y-%m"),
                "--out-dir",
                str(report_dir),
            ],
        )
        if not args.no_email:
            logger.info("Sending daily revenue reports email")
            send_reports(
                subject=pm_subject(inv_day),
                intro=(
                    "Please find attached the daily revenue reports for "
                    f"{inv_day.strftime('%A, %d %B %Y')}."
                ),
                attachments=[dashboard, billing, unbilled, credits],
                to=to,
                cc=cc,
                dry_run=args.dry_run_email,
            )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--data-dir",
        required=True,
        help='The "2. Revenue Data" folder (extracts land here)',
    )
    ap.add_argument(
        "--report-dir", required=True, help="Where the report workbooks are written"
    )
    ap.add_argument(
        "--only",
        choices=["all", "flash", "pm"],
        default="all",
        help="flash = 07:00 run; pm = 16:30 run; all = both",
    )
    ap.add_argument(
        "--skip-extract",
        action="store_true",
        help="Rebuild reports from the existing files only",
    )
    ap.add_argument(
        "--no-email",
        action="store_true",
        help="Build and save the reports but send no email",
    )
    ap.add_argument(
        "--dry-run-email",
        action="store_true",
        help="Print what would be emailed without sending",
    )
    ap.add_argument(
        "--to", default=None, help="Comma-separated recipient override (test sends)"
    )
    ap.add_argument("--cc", default=None, help="Comma-separated cc override")
    args = ap.parse_args()

    logger.info(f"Starting revenue pipeline: {args.only}")
    try:
        generate_reports(args)
    except SystemExit:
        raise
    except Exception as e:
        logger.error(f"Revenue pipeline failed: {e!s}")
        raise SystemExit(1)
    logger.info("Revenue pipeline completed successfully")


if __name__ == "__main__":
    main()
