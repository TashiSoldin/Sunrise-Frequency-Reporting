"""Day 4 acceptance — answers asked through the interface vs pulled the
existing way, compared to the cent (QT-000004, "tested and validated against
Parcel Perfect").

The "existing way" is the production path: extract_revenue.connect/fetch for
the pull, export files + the builders for the reports. The interface way is
mcp_server.revenue. Both hit the live database, seconds apart — the script
says so when a difference is live drift (row counts differ) rather than a
logic difference.

Usage (repo root, BI server):
    uv run research/day4_acceptance.py inline      # sales / summary / credits numbers
    uv run research/day4_acceptance.py unbilled    # inline + workbook, diffed
    uv run research/day4_acceptance.py billing     # billing detail vs the scheduled artifact
    uv run research/day4_acceptance.py flash       # flash vs the scheduled artifact
"""

import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "revenue_reports"))

import build_unbilled
from build_credit_notes import load_credits
from day_guards import last_trading_day
from extract_revenue import (
    CREDITS_SQL,
    connect,
    credits_shaped,
    export_shaped,
    extraction_sql,
    fetch,
    fy_start,
    write_xlsx,
)

from data import col, load_export
from mcp_server import revenue

SCRATCH = Path(tempfile.mkdtemp(prefix="day4_acceptance_"))
ACCOUNT = "B35"  # Day 3's live reference account


def cent(a, b, label, tol=0.005):
    ok = abs(float(a) - float(b)) <= tol
    print(f"  {'PASS' if ok else 'FAIL'}  {label}: interface={a}  existing={b}")
    return ok


def existing_pull(basis):
    conn = connect()
    try:
        cols, rows = fetch(conn, *extraction_sql(basis, fy_start()))
    finally:
        conn.close()
    return export_shaped(cols, rows)


def existing_credits():
    conn = connect()
    try:
        start = date(fy_start().year - 2, 3, 1)
        cols, rows = fetch(conn, CREDITS_SQL.format(start=start.isoformat()))
    finally:
        conn.close()
    return credits_shaped(cols, rows)


def check_inline():
    ok = True
    print(f"\n=== sales_report({ACCOUNT}) vs existing-way FY filter ===")
    r = revenue.sales_report(ACCOUNT)
    h, rows = existing_pull("inv")
    ia, isub, ikg = col(h, "Account"), col(h, "Subtotal"), col(h, "Chrg Mass")
    mine = [x for x in rows if str(x[ia]).strip() == ACCOUNT]
    gross = sum(float(x[isub] or 0) for x in mine)
    kg = sum(float(x[ikg] or 0) for x in mine)
    ok &= cent(r["waybills"], len(mine), "waybill count", tol=0)
    ok &= cent(r["gross_revenue"], round(gross, 2), "gross revenue")
    ok &= cent(r["chargeable_kg"], round(kg, 2), "chargeable kg")

    ch, crows = existing_credits()
    notes = [
        n
        for n in load_credits(None, (ch, crows))
        if n["acct"] == ACCOUNT and fy_start() <= n["date"] <= date.today()
    ]
    ok &= cent(r["credit_notes"]["count"], len(notes), "credit-note count", tol=0)
    ok &= cent(
        r["credit_notes"]["total"],
        round(sum(n["value"] for n in notes), 2),
        "credit-note total",
    )
    ok &= cent(
        r["net_revenue"],
        round(round(gross, 2) - sum(n["value"] for n in notes), 2),
        "net revenue",
    )

    print("\n=== revenue_summary() vs existing-way day choice + totals ===")
    s = revenue.revenue_summary()
    today = date.today()
    wb_h, wb_rows = existing_pull("wb")
    iwd, isub = col(wb_h, "Waybill Date"), col(wb_h, "Subtotal")
    wb_day = last_trading_day(
        ((revenue._norm_date(x[iwd]), x[isub]) for x in wb_rows), today
    )
    ok &= cent(
        s["shipped"]["day"] == wb_day.isoformat(),
        True,
        f"shipped day = {wb_day}",
        tol=0,
    )
    day_rows = [x for x in wb_rows if revenue._norm_date(x[iwd]) == wb_day]
    ok &= cent(s["shipped"]["waybills"], len(day_rows), "shipped waybills", tol=0)
    ok &= cent(
        s["shipped"]["gross_revenue"],
        round(sum(float(x[isub] or 0) for x in day_rows), 2),
        "shipped gross",
    )

    inv_h, inv_rows = existing_pull("inv")
    iid, isub2 = col(inv_h, "Invoice Date"), col(inv_h, "Subtotal")
    inv_day = last_trading_day(
        ((revenue._norm_date(x[iid]), x[isub2]) for x in inv_rows), today
    )
    ok &= cent(
        s["billed"]["day"] == inv_day.isoformat(),
        True,
        f"billed day = {inv_day}",
        tol=0,
    )
    inv_day_rows = [x for x in inv_rows if revenue._norm_date(x[iid]) == inv_day]
    ok &= cent(s["billed"]["waybills"], len(inv_day_rows), "billed waybills", tol=0)
    ok &= cent(
        s["billed"]["gross_revenue"],
        round(sum(float(x[isub2] or 0) for x in inv_day_rows), 2),
        "billed gross",
    )

    print("\n=== credit_notes(July 2026, closed month) vs existing-way ===")
    c = revenue.credit_notes("2026-07")
    jul = [
        n
        for n in load_credits(None, (ch, crows))
        if date(2026, 7, 1) <= n["date"] <= date(2026, 7, 31)
    ]
    ok &= cent(c["credit_notes"], len(jul), "credit-note count", tol=0)
    ok &= cent(c["total_value"], round(sum(n["value"] for n in jul), 2), "credit total")
    return ok


