"""Build the standalone Credit Notes report.

No reference output exists for this one (HANDOFF: "not started") — it packages the
credit-notes analysis from the Revenue Dashboard's "MTD Credit Notes" tab as its own
workbook, following the same conventions (types Credit Note + Journal Credit only;
Subtotal excl VAT; reduces revenue).

Tabs: Overview (KPIs, FY27 monthly trend, MTD by reason) / By Customer (MTD) /
Detail (MTD, largest first).

Usage:
    python build_credit_notes.py --credits-file ".../Credits - March24 - Feb27.xls" \
        [--month YYYY-MM] --out-dir out
"""

import argparse
import calendar
from collections import defaultdict
from datetime import date

import xlsxwriter

from data import excel_serial_to_date  # noqa: F401  (used via Credits loader pattern)
from style import ALT, NAVY, NAVY2, ORANGE, YELLOW, NUM, NUM2, PCT1, Styles, title_block

CREDIT_TYPES = ("Credit Note", "Journal Credit")
FY_START = date(2026, 3, 1)  # FY27


def load_credits(path):
    import xlrd
    from datetime import datetime, timedelta
    book = xlrd.open_workbook(path)
    sh = book.sheet_by_index(0)
    hdr = [str(sh.cell_value(0, c)).strip() for c in range(sh.ncols)]
    ic = {n: hdr.index(n) for n in
          ["Receipt", "Account", "Customer Name", "Date", "Subtotal", "Reference",
           "Type", "Rep", "Reason", "Branch", "Credit Controller"]}
    out = []
    for i in range(1, sh.nrows):
        if str(sh.cell_value(i, ic["Type"])) not in CREDIT_TYPES:
            continue
        try:
            d = (datetime(1899, 12, 30) + timedelta(days=sh.cell_value(i, ic["Date"]))).date()
        except (TypeError, ValueError):
            continue
        out.append(dict(
            date=d, acct=str(sh.cell_value(i, ic["Account"])).strip(),
            customer=str(sh.cell_value(i, ic["Customer Name"])).strip(),
            value=sh.cell_value(i, ic["Subtotal"]) or 0,
            ref=str(sh.cell_value(i, ic["Reference"])).strip(),
            reason=str(sh.cell_value(i, ic["Reason"])).strip() or "(unspecified)",
            rep=str(sh.cell_value(i, ic["Rep"])).strip(),
            branch=str(sh.cell_value(i, ic["Branch"])).strip(),
            controller=str(sh.cell_value(i, ic["Credit Controller"])).strip(),
            type=str(sh.cell_value(i, ic["Type"])).strip(),
        ))
    return out


