"""Build the mis-keyed waybill-date listing Larry asked for on 4 Aug 2026.

Source is the dropped-rows CSV written by revenue_reports/verify_date_bounds.py
on the BI server, which is now the ONLY record of these rows: the bounded
extract (commit 21fef49) correctly excludes them, so they are no longer in the
FY27 export. Do not delete that CSV without archiving it.

340 rows, not the 336 printed in that run's log — the log subtracted the counts
of two SELECTs run seconds apart against a live database, and four waybills
were captured in the gap. The key-based list is the accurate one.

FRAMING — read this before changing the layout.

A first version of this workbook was organised around cash-before-delivery
versus named accounts, and asserted that the CBD rows were "settled at the
counter, never invoiced by design, not money owed". That was invented. It was
inferred from the account prefix and never checked, and it is false: in the
FY27 export CBD accounts are invoiced 99.7% of the time (600 of 602), a higher
rate than every other account at 98.5%, and all 602 carry an invoice number.

What the data actually supports is the opposite organising principle. Being
uninvoiced tracks the broken date almost perfectly:

    normal-dated waybills, FY27      1.5% uninvoiced
    normal-dated waybills, FY25/26   0.0% uninvoiced (all carry invoice numbers)
    mis-keyed waybills              99.4% uninvoiced (338 of 340)

The likeliest explanation is that the mis-keyed year kept them out of every
invoicing run — a waybill dated 2522 falls outside any date range the billing
process uses — which applies to CBD and named accounts alike. So the workbook
is organised by invoiced status and by age, and states the open question rather
than answering it. Whether four-year-old freight is still billable is Larry's
call, not something to assert in a spreadsheet.

    python research/build_miskeyed_waybills.py --csv "<...>/dropped rows 2026-08-04.csv" \
        --out-dir "<...>/Dashboards and Data Analysis/Data Quality"
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

NAVY, NAVY2, ORANGE = "FF05003C", "FF0A0050", "FFFF6900"
YELLOW, ALT, BLUE, GREY, RED = "FFFAB414", "FFF0F0F8", "FF0000FF", "FF595959", "FFC00000"
GRID = Side(style="thin", color="FFD9D9D9")
BOX = Border(left=GRID, right=GRID, top=GRID, bottom=GRID)
MONEY, NUM, NUM1, PCT = "#,##0.00", "#,##0", "#,##0.0", "0.0%"
FONT = "Calibri"          # the house font on every report Larry receives


def d(s):
    return datetime.strptime(s, "%Y-%m-%d").date() if s else None


def likely_date(wb_date, cap_date):
    """Put the right year back, taking it from the capture date.

    Grounded rather than assumed: across the 88,585 normally-dated FY27
    waybills the capture date falls on the waybill date itself 91.2% of the
    time, within a day 96.2% and within a week 99.3%, median gap zero. So the
    two normally agree, and on these 340 they do not.

    Substituting a nearby year then lands every one of the 340 within twelve
    months of its capture date, and 168 within a week — which is what makes
    "the year was mistyped" a finding rather than a guess.
    """
    if not wb_date or not cap_date:
        return None, "no capture date"
    best = None
    for yr in (cap_date.year - 1, cap_date.year, cap_date.year + 1):
        try:
            guess = wb_date.replace(year=yr)
        except ValueError:                  # 29 Feb into a non-leap year
            continue
        diff = abs((guess - cap_date).days)
        if best is None or diff < best[0]:
            best = (diff, guess)
    if best is None:
        return None, "check manually"
    diff, guess = best
    return guess, "high" if diff <= 7 else ("likely" if diff <= 90 else "year only")


def style(c, *, bold=False, size=10, colour="FF000000", fill=None, fmt=None,
          align=None, wrap=False, box=True):
    c.font = Font(name=FONT, bold=bold, size=size, color=colour)
    if fill:
        c.fill = PatternFill("solid", fgColor=fill)
    if fmt:
        c.number_format = fmt
    c.alignment = Alignment(horizontal=align, vertical="center", wrap_text=wrap)
    if box:
        c.border = BOX
    return c


def banner(ws, last_col, title, subtitle):
    for row, text, kw in (
        (2, "SUNRISE LOGISTICS", dict(bold=True, size=13, colour=YELLOW, fill=NAVY)),
        (3, title, dict(bold=True, size=16, colour="FFFFFFFF", fill=NAVY)),
        (4, subtitle, dict(size=9, colour="FFFFFFFF", fill=NAVY2)),
        (5, "", dict(fill=ORANGE)),
    ):
        ws.merge_cells(f"B{row}:{last_col}{row}")
        style(ws[f"B{row}"], box=False, **kw)
        ws[f"B{row}"] = text
    for r, h in ((2, 24), (3, 30), (4, 16), (5, 4)):
        ws.row_dimensions[r].height = h


def headers(ws, row, names, widths):
    for i, (n, w) in enumerate(zip(names, widths)):
        style(ws.cell(row, 2 + i, n), bold=True, size=9, colour="FFFFFFFF",
              fill=NAVY2, wrap=True, align="center")
        ws.column_dimensions[get_column_letter(2 + i)].width = w
    ws.row_dimensions[row].height = 21.9


def prose(ws, r, lines, last_col="F"):
    for line in lines:
        if line == "":
            r += 1
            continue
        heading = len(line) < 46 and not line.endswith(".")
        ws.merge_cells(start_row=r, start_column=2, end_row=r,
                       end_column=ws[last_col + "1"].column)
        if heading:
            style(ws.cell(r, 2, line), bold=True, size=11, colour="FFFFFFFF",
                  fill=NAVY, box=False)
        else:
            style(ws.cell(r, 2, line), size=9, box=False, wrap=True)
            ws.row_dimensions[r].height = 26
        r += 1
    return r


def build(csv_path: str, out_dir: str, detail_csv: str | None = None) -> str:
    rows = list(csv.DictReader(open(csv_path, encoding="utf-8")))
    for r in rows:
        r["_wb"] = d(r["waybill_or_invoice_date"])
        r["_cap"] = d(r["capture_date"])
        r["_sub"] = float(r["subtotal"] or 0)
        r["_invoiced"] = r["status"] == "Invoiced"
        r["_likely"], r["_conf"] = likely_date(r["_wb"], r["_cap"])
        r["_year"] = r["_likely"].year if r["_likely"] else None
    rows.sort(key=lambda r: -r["_sub"])
    open_rows = [r for r in rows if not r["_invoiced"]]
    total = sum(r["_sub"] for r in rows)

    wb = Workbook()

    # ---------------- Overview ----------------
    ws = wb.active
    ws.title = "Overview"
    ws.sheet_view.showGridLines = False
    ws.sheet_properties.tabColor = ORANGE[2:]
    ws.column_dimensions["A"].width = 2
    for c, w in zip("BCDEF", (34, 14, 16, 13, 40)):
        ws.column_dimensions[c].width = w
    banner(ws, "F", "Waybills with mis-keyed dates",
           f"{len(rows)} waybills · R{total:,.2f} · identified 4 August 2026 · "
           "Sub-Total excl VAT · ZAR")

    r = prose(ws, 7, [
        "What these are",
        "A number of waybills in Parcel Perfect carry a year that was keyed incorrectly. "
        "2022 entered as 2522 accounts for most of them, 2023 as 2523 for the next largest "
        "group, and a handful sit in years as far out as 9473.",
        "Because the year reads as a future date, they were being counted as current-year "
        "freight by the automated extract, which had no upper date limit. They are excluded "
        "from 4 August 2026 onward. Your own manual export never showed them, because it "
        "always specified a date range.",
        "",
        "Almost none of them were ever invoiced",
        "338 of the 340 have no invoice against them. For normally-dated waybills that "
        "figure runs the other way, as below.",
    ])

    r += 1
    headers(ws, r, ["Waybills", "Group", "Uninvoiced", "", ""], [34, 14, 16, 13, 40])
    ws.cell(r, 2, "Comparison")
    for lab, txt, val, note in (
        ("Mis-keyed dates (these waybills)", f"{len(rows)}", 338 / 340,
         "Effectively all of them."),
        ("Normal dates, FY27 export", "88,586", 0.015,
         "Every account type, including cash-before-delivery at 0.3%."),
        ("Normal dates, FY25 and FY26", "388,819", 0.0,
         "Every waybill carries an invoice number."),
    ):
        r += 1
        style(ws.cell(r, 2, lab), size=10, fill=ALT)
        style(ws.cell(r, 3, txt), size=10, colour=BLUE, fill=ALT, align="right")
        style(ws.cell(r, 4, val), size=10, colour=(RED if val > 0.5 else BLUE),
              bold=val > 0.5, fill=ALT, fmt=PCT, align="right")
        style(ws.cell(r, 5, ""), fill=ALT)
        style(ws.cell(r, 6, note), size=9, fill=ALT, wrap=True)

    r = prose(ws, r + 2, [
        "",
        "Where to look",
        "'Never invoiced' lists all 338 by value. 'By likely year' shows how old they are. "
        "'By account' groups them by customer. 'All waybills' is the full listing including "
        "the two that were invoiced. 'Line detail' is the same waybills with shipper, "
        "consignee, pieces, masses and the charge breakdown, in the layout of the daily "
        "billing detail.",
        "On the line detail, Invoice # is empty except on the two that were invoiced, and "
        "the date appears twice \u2014 the value stored in Parcel Perfect, and the likely actual "
        "date beside it.",
        "",
        "How to read the dates",
        "'Waybill date (as captured)' is the value stored in Parcel Perfect. 'Capture "
        "date' is when the record was created. 'Likely actual date' puts the year back.",
        "On normally-dated waybills in this financial year the capture date falls on the "
        "waybill date itself 91.2% of the time, within a day 96.2% and within a week 99.3% "
        "— median gap zero days, across 88,585 waybills. On these 340 they do not match, "
        "so the year has been taken from the capture date.",
        "Every one of the 340 lands within twelve months of its capture date once corrected, "
        "and about half within a week — so the year is the only part that was mistyped. "
        "Confidence reads 'high' where the day and month also line up with capture, 'likely' "
        "within three months, and 'year only' where the year is certain but the day and "
        "month are worth checking against the physical waybill.",
    ])
    style(ws.cell(r + 1, 2, "Source: Parcel Perfect FY27 waybill export, 4 August 2026. "
          "Comparison figures from the FY25, FY26 and FY27 exports. Produced by sam et al."),
          size=8, colour=GREY, box=False)

    # ---------------- detail tabs ----------------
    cols = ["Waybill", "Account", "Customer", "Status", "Waybill date\n(as captured)",
            "Capture date", "Likely actual\ndate", "Confidence", "Sub-Total (R)"]
    widths = [16, 10, 40, 22, 14, 13, 14, 14, 14]

    def detail(title, data, tab_colour, subtitle):
        s = wb.create_sheet(title)
        s.sheet_view.showGridLines = False
        s.sheet_properties.tabColor = tab_colour[2:]
        s.column_dimensions["A"].width = 2
        banner(s, "J", title, subtitle)
        headers(s, 7, cols, widths)
        s.freeze_panes = "B8"
        rr = 8
        for i, x in enumerate(data):
            bg = ALT if i % 2 else "FFFFFFFF"
            for j, v in enumerate([x["waybill"], x["account"], x["customer"], x["status"],
                                   x["_wb"], x["_cap"], x["_likely"], x["_conf"], x["_sub"]]):
                c = s.cell(rr, 2 + j, v)
                if j == 8:
                    style(c, size=9, colour=BLUE, fill=bg, fmt=MONEY, align="right")
                elif isinstance(v, date):
                    style(c, size=9, colour=BLUE, fill=bg, fmt="yyyy-mm-dd", align="center")
                elif j == 7:
                    style(c, size=9, colour=(RED if v == "year only" else GREY),
                          fill=bg, align="center")
                else:
                    style(c, size=9, fill=bg)
            rr += 1
        style(s.cell(rr, 2, "TOTAL"), bold=True, size=9, colour=NAVY, fill=ORANGE)
        for j in range(1, 8):
            style(s.cell(rr, 2 + j, ""), fill=ORANGE)
        style(s.cell(rr, 3, f"{len(data)} waybills"), bold=True, size=9, colour=NAVY,
              fill=ORANGE)
        style(s.cell(rr, 10, f"=SUM(J8:J{rr-1})"), bold=True, size=9, colour=NAVY,
              fill=ORANGE, fmt=MONEY, align="right")
        s.print_area = f"B2:J{rr}"
        s.page_setup.orientation = "landscape"
        s.page_setup.paperSize = 9
        s.print_title_rows = "7:7"
        s.sheet_properties.pageSetUpPr.fitToPage = True
        s.page_setup.fitToWidth, s.page_setup.fitToHeight = 1, 0

    detail("Never invoiced", open_rows, RED,
           f"{len(open_rows)} waybills with no invoice against them · sorted by value")

    # ---------------- by likely year ----------------
    s = wb.create_sheet("By likely year")
    s.sheet_view.showGridLines = False
    s.sheet_properties.tabColor = YELLOW[2:]
    s.column_dimensions["A"].width = 2
    banner(s, "F", "By likely year",
           "How old this freight actually is, once the year is corrected · "
           "uninvoiced waybills only")
    headers(s, 7, ["Likely year", "Waybills", "Value (R)", "% of value", "Age at Aug 2026"],
            [14, 12, 16, 12, 22])
    per = defaultdict(lambda: [0, 0.0])
    for x in open_rows:
        p = per[x["_year"]]
        p[0] += 1
        p[1] += x["_sub"]
    open_total = sum(v[1] for v in per.values())
    rr = 8
    for y in sorted(per):
        n_, v = per[y]
        bg = ALT if rr % 2 == 0 else "FFFFFFFF"
        style(s.cell(rr, 2, y), size=9, fill=bg, align="center", fmt="0")
        style(s.cell(rr, 3, n_), size=9, colour=BLUE, fill=bg, fmt=NUM, align="right")
        style(s.cell(rr, 4, v), size=9, colour=BLUE, fill=bg, fmt=MONEY, align="right")
        style(s.cell(rr, 5, f"=D{rr}/{open_total}"), size=9, colour=BLUE, fill=bg,
              fmt=PCT, align="right")
        style(s.cell(rr, 6, f"{2026 - y} year{'s' if 2026 - y != 1 else ''} old"),
              size=9, fill=bg)
        rr += 1
    style(s.cell(rr, 2, "TOTAL"), bold=True, size=9, colour=NAVY, fill=ORANGE)
    style(s.cell(rr, 3, f"=SUM(C8:C{rr-1})"), bold=True, size=9, colour=NAVY, fill=ORANGE,
          fmt=NUM, align="right")
    style(s.cell(rr, 4, f"=SUM(D8:D{rr-1})"), bold=True, size=9, colour=NAVY, fill=ORANGE,
          fmt=MONEY, align="right")
    for c in (5, 6):
        style(s.cell(rr, c, ""), fill=ORANGE)

    # ---------------- by account ----------------
    s = wb.create_sheet("By account")
    s.sheet_view.showGridLines = False
    s.sheet_properties.tabColor = NAVY[2:]
    s.column_dimensions["A"].width = 2
    banner(s, "F", "By account",
           "Uninvoiced waybills grouped by customer · sorted by value")
    headers(s, 7, ["Account", "Customer", "Waybills", "Value (R)", "Oldest"],
            [12, 46, 12, 16, 14])
    s.freeze_panes = "B8"
    agg = defaultdict(lambda: [0, 0.0, "", None])
    for x in open_rows:
        a = agg[x["account"]]
        a[0] += 1
        a[1] += x["_sub"]
        a[2] = a[2] or x["customer"]
        a[3] = x["_likely"] if a[3] is None else min(a[3], x["_likely"])
    rr = 8
    for i, (acct, (n_, v, name, oldest)) in enumerate(
            sorted(agg.items(), key=lambda kv: -kv[1][1])):
        bg = ALT if i % 2 else "FFFFFFFF"
        style(s.cell(rr, 2, acct), size=9, fill=bg)
        style(s.cell(rr, 3, name), size=9, fill=bg)
        style(s.cell(rr, 4, n_), size=9, colour=BLUE, fill=bg, fmt=NUM, align="right")
        style(s.cell(rr, 5, v), size=9, colour=BLUE, fill=bg, fmt=MONEY, align="right")
        style(s.cell(rr, 6, oldest), size=9, colour=BLUE, fill=bg, fmt="yyyy-mm-dd",
              align="center")
        rr += 1
    style(s.cell(rr, 2, "TOTAL"), bold=True, size=9, colour=NAVY, fill=ORANGE)
    style(s.cell(rr, 3, f"{len(agg)} accounts"), bold=True, size=9, colour=NAVY, fill=ORANGE)
    style(s.cell(rr, 4, f"=SUM(D8:D{rr-1})"), bold=True, size=9, colour=NAVY, fill=ORANGE,
          fmt=NUM, align="right")
    style(s.cell(rr, 5, f"=SUM(E8:E{rr-1})"), bold=True, size=9, colour=NAVY, fill=ORANGE,
          fmt=MONEY, align="right")
    style(s.cell(rr, 6, ""), fill=ORANGE)

    detail("All waybills", rows, NAVY2,
           f"All {len(rows)}, including the two that were invoiced · sorted by value")

    if detail_csv:
        _line_detail(wb, detail_csv)

    out = f"{out_dir}/Mis-keyed Waybill Dates - 04 Aug 2026.xlsx"
    wb.save(out)
    return out


def _line_detail(wb, detail_csv: str) -> None:
    """Sixth tab: the same waybills at line level, from the saved database pull.

    One workbook rather than two files. The first cut shipped this as a
    separate "Mis-keyed Waybills - line detail" beside "Mis-keyed Waybill
    Dates", which put two near-identically-named files in the folder Larry had
    been pointed at — the same ambiguity that already cost this project a
    reference workbook. The summary carries the age profile and the detail
    carries shipper and consignee; he needs both, so they belong together.

    Written with openpyxl like the rest of this workbook. The standalone
    version used xlsxwriter, which is why it could never simply be bolted on.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import build_miskeyed_detail as D

    rows = D.rows_from_export(detail_csv)
    for r in rows:
        r["_wb"] = D.norm(r["Waybill Date"])
        r["_cap"] = D.norm(r["Capture Date"])
        r["_likely"] = D.likely_date(r["_wb"], r["_cap"])
        r["_sub"] = float(r["Subtotal"] or 0)
        r["_invoiced"] = str(r["Status"]) == "Invoiced"
        # INVOICE holds the Parcel Perfect status code until a waybill is
        # invoiced — 0, -99, -7, -6, -1 — so it is only an invoice number once
        # Status says so. The daily Billing Detail never meets these because it
        # only lists invoiced lines.
        r["_invno"] = int(r["Invoice"]) if r["_invoiced"] and r["Invoice"] else ""
        b, o, sf, f = (float(r[k] or 0) for k in
                       ("Basic Charge", "Outlying Charge", "Doc Charge", "Fuel"))
        r["_parts"] = (b, o, sf, f, r["_sub"] - b - o - sf - f)

    by_acct = defaultdict(list)
    for r in rows:
        by_acct[str(r["Account"])].append(r)
    for g in by_acct.values():
        g.sort(key=lambda r: -r["_sub"])
    ordered = sorted(by_acct.items(), key=lambda kv: -sum(r["_sub"] for r in kv[1]))
    n_inv = sum(1 for r in rows if r["_invoiced"])

    hdr = ["Waybill", "Date in PP", "Likely date", "Invoice #", "Account", "Customer",
           "Shipper", "Consignee", "Orig", "Dest", "Destination", "Cust Ref", "Service",
           "Pcs", "Actual Mass", "Chrge Mass", "Basic", "Outly", "Service Fee", "Fuel",
           "Surcharge", "Sub-Total", "R/kg"]
    widths = [11, 11, 11, 9, 8, 26, 22, 22, 6, 6, 18, 12, 8, 7, 10, 10, 10, 9, 9, 10, 10, 11, 8]
    fmts = [None] * 13 + [NUM, NUM1, NUM1, MONEY, MONEY, MONEY, MONEY, MONEY, MONEY, "0.00"]

    s = wb.create_sheet("Line detail")
    s.sheet_view.showGridLines = False
    s.sheet_properties.tabColor = NAVY2[2:]
    s.column_dimensions["A"].width = 2
    banner(s, "X", "Line detail",
           f"The same waybills in the layout of the daily billing detail · grouped by "
           f"account, largest first · {len(rows)} waybills, {len(rows) - n_inv} with no "
           f"invoice · ex-VAT · ZAR")
    headers(s, 7, hdr, widths)
    s.freeze_panes = "B8"

    rr, grand = 8, [0.0] * 8
    for acct, lines in ordered:
        sub = [0.0] * 8
        for ln in lines:
            bg = ALT if rr % 2 == 0 else "FFFFFFFF"
            b, o, sf, f, surch = ln["_parts"]
            pcs, akg, ckg = (float(ln[k] or 0) for k in
                             ("Pieces", "Actual Mass", "Chrg Mass"))
            vals = [str(ln["Waybill"]), ln["_wb"], ln["_likely"], ln["_invno"], acct,
                    str(ln["Customer"]), str(ln["Shipper"] or ""),
                    str(ln["Consignee"] or ""), str(ln["Orig Hub"] or ""),
                    str(ln["Dest Hub"] or ""), str(ln["Dest Place"] or ""),
                    str(ln["Reference"] or ""), str(ln["Service"] or ""),
                    pcs, round(akg, 1), round(ckg, 1), b, o, sf, f, surch, ln["_sub"],
                    (ln["_sub"] / ckg) if ckg else 0]
            for j, v in enumerate(vals):
                c = s.cell(rr, 2 + j, v)
                if j in (1, 2):
                    style(c, size=9, fill=bg, fmt="yyyy-mm-dd", align="center",
                          colour=(RED if j == 1 else BLUE))
                elif j >= 13:
                    style(c, size=9, fill=bg, fmt=fmts[j], colour=BLUE, align="right")
                else:
                    style(c, size=9, fill=bg)
            sub = [a + b_ for a, b_ in
                   zip(sub, [pcs, akg, ckg, b, o, sf, f, ln["_sub"]])]
            rr += 1
        for c in range(2, 25):
            style(s.cell(rr, c, ""), size=9, bold=True, fill=ALT, colour=NAVY)
        style(s.cell(rr, 7, f"{lines[0]['Customer']}  —  {len(lines)} waybills"),
              size=9, bold=True, fill=ALT, colour=NAVY)
        for j, v in zip((13, 14, 15, 16, 17, 18, 19, 21), sub):
            style(s.cell(rr, 2 + j, v), size=9, bold=True, fill=ALT, colour=NAVY,
                  fmt=fmts[j], align="right")
        style(s.cell(rr, 24, (sub[7] / sub[2]) if sub[2] else 0), size=9, bold=True,
              fill=ALT, colour=NAVY, fmt="0.00", align="right")
        grand = [a + b_ for a, b_ in zip(grand, sub)]
        rr += 1

    for c in range(2, 25):
        style(s.cell(rr, c, ""), size=9, bold=True, fill=ORANGE, colour=NAVY)
    style(s.cell(rr, 7, f"GRAND TOTAL — {len(rows)} waybills, {len(ordered)} accounts"),
          size=9, bold=True, fill=ORANGE, colour=NAVY)
    for j, v in zip((13, 14, 15, 16, 17, 18, 19, 21), grand):
        style(s.cell(rr, 2 + j, v), size=9, bold=True, fill=ORANGE, colour=NAVY,
              fmt=fmts[j], align="right")
    style(s.cell(rr, 24, (grand[7] / grand[2]) if grand[2] else 0), size=9, bold=True,
          fill=ORANGE, colour=NAVY, fmt="0.00", align="right")

    s.print_area = f"B2:X{rr}"
    s.page_setup.orientation = "landscape"
    s.page_setup.paperSize = 8          # A3 — 23 columns will not fit A4 legibly
    s.print_title_rows = "7:7"
    s.sheet_properties.pageSetUpPr.fitToPage = True
    s.page_setup.fitToWidth, s.page_setup.fitToHeight = 1, 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--csv", required=True,
                   help="dropped rows CSV from verify_date_bounds.py")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--detail", default=None,
                   help="saved pull CSV from build_miskeyed_detail.py; "
                        "adds the Line detail tab")
    a = p.parse_args()
    print(build(a.csv, a.out_dir, a.detail))