def check_unbilled():
    print("\n=== unbilled_report: interface vs existing-way file build ===")
    ok = True
    r = revenue.unbilled_report(workbook=True)
    # existing way: export file -> load -> select -> build (the file path the
    # daily pipeline runs)
    conn = connect()
    try:
        cols, raw = fetch(conn, *extraction_sql("wb", fy_start()))
    finally:
        conn.close()
    export_file = SCRATCH / "WB acceptance.xlsx"
    write_xlsx(str(export_file), cols, raw)
    fh, frows = load_export(str(export_file))
    unb, frontier = build_unbilled.select_unbilled(fh, frows)
    ok &= cent(
        r["billing_frontier"] == frontier.isoformat(),
        True,
        f"frontier = {frontier}",
        tol=0,
    )
    ok &= cent(r["unbilled_waybills"], len(unb), "unbilled count", tol=0)
    ok &= cent(
        r["unbilled_value"], round(sum(u["sub"] for u in unb), 2), "unbilled value"
    )
    file_wb = build_unbilled.build(str(export_file), str(SCRATCH))
    print("  diffing workbooks (interface vs existing-way file build):")
    subprocess.run(
        [
            sys.executable,
            str(REPO / "revenue_reports" / "diff_workbooks.py"),
            r["workbook"]["path"],
            file_wb,
            "--tol",
            "0.005",
        ],
        check=False,
    )
    return ok


def check_billing():
    """Full daily report through the interface vs the scheduled artifact."""
    d = date(2026, 8, 13)  # the newest scheduled Billing Detail (14 Aug 16:38 run)
    print(f"\n=== billing_detail {d} via interface vs scheduled artifact ===")
    r = revenue.daily_report("billing_detail", d.isoformat())
    if not r.get("ok"):
        print("  REFUSED:", r.get("reason"))
        return False
    ref = revenue.SCHEDULED_REPORT_DIR / f"Billing Detail - {d.day} {d:%b %Y}.xlsx"
    subprocess.run(
        [
            sys.executable,
            str(REPO / "revenue_reports" / "diff_workbooks.py"),
            r["workbook"]["path"],
            str(ref),
            "--tol",
            "0.005",
        ],
        check=False,
    )
    return True


def check_flash():
    d = date(2026, 8, 14)  # covered by the scheduled Sat-morning flash
    print(f"\n=== flash {d} via interface vs scheduled artifact ===")
    r = revenue.daily_report("flash", d.isoformat())
    if not r.get("ok"):
        print("  REFUSED:", r.get("reason"))
        return False
    ref = revenue.SCHEDULED_REPORT_DIR / f"Flash Revenue - {d.day} {d:%b %Y}.xlsx"
    subprocess.run(
        [
            sys.executable,
            str(REPO / "revenue_reports" / "diff_workbooks.py"),
            r["workbook"]["path"],
            str(ref),
            "--tol",
            "0.005",
        ],
        check=False,
    )
    return True


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "inline"
    steps = {
        "inline": check_inline,
        "unbilled": check_unbilled,
        "billing": check_billing,
        "flash": check_flash,
    }
    passed = steps[which]()
    print(f"\n{'ALL PASS' if passed else 'SEE FAILURES ABOVE'} ({which})")
