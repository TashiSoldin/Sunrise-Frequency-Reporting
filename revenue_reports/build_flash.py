"""Build the Flash Revenue report — one-page same-day snapshot, waybill-date basis.

Replicates Larry's "Flash Revenue - DD Mon YYYY.xlsx" (see replication guide).

Usage:
    python build_flash.py --date 2026-07-27 \
        --wb-file "…/2. Revenue Data/WB Date - March26 - Feb27..xlsx" \
        --out-dir "…/output"

Notes / assumptions (flagged in PLAN.md Phase 0):
  * "Typical <weekday>" = mean of same-weekday daily totals this FY prior to the
    report date, excluding days below 50% of the median (public-holiday guard).
    Reverse-engineered to within 0.05% of the reference output; exact original
    definition unconfirmed.
  * Branch grouping maps Orig Hub codes: JHB={JNB,PRY}, Cape Town={CPT},
    Durban={DUR,KZ1,KZ3,PMB}, everything else = Other. Reconciled to the rand
    against the 27 Jul 2026 reference.
"""

import argparse
import statistics
from collections import defaultdict
from datetime import date

import xlsxwriter

from data import col, load_export
from style import TAB_BILLING

NAVY = "#05003C"
NAVY2 = "#0A0050"
ORANGE = "#FF6900"
YELLOW = "#FAB414"
ALT = "#F0F0F8"
BLUE = "#0000FF"

BRANCH_MAP = {
    "JNB": "JHB",
    "PRY": "JHB",
    "CPT": "Cape Town",
    "DUR": "Durban",
    "KZ1": "Durban",
    "KZ3": "Durban",
    "PMB": "Durban",
}
BRANCH_ORDER = ["JHB", "Cape Town", "Durban", "Other"]
HOLIDAY_GUARD = 0.5  # exclude same-weekday days below this fraction of median


