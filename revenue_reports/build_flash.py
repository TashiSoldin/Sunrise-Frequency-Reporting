"""Build the Flash Revenue report — same-day snapshot, waybill-date basis.

Page one replicates Larry's "Flash Revenue - DD Mon YYYY.xlsx" (see replication
guide) and must stay that shape: build_billing_detail._flash_comparison re-reads
the frozen workbook and finds its sections by scanning the first sheet for three
literal headers. A second "All Customers" tab lists every client that moved
freight that day — Larry's request of 4 Aug 2026, on its own tab so page one and
the archive of already-frozen flashes both keep parsing.

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
from style import (
    DEC2,
    H_BILLING,
    NUM,
    PCT1,
    TAB_BILLING,
    Styles,
    freeze_below,
    set_rows,
    title_block,
)

from data import col, load_export

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
ALL_TAB = "All Customers"


def build(
    day: date,
    wb_file: str | None,
    out_dir: str,
    data: tuple[list[str], list[list]] | None = None,
) -> str:
    """data, when given, is injected (headers, rows) in export shape — as
    load_export returns them, or extract_revenue.export_shaped builds them
    from a live query — and wb_file is not read (it may be None)."""
    headers, rows = data if data is not None else load_export(wb_file)
    iWD = col(headers, "Waybill Date")
    iWB = col(headers, "Waybill")
    iSUB = col(headers, "Subtotal")
    iKG = col(headers, "Chrg Mass")
    iHUB = col(headers, "Orig Hub")
    iREP = col(headers, "Salesrep")
    iREPN = col(headers, "Rep")
    iCUST = col(headers, "Customer")
    iACC = col(headers, "Account")

    day_rows = [r for r in rows if r[iWD] == day and "~" not in str(r[iWB])]
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

    # by rep (revenue > 0), display "CODE — Full Name".
    # Chargeable mass and R/kg added at Larry's request, 4 Aug 2026, matching
    # the columns the branch and customer blocks already carry.
    rep = defaultdict(lambda: [0.0, 0.0, 0])
    rep_names = {}
    for r in day_rows:
        c = str(r[iREP])
        rep[c][0] += r[iSUB] or 0
        rep[c][1] += r[iKG] or 0
        rep[c][2] += 1
        if r[iREPN]:
            rep_names[c] = str(r[iREPN])
    reps = sorted(
        ((f"{c} — {rep_names.get(c, c)}", *v) for c, v in rep.items() if v[0] > 0),
        key=lambda t: -t[1],
    )

    # Customers, keyed on Account rather than the name printed on the waybill:
    # a handful of accounts carry two spellings of the same customer (94 names
    # against 92 accounts on 3 Aug 2026), which would split those clients into
    # two rows on the all-customers tab. The display name is the first spelling
    # seen for the account.
    cust = defaultdict(lambda: [0.0, 0.0, 0])
    cust_names = {}
    for r in day_rows:
        a = str(r[iACC])
        cust_names.setdefault(a, str(r[iCUST]))
        cust[a][0] += r[iSUB] or 0
        cust[a][1] += r[iKG] or 0
        cust[a][2] += 1
    customers = sorted(
        ((a, cust_names[a], *v) for a, v in cust.items()), key=lambda t: -t[2]
    )
    top10 = [(name, *v) for _, name, *v in customers[:10]]

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

    # Alias over the shared cache, matching build_unbilled's F and
    # build_credit_notes' F. This used to hand-copy Styles' base dict — same
    # values, second copy — which is how a change to the house defaults would
    # have reached four builders and quietly skipped this one.
    st = Styles(wb)

    def fmt(**kw):
        return st.get(**kw)

    brand = fmt(border=0, bold=True, font_size=13, font_color=YELLOW, bg_color=NAVY)
    title = fmt(border=0, bold=True, font_size=16, font_color="white", bg_color=NAVY)
    subtitle = fmt(border=0, font_size=9, font_color="white", bg_color=NAVY2)
    accent = fmt(border=0, bg_color=ORANGE)
    kpi_l_navy = fmt(bold=True, font_size=8, font_color="white", bg_color=NAVY)
    kpi_v_navy = fmt(
        bold=True,
        font_size=16,
        font_color="white",
        bg_color=NAVY,
        num_format="#,##0",
        align="left",
        valign="vcenter",
    )
    kpi_l_or = fmt(bold=True, font_size=8, font_color=NAVY, bg_color=ORANGE)
    kpi_v_or = fmt(
        bold=True,
        font_size=16,
        font_color=NAVY,
        bg_color=ORANGE,
        num_format="0.00",
        align="left",
        valign="vcenter",
    )
    kpi_l_ye = fmt(bold=True, font_size=8, font_color=NAVY, bg_color=YELLOW)
    kpi_v_ye = fmt(
        bold=True,
        font_size=16,
        font_color=NAVY,
        bg_color=YELLOW,
        num_format="#,##0",
        align="left",
        valign="vcenter",
    )
    kpi_v_pct = fmt(
        bold=True,
        font_size=16,
        font_color=NAVY,
        bg_color=YELLOW,
        num_format="0.0%;(0.0%)",
        align="left",
        valign="vcenter",
    )
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
    ws.merge_range(
        "B4:G4", "Waybill-date basis · gross Subtotal (ex-VAT) · ZAR", subtitle
    )
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
    # Chg kg and R/kg go to the RIGHT of Revenue, so the block keeps its label
    # in column B and its revenue in column C. build_billing_detail's flash
    # comparison reads exactly those two columns out of the frozen workbook;
    # putting the new columns anywhere else would silently feed it mass as
    # revenue. Waybills moves from D to F, which nothing reads.
    for i, h in enumerate(["Rep", "Revenue", "Chg kg", "R/kg", "Waybills"]):
        ws.write(r + 1, 1 + i, h, th)
    for j, (name, rev, rkg, n) in enumerate(reps):
        t, num, dec = row_fmts(j % 2)
        ws.write(r + 2 + j, 1, name, t)
        ws.write(r + 2 + j, 2, rev, num)
        ws.write(r + 2 + j, 3, rkg, num)
        ws.write(r + 2 + j, 4, rev / rkg if rkg else 0, dec)
        ws.write(r + 2 + j, 5, n, num)

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
    ws.write(
        r + 2 + len(top10),
        1,
        f"Every client that moved freight on {title_date} is listed on the "
        f"'{ALL_TAB}' tab.",
        fmt(border=0, font_size=8, font_color="#595959"),
    )

    _all_customers(wb, fmt, customers, revenue, title_date, weekday)

    wb.close()
    return out_path


def _all_customers(wb, fmt, customers, revenue, title_date, weekday):
    """Second tab: every client that moved freight that day.

    Larry asked for all clients on 4 Aug 2026; the shape (full list on its own
    tab, top ten left on the front page) was agreed the same morning. Around a
    hundred rows on a typical day.

    Deliberately a separate worksheet rather than an expanded front-page block:
    build_billing_detail._flash_comparison re-reads the frozen flash and scans
    the first sheet for the section headers "BY BRANCH (origin)", "BY REP" and
    "TOP 10 CUSTOMERS". Renaming or lengthening that block in place would leave
    the rep section open and pull every customer into it — 100 "reps" instead of
    six, silently. Leaving page one untouched keeps that parser correct for both
    the archive of frozen flashes and every run from here.
    """
    ws = wb.add_worksheet(ALL_TAB)
    ws.set_tab_color(TAB_BILLING)
    ws.hide_gridlines(2)
    ws.set_column("A:A", 2)
    for c_, w in zip("BCDEFGHI", [10, 34, 14, 12, 9, 10, 9, 10]):
        ws.set_column(f"{c_}:{c_}", w)

    # Shared house helpers, not the hand-rolled equivalents the rest of this
    # module uses: the layout that matters here is the billing detail's "By
    # Customer" tab — the other long per-customer list in the suite — and the
    # point of style.py is that those two stay in step. Column headings stay
    # NAVY2 rather than the NAVY that tab uses, because this sheet lives in the
    # flash workbook and Larry's 27 Jul flash reference puts every heading band
    # at NAVY2. Checked, not assumed.
    class _Shim:
        get = staticmethod(fmt)

    title_block(
        ws,
        _Shim,
        "I",
        "SUNRISE LOGISTICS",
        f"All Customers — {title_date} ({weekday})",
        f"Every client that moved freight that day · {len(customers)} clients · "
        f"grouped by account · waybill-date basis · gross Subtotal (ex-VAT) · ZAR",
    )
    set_rows(ws, H_BILLING)  # heading row 21.9, or it renders tight

    th = fmt(bold=True, font_size=9, font_color="white", bg_color=NAVY2)
    hdr = [
        "Account",
        "Customer",
        "Revenue",
        "Chg kg",
        "R/kg",
        "Waybills",
        "% of day",
        "Cumulative",
    ]
    for i, h in enumerate(hdr):
        ws.write(6, 1 + i, h, th)
    freeze_below(ws, 7)  # B8 — headings held, detail scrolls

    running = 0.0
    rr = 7
    for j, (acc, name, rev, ckg, n) in enumerate(customers):
        running += rev
        bg = ALT if j % 2 else "white"
        # Size 9, matching the billing detail's per-customer list. The flash's
        # front page is 10, but that block is ten rows and this one is ~100.
        # Black is set explicitly, not left to default: commit a712fe3 found the
        # billing detail carrying no font colours at all, and "looks black" and
        # "is black" diff differently.
        txt = fmt(font_size=9, font_color="black", bg_color=bg)
        num = fmt(font_size=9, font_color=BLUE, bg_color=bg, num_format=NUM)
        dec = fmt(font_size=9, font_color=BLUE, bg_color=bg, num_format=DEC2)
        pct = fmt(font_size=9, font_color=BLUE, bg_color=bg, num_format=PCT1)
        ws.write(rr, 1, acc, txt)
        ws.write(rr, 2, name, txt)
        ws.write(rr, 3, rev, num)
        ws.write(rr, 4, ckg, num)
        ws.write(rr, 5, rev / ckg if ckg else 0, dec)
        ws.write(rr, 6, n, num)
        ws.write(rr, 7, rev / revenue if revenue else 0, pct)
        ws.write(rr, 8, running / revenue if revenue else 0, pct)
        rr += 1

    tot = {"bold": True, "font_size": 9, "bg_color": ORANGE, "font_color": NAVY}
    ws.write(rr, 1, "TOTAL", fmt(**tot))
    ws.write(rr, 2, f"{len(customers)} clients", fmt(**tot))
    ws.write(rr, 3, sum(c[2] for c in customers), fmt(num_format=NUM, **tot))
    kg_t = sum(c[3] for c in customers)
    ws.write(rr, 4, kg_t, fmt(num_format=NUM, **tot))
    ws.write(rr, 5, revenue / kg_t if kg_t else 0, fmt(num_format=DEC2, **tot))
    ws.write(rr, 6, sum(c[4] for c in customers), fmt(num_format=NUM, **tot))
    ws.write(rr, 7, 1 if revenue else 0, fmt(num_format=PCT1, **tot))
    ws.write(rr, 8, 1 if revenue else 0, fmt(num_format=PCT1, **tot))

    # ~100 rows a day, so this one is meant to be printed as well as scrolled.
    ws.set_landscape()
    ws.set_paper(9)  # A4
    ws.fit_to_pages(1, 0)  # one page wide, as many tall as needed
    ws.repeat_rows(6)  # headings on every printed page
    ws.print_area(1, 1, rr, 8)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--date", required=True, help="YYYY-MM-DD (waybill date)")
    p.add_argument("--wb-file", required=True, help="WB-date export .xlsx")
    p.add_argument("--out-dir", default=".")
    a = p.parse_args()
    print(build(date.fromisoformat(a.date), a.wb_file, a.out_dir))