def build(credits_file: str, out_dir: str, month: date | None = None) -> str:
    notes = load_credits(credits_file)
    if month is None:
        month = max(n["date"] for n in notes if n["date"] >= FY_START).replace(day=1)
    m_end = date(month.year, month.month, calendar.monthrange(month.year, month.month)[1])
    mtd = [n for n in notes if month <= n["date"] <= m_end]
    mtd_total = sum(n["value"] for n in mtd)
    mon_lab = month.strftime("%B FY27") if month >= FY_START else month.strftime("%B %Y")
    mon_short = month.strftime("%b")

    out_path = f"{out_dir}/Credit Notes Report - {month.strftime('%b %Y')}.xlsx"
    wb = xlsxwriter.Workbook(out_path)
    st = Styles(wb)
    GREY = "#595959"

    def F(**kw):
        return st.get(**kw)

    kl_navy = F(bold=True, font_size=8, font_color="white", bg_color=NAVY)
    kl_or = F(bold=True, font_size=8, font_color=NAVY, bg_color=ORANGE)

    def kv(bg, fc, fmt):
        return F(bold=True, font_size=14, font_color=fc, bg_color=bg,
                 num_format=fmt, align="left", valign="vcenter")

    sect = F(bold=True, font_size=11, font_color="white", bg_color=NAVY)
    th = F(bold=True, font_size=9, font_color="white", bg_color=NAVY2)
    note8 = F(font_size=8, font_color=GREY)

    # ---------------- Overview ----------------
    ws = wb.add_worksheet("Overview")
    ws.hide_gridlines(2)
    for i, w in enumerate([2, 22, 13, 12, 13, 13, 12, 13, 12, 12]):
        ws.set_column(i, i, w)
    title_block(ws, st, "J", "SUNRISE LOGISTICS",
                f"Credit Notes Report — {mon_lab}",
                "Credit notes (types Credit Note + Journal Credit) · Subtotal excl VAT · "
                "ZAR · reduces revenue")

    reasons = defaultdict(lambda: [0.0, 0])
    for n in mtd:
        reasons[n["reason"]][0] += n["value"]
        reasons[n["reason"]][1] += 1
    top_reason = max(reasons.items(), key=lambda kv_: kv_[1][0]) if reasons else ("—", [0, 0])
    largest = max((n["value"] for n in mtd), default=0)

    ws.merge_range("B7:C7", "TOTAL CREDITS (MTD)", kl_navy)
    ws.merge_range("D7:E7", "# CREDIT NOTES", kl_navy)
    ws.merge_range("F7:G7", "LARGEST NOTE", kl_navy)
    ws.merge_range("H7:J7", f"TOP REASON: {top_reason[0]}", kl_or)
    ws.merge_range("B8:C8", mtd_total, kv(NAVY, "white", NUM))
    ws.merge_range("D8:E8", len(mtd), kv(NAVY, "white", NUM))
    ws.merge_range("F8:G8", largest, kv(NAVY, "white", NUM))
    ws.merge_range("H8:J8", top_reason[1][0], kv(ORANGE, NAVY, NUM))

    # FY27 monthly trend
    ws.merge_range("B11:J11", "FY27 CREDIT NOTES BY MONTH", sect)
    for i, h in enumerate(["Month", "Value (R)", "# Notes", "Avg / note", "Largest"]):
        ws.write(11, 1 + i, h, th)
    fy = defaultdict(list)
    for n in notes:
        if n["date"] >= FY_START:
            fy[(n["date"].year, n["date"].month)].append(n["value"])
    r = 13
    first_r = r
    for (y, m), vals in sorted(fy.items()):
        bg = ALT if r % 2 == 1 else "white"
        lab = date(y, m, 1).strftime("%b %Y")
        if (y, m) == (month.year, month.month):
            lab += " (MTD)"
        ws.write(r - 1, 1, lab, F(font_size=10, bg_color=bg))
        ws.write(r - 1, 2, round(sum(vals)), F(font_size=10, bg_color=bg, num_format=NUM))
        ws.write(r - 1, 3, len(vals), F(font_size=10, bg_color=bg, num_format=NUM))
        ws.write_formula(r - 1, 4, f'=IF(D{r}=0,"",C{r}/D{r})',
                         F(font_size=10, bg_color=bg, num_format=NUM))
        ws.write(r - 1, 5, round(max(vals)), F(font_size=10, bg_color=bg, num_format=NUM))
        r += 1
    ob = dict(bold=True, font_size=10, bg_color=ORANGE)
    ws.write(r - 1, 1, "FY27 to date", F(**ob))
    ws.write_formula(r - 1, 2, f"=SUM(C{first_r}:C{r - 1})", F(num_format=NUM, **ob))
    ws.write_formula(r - 1, 3, f"=SUM(D{first_r}:D{r - 1})", F(num_format=NUM, **ob))
    ws.write_formula(r - 1, 4, f'=IF(D{r}=0,"",C{r}/D{r})', F(num_format=NUM, **ob))
    total_trend_row = r

    # MTD by reason
    r += 2
    ws.merge_range(r - 1, 1, r - 1, 9, f"CREDIT NOTES BY REASON — {mon_short} MTD", sect)
    r += 1
    hdr_r = r
    ws.merge_range(r - 1, 1, r - 1, 4, "Reason", th)
    ws.write(r - 1, 5, "Value", th)
    ws.write(r - 1, 6, "# Notes", th)
    ws.write(r - 1, 7, "% of Total", th)
    r += 1
    first_r = r
    for reason, (val, cnt) in sorted(reasons.items(), key=lambda kv_: -kv_[1][0]):
        bg = ALT if r % 2 == 1 else "white"
        ws.merge_range(r - 1, 1, r - 1, 4, reason, F(font_size=9, bg_color=bg))
        ws.write(r - 1, 5, round(val), F(font_size=9, bg_color=bg, num_format=NUM))
        ws.write(r - 1, 6, cnt, F(font_size=9, bg_color=bg, num_format=NUM))
        ws.write_formula(r - 1, 7, f"=F{r}/$F${first_r + len(reasons)}",
                         F(font_size=9, bg_color=bg, num_format=PCT1))
        r += 1
    ws.merge_range(r - 1, 1, r - 1, 4, "Total", F(bold=True, font_size=9, bg_color=ORANGE))
    ws.write_formula(r - 1, 5, f"=SUM(F{first_r}:F{r - 1})",
                     F(bold=True, font_size=9, bg_color=ORANGE, num_format=NUM))
    ws.write_formula(r - 1, 6, f"=SUM(G{first_r}:G{r - 1})",
                     F(bold=True, font_size=9, bg_color=ORANGE, num_format=NUM))
    ws.write_formula(r - 1, 7, f"=F{r}/F{r}",
                     F(bold=True, font_size=9, bg_color=ORANGE, num_format=PCT1))
    r += 2
    ws.merge_range(r - 1, 1, r - 1, 9,
                   "Net revenue = gross invoiced (Subtotal, excl VAT) less these credit notes. "
                   "Bad-debt reasons appear here for visibility but are treated separately as a "
                   "cost in revenue reporting.", note8)
    ws.merge_range(r, 1, r, 9,
                   "Source: Credits export, Revenue Data folder. Blue = source values; "
                   "black = formulas.", note8)

    # ---------------- By Customer (MTD) ----------------
    ws2 = wb.add_worksheet(f"By Customer {mon_short}")
    ws2.hide_gridlines(2)
    for i, w in enumerate([2, 10, 40, 22, 12, 13, 22]):
        ws2.set_column(i, i, w)
    title_block(ws2, st, "G", "SUNRISE LOGISTICS",
                f"Credit Notes by Customer — {mon_lab} MTD",
                f"{len(mtd)} notes · total R{mtd_total:,.0f} · Subtotal excl VAT · ZAR")
    cust = defaultdict(lambda: [0.0, 0])
    cnames, ctop = {}, {}
    for n in mtd:
        cust[n["acct"]][0] += n["value"]
        cust[n["acct"]][1] += 1
        cnames.setdefault(n["acct"], n["customer"])
        if n["acct"] not in ctop or n["value"] > ctop[n["acct"]][1]:
            ctop[n["acct"]] = (n["reason"], n["value"])
    for i, h in enumerate(["Account", "Customer", "Rep", "# Notes", "Value (R)",
                           "Top reason (by value)"]):
        ws2.write(6, 1 + i, h, th)
    rep_of = {}
    for n in mtd:
        rep_of.setdefault(n["acct"], n["rep"])
    rr = 8
    for acct, (val, cnt) in sorted(cust.items(), key=lambda kv_: -kv_[1][0]):
        bg = ALT if rr % 2 == 0 else "white"
        ws2.write(rr - 1, 1, acct, F(font_size=9, bg_color=bg))
        ws2.write(rr - 1, 2, cnames[acct], F(font_size=9, bg_color=bg))
        ws2.write(rr - 1, 3, rep_of[acct], F(font_size=9, bg_color=bg))
        ws2.write(rr - 1, 4, cnt, F(font_size=9, bg_color=bg, num_format=NUM))
        ws2.write(rr - 1, 5, round(val, 2), F(font_size=9, bg_color=bg, num_format=NUM2))
        ws2.write(rr - 1, 6, ctop[acct][0], F(font_size=9, bg_color=bg))
        rr += 1
    ws2.write(rr - 1, 1, "TOTAL", F(bold=True, font_size=9, bg_color=ORANGE))
    ws2.write_formula(rr - 1, 4, f"=SUM(E8:E{rr - 1})",
                      F(bold=True, font_size=9, bg_color=ORANGE, num_format=NUM))
    ws2.write_formula(rr - 1, 5, f"=SUM(F8:F{rr - 1})",
                      F(bold=True, font_size=9, bg_color=ORANGE, num_format=NUM2))

    # ---------------- Detail (MTD) ----------------
    ws3 = wb.add_worksheet(f"Detail {mon_short}")
    ws3.hide_gridlines(2)
    for i, w in enumerate([2, 9, 13, 9, 32, 18, 14, 22, 13, 20]):
        ws3.set_column(i, i, w)
    title_block(ws3, st, "J", "SUNRISE LOGISTICS",
                f"Credit Note Detail — {mon_lab} MTD (largest first)",
                "As captured in the credits system · Subtotal excl VAT · ZAR")
    for i, h in enumerate(["Date", "CN Ref", "Account", "Customer", "Rep", "Branch",
                           "Reason", "Value", "Credit Controller"]):
        ws3.write(6, 1 + i, h, th)
    rr = 8
    for n in sorted(mtd, key=lambda n_: -n_["value"]):
        bg = ALT if rr % 2 == 0 else "white"
        vals = [n["date"].strftime("%d %b"), n["ref"], n["acct"], n["customer"],
                n["rep"], n["branch"], n["reason"], round(n["value"]), n["controller"]]
        for j, v in enumerate(vals):
            kw = dict(font_size=9, bg_color=bg)
            if j == 7:
                kw.update(num_format=NUM, font_color="#0000FF")
            ws3.write(rr - 1, 1 + j, v, F(**kw))
        rr += 1
    ws3.write(rr - 1, 1, "TOTAL", F(bold=True, font_size=9, bg_color=ORANGE))
    ws3.write_formula(rr - 1, 8, f"=SUM(I8:I{rr - 1})",
                      F(bold=True, font_size=9, bg_color=ORANGE, num_format=NUM))

    wb.close()
    return out_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--credits-file", required=True)
    ap.add_argument("--month", default=None, help="YYYY-MM (default: latest FY27 month in file)")
    ap.add_argument("--out-dir", default=".")
    a = ap.parse_args()
    m = date.fromisoformat(a.month + "-01") if a.month else None
    print(build(a.credits_file, a.out_dir, m))