def build(day: date, wb_file: str, out_dir: str) -> str:
    headers, rows = load_export(wb_file)
    iWD = col(headers, "Waybill Date")
    iWB = col(headers, "Waybill")
    iSUB = col(headers, "Subtotal")
    iKG = col(headers, "Chrg Mass")
    iHUB = col(headers, "Orig Hub")
    iREP = col(headers, "Salesrep")
    iREPN = col(headers, "Rep")
    iCUST = col(headers, "Customer")

    day_rows = [
        r for r in rows if r[iWD] == day and "~" not in str(r[iWB])
    ]
    if not day_rows:
        raise SystemExit(f"No waybills found for {day} — wrong file or date?")

    revenue = sum(r[iSUB] or 0 for r in day_rows)
    kg = sum(r[iKG] or 0 for r in day_rows)
    waybills = len(day_rows)
    rpkg = revenue / kg if kg else 0

    # typical same-weekday
    daily = defaultdict(float)
    for r in rows:
        d = r[iWD]
        if isinstance(d, date) and d < day and d.weekday() == day.weekday():
            daily[d] += r[iSUB] or 0
    vals = list(daily.values())
    med = statistics.median(vals) if vals else 0
    typical_vals = [v for v in vals if v >= HOLIDAY_GUARD * med]
    typical = statistics.mean(typical_vals) if typical_vals else 0
    vs_typical = revenue / typical - 1 if typical else 0

    # by branch
    br = defaultdict(lambda: [0.0, 0.0, 0])
    for r in day_rows:
        b = BRANCH_MAP.get(str(r[iHUB]), "Other")
        br[b][0] += r[iSUB] or 0
        br[b][1] += r[iKG] or 0
        br[b][2] += 1
    branches = [(b, *br[b]) for b in BRANCH_ORDER if b in br]

    # by rep (revenue > 0), display "CODE — Full Name"
    rep = defaultdict(lambda: [0.0, 0])
    rep_names = {}
    for r in day_rows:
        c = str(r[iREP])
        rep[c][0] += r[iSUB] or 0
        rep[c][1] += 1
        if r[iREPN]:
            rep_names[c] = str(r[iREPN])
    reps = sorted(
        ((f"{c} — {rep_names.get(c, c)}", v[0], v[1]) for c, v in rep.items() if v[0] > 0),
        key=lambda t: -t[1],
    )

    # top 10 customers
    cust = defaultdict(lambda: [0.0, 0.0, 0])
    for r in day_rows:
        c = str(r[iCUST])
        cust[c][0] += r[iSUB] or 0
        cust[c][1] += r[iKG] or 0
        cust[c][2] += 1
    top10 = sorted(((c, *v) for c, v in cust.items()), key=lambda t: -t[1])[:10]

    # ---- write workbook ----
    weekday = day.strftime("%A")
    title_date = f"{day.day} {day.strftime('%B %Y')}"
    short_date = f"{day.day:02d} {day.strftime('%b %Y')}"
    out_path = f"{out_dir}/Flash Revenue - {short_date}.xlsx"
    wb = xlsxwriter.Workbook(out_path)
    ws = wb.add_worksheet(f"Flash {day.day:02d} {day.strftime('%b')}")
    ws.set_tab_color(TAB_BILLING)
    ws.hide_gridlines(2)
    ws.set_column("A:A", 2)
    for c_, w in zip("BCDEFG", [22, 15, 13, 11, 13, 11]):
        ws.set_column(f"{c_}:{c_}", w)
    for r_, h in {2: 24, 3: 30, 4: 16, 5: 4}.items():
        ws.set_row(r_ - 1, h)

    def fmt(**kw):
        base = {"font_name": "Calibri"}
        base.update(kw)
        return wb.add_format(base)

    brand = fmt(bold=True, font_size=13, font_color=YELLOW, bg_color=NAVY)
    title = fmt(bold=True, font_size=16, font_color="white", bg_color=NAVY)
    subtitle = fmt(font_size=9, font_color="white", bg_color=NAVY2)
    accent = fmt(bg_color=ORANGE)
    kpi_l_navy = fmt(bold=True, font_size=8, font_color="white", bg_color=NAVY)
    kpi_v_navy = fmt(bold=True, font_size=16, font_color="white", bg_color=NAVY, num_format="#,##0", align="left", valign="vcenter")
    kpi_l_or = fmt(bold=True, font_size=8, font_color=NAVY, bg_color=ORANGE)
    kpi_v_or = fmt(bold=True, font_size=16, font_color=NAVY, bg_color=ORANGE, num_format="0.00", align="left", valign="vcenter")
    kpi_l_ye = fmt(bold=True, font_size=8, font_color=NAVY, bg_color=YELLOW)
    kpi_v_ye = fmt(bold=True, font_size=16, font_color=NAVY, bg_color=YELLOW, num_format="#,##0", align="left", valign="vcenter")
    kpi_v_pct = fmt(bold=True, font_size=16, font_color=NAVY, bg_color=YELLOW, num_format="0.0%;(0.0%)", align="left", valign="vcenter")
    section = fmt(bold=True, font_size=11, font_color="white", bg_color=NAVY)
    th = fmt(bold=True, font_size=9, font_color="white", bg_color=NAVY2)

    def row_fmts(alt):
        bg = ALT if alt else "white"
        return (
            fmt(font_size=10, bg_color=bg),
            fmt(font_size=10, font_color=BLUE, bg_color=bg, num_format="#,##0"),
            fmt(font_size=10, font_color=BLUE, bg_color=bg, num_format="0.00"),
        )

    ws.merge_range("B2:G2", "SUNRISE LOGISTICS", brand)
    ws.merge_range("B3:G3", f"Flash Revenue Report — {title_date} ({weekday})", title)
    ws.merge_range("B4:G4", "Waybill-date basis · gross Subtotal (ex-VAT) · ZAR", subtitle)
    ws.merge_range("B5:G5", "", accent)

    ws.merge_range("B7:C7", "REVENUE", kpi_l_navy)
    ws.merge_range("D7:E7", "WAYBILLS", kpi_l_navy)
    ws.merge_range("F7:G7", "CHARGEABLE KG", kpi_l_navy)
    ws.merge_range("B8:C9", revenue, kpi_v_navy)
    ws.merge_range("D8:E9", waybills, kpi_v_navy)
    ws.merge_range("F8:G9", kg, kpi_v_navy)
    ws.merge_range("B10:C10", "R / KG", kpi_l_or)
    ws.merge_range("D10:E10", f"TYPICAL {weekday[:3].upper()}", kpi_l_ye)
    ws.merge_range("F10:G10", f"vs TYPICAL {weekday[:3].upper()}", kpi_l_ye)
    ws.merge_range("B11:C12", rpkg, kpi_v_or)
    ws.merge_range("D11:E12", typical, kpi_v_ye)
    ws.merge_range("F11:G12", vs_typical, kpi_v_pct)

    r = 13  # 0-indexed row of "BY BRANCH" (xlsx row 14)
    ws.merge_range(r, 1, r, 6, "BY BRANCH (origin)", section)
    for i, h in enumerate(["Branch", "Revenue", "Chg kg", "R/kg", "Waybills"]):
        ws.write(r + 1, 1 + i, h, th)
    for j, (b, rev, bkg, n) in enumerate(branches):
        t, num, dec = row_fmts(j % 2)
        ws.write(r + 2 + j, 1, b, t)
        ws.write(r + 2 + j, 2, rev, num)
        ws.write(r + 2 + j, 3, bkg, num)
        ws.write(r + 2 + j, 4, rev / bkg if bkg else 0, dec)
        ws.write(r + 2 + j, 5, n, num)

    r = r + 2 + len(branches) + 1  # gap row then BY REP
    ws.merge_range(r, 1, r, 6, "BY REP", section)
    for i, h in enumerate(["Rep", "Revenue", "Waybills"]):
        ws.write(r + 1, 1 + i, h, th)
    for j, (name, rev, n) in enumerate(reps):
        t, num, _ = row_fmts(j % 2)
        ws.write(r + 2 + j, 1, name, t)
        ws.write(r + 2 + j, 2, rev, num)
        ws.write(r + 2 + j, 3, n, num)

    r = r + 2 + len(reps) + 1
    ws.merge_range(r, 1, r, 6, "TOP 10 CUSTOMERS", section)
    for i, h in enumerate(["Customer", "Revenue", "Chg kg", "R/kg", "Waybills"]):
        ws.write(r + 1, 1 + i, h, th)
    for j, (c, rev, ckg, n) in enumerate(top10):
        t, num, dec = row_fmts(j % 2)
        ws.write(r + 2 + j, 1, c, t)
        ws.write(r + 2 + j, 2, rev, num)
        ws.write(r + 2 + j, 3, ckg, num)
        ws.write(r + 2 + j, 4, rev / ckg if ckg else 0, dec)
        ws.write(r + 2 + j, 5, n, num)

    wb.close()
    return out_path


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--date", required=True, help="YYYY-MM-DD (waybill date)")
    p.add_argument("--wb-file", required=True, help="WB-date export .xlsx")
    p.add_argument("--out-dir", default=".")
    a = p.parse_args()
    print(build(date.fromisoformat(a.date), a.wb_file, a.out_dir))
