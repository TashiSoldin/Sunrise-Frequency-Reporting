"""Daily revenue pipeline — Phase 4 orchestrator.

One command, no Claude in the loop: extract the three files from Parcel
Perfect, then build the five reports. Designed for Windows Task Scheduler on
the BI server (see run_revenue.bat), writing into the synced SharePoint
folder so everything lands in "Claude General" automatically.

    uv run revenue_reports/run_daily.py \
        --data-dir  "<synced>/Dashboards and Data Analysis/2. Revenue Data" \
        --report-dir "<synced>/Dashboards and Data Analysis" \
        [--skip-extract]   # rebuild reports from existing files only

Dates are auto-derived, mirroring Larry's daily rhythm:
  - flash          -> latest waybill date in the WB file (today's early read)
  - billing detail -> last fully invoiced day (max invoice date in INV file)
  - dashboard      -> builders' own defaults (latest data in the files)
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

PY_INV_NAME = "INV Date - March25 - Feb26..xlsx"
BUDGET_NAME = "FY26-27_Budget_v30_Sunrise.xlsx"


def fy_start(today: date | None = None) -> date:
    """Most recent 1 March (duplicated from extract_revenue so that
    --skip-extract runs don't need the firebirdsql driver installed)."""
    today = today or date.today()
    return date(today.year if today.month >= 3 else today.year - 1, 3, 1)


def fy_label(start: date) -> str:
    return f"March{start.year % 100} - Feb{(start.year + 1) % 100}"


def run(step: str, args: list[str]) -> None:
    print(f"== {step} ==", flush=True)
    subprocess.run([sys.executable, *args], check=True, cwd=HERE)


def latest_dates(wb_file: Path, inv_file: Path) -> tuple[date, date]:
    """(latest waybill date not in the future, last invoiced day)."""
    today = date.today()

    def norm(v):
        return v.date() if isinstance(v, datetime) else v

    h, rows = load_export(str(wb_file))
    iwd = col(h, "Waybill Date")
    wb_latest = max((norm(r[iwd]) for r in rows
                     if isinstance(norm(r[iwd]), date) and norm(r[iwd]) <= today),
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
                    help="Where the five report workbooks are written")
    ap.add_argument("--skip-extract", action="store_true",
                    help="Rebuild reports from the existing files only")
    args = ap.parse_args()

    data_dir, report_dir = Path(args.data_dir), Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)

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

    run("flash", ["build_flash.py", "--date", wb_day.isoformat(),
                  "--wb-file", str(wb_file), "--out-dir", str(report_dir)])
    run("billing detail", ["build_billing_detail.py", "--date", inv_day.isoformat(),
                           "--inv-file", str(inv_file),
                           "--credits-file", str(credits_file),
                           "--out-dir", str(report_dir)])
    run("dashboard", ["build_dashboard.py", "--inv-file", str(inv_file),
                      "--py-inv-file", str(py_inv), "--wb-file", str(wb_file),
                      "--credits-file", str(credits_file),
                      "--budget-file", str(budget), "--out-dir", str(report_dir)])
    run("unbilled", ["build_unbilled.py", "--wb-file", str(wb_file),
                     "--out-dir", str(report_dir)])
    run("credit notes", ["build_credit_notes.py", "--credits-file", str(credits_file),
                         "--out-dir", str(report_dir)])
    print("Daily pipeline complete.", flush=True)


if __name__ == "__main__":
    main()
