"""Build the Billing Detail workbook — every invoice line for one day.

Tabs: "Billing DD Mon", optional "Flash Comparison" (only when --flash-file is
given, mirroring Larry's 24 Jul special), "By Customer", "Consolidations",
"Credit Notes DD Mon".

Usage:
    python build_billing_detail.py --date 2026-07-24 \
        --inv-file ".../INV Date - March26 - Feb27..xlsx" \
        --credits-file ".../Credits - March24 - Feb27.xls" \
        [--flash-file ".../Flash Revenue - 24 Jul 2026.xlsx"] \
        --out-dir out

Derivations reconciled against the 24 Jul 2026 reference:
  * Component columns: Basic=Basic Charge, Outly=Outlying Charge,
    Service Fee=Doc Charge, Fuel=Fuel, Surcharge = Subtotal − (those four).
  * Billing tab grouped by (Account, Customer), accounts ascending.
  * Consolidations = First Ref groups where any member Consolidated == "Yes".
  * Flash Comparison shipping side reads the day's FROZEN flash workbook
    (the live WB export firms up afterwards as more waybills are captured).
"""

import argparse
from collections import defaultdict
from datetime import date

import openpyxl
import xlsxwriter

from data import col, load_credit_sheet, load_export
from style import (ALT, NAVY, NAVY2, ORANGE, RED, RED_LIGHT, YELLOW, NUM, NUM1, NUM2, DEC2,
                   PCT1, Styles, TAB_BILLING, TAB_CREDIT, TAB_SUMMARY, H_BILLING, H_BILLING_LATE,
                   freeze_below, set_rows, title_block)

BRANCH_MAP = {
    "JNB": "JHB", "PRY": "JHB", "CPT": "Cape Town",
    "DUR": "Durban", "KZ1": "Durban", "KZ3": "Durban", "PMB": "Durban",
}
BUDGET_REPS = ["CN", "TF", "NP", "LS", "PM"]
CREDIT_TYPES = ("Credit Note", "Journal Credit")


def load_day(inv_file: str, day: date):
    headers, rows = load_export(inv_file)
    ix = {
        n: col(headers, n)
        for n in [
            "Waybill", "Waybill Date", "Invoice", "Account", "Customer",
            "Shipper", "Consignee", "Orig Hub", "Dest Hub", "Dest Place",
            "Reference", "Service", "Pieces", "Actual Mass", "Chrg Mass",
            "Basic Charge", "Outlying Charge", "Doc Charge", "Fuel",
            "Subtotal", "Invoice Date", "Salesrep", "Rep", "First Ref",
            "Consolidated",
        ]
    }
    day_rows = [r for r in rows if r[ix["Invoice Date"]] == day and "~" not in str(r[ix["Waybill"]])]
    return ix, day_rows, rows


def line_components(r, ix):
    basic = r[ix["Basic Charge"]] or 0
    outly = r[ix["Outlying Charge"]] or 0
    svc = r[ix["Doc Charge"]] or 0
    fuel = r[ix["Fuel"]] or 0
    sub = r[ix["Subtotal"]] or 0
    surch = sub - basic - outly - svc - fuel
    return basic, outly, svc, fuel, surch, sub


def build(day: date, inv_file: str, credits_file: str, out_dir: str, flash_file: str | None = None) -> str:
    ix, day_rows, _ = load_day(inv_file, day)
    if not day_rows:
        raise SystemExit(f"No invoice lines for {day} — not yet invoiced? Use the flash instead.")

    dm = f"{day.day:02d} {day.strftime('%b')}"
    long_date = f"{day.day} {day.strftime('%B %Y')}"
    short_date = f"{dm} {day.year}"

    out_path = f"{out_dir}/Billing Detail - {short_date}.xlsx"
    wb = xlsxwriter.Workbook(out_path)
    st = Styles(wb)

    # ---------------- Tab 1: Billing lines ----------------
    ws = wb.add_worksheet(f"Billing {dm}")
    ws.set_tab_color(TAB_SUMMARY)
    set_rows(ws, H_BILLING)
    freeze_below(ws, 7)           # headings row 7
    ws.hide_gridlines(2)
    widths = [2, 11, 9.5, 10, 8, 26, 22, 22, 9.5, 9.5, 18, 12, 9.5, 9.5, 9.5, 9.5, 9.5, 9.5, 9.5, 9.5, 9.5, 11, 8]
    for i, w in enumerate(widths):
        ws.set_column(i, i, w)

    groups = defaultdict(list)  # account -> rows
    names = {}
    for r in day_rows:
        acc = str(r[ix["Account"]])
        groups[acc].append(r)
        names.setdefault(acc, str(r[ix["Customer"]]))
    for g in groups.values():
        g.sort(key=lambda r: -(r[ix["Subtotal"]] or 0))
    ordered = sorted(groups.items(), key=lambda kv: kv[0])

    title_block(ws, st, "W", "SUNRISE LOGISTICS",
                f"Billing Component Detail — Invoice date {short_date}",
                f"Every waybill invoiced on {short_date} · charges left→right ending in Sub-Total (ex-VAT) then R/kg · "
                f"mirrors tax-invoice layout · {len(day_rows)} lines · ZAR")

    headers = ["Waybill", "Date", "Invoice #", "Account", "Customer", "Consignor", "Consignee",
               "Orig", "Dest", "Destination", "Cust Ref", "Service", "Pcs", "Actual Mass", "Chrge Mass",
               "Basic", "Outly", "Service Fee", "Fuel", "Surcharge", "Sub-Total", "R/kg"]
    th = st.get(bold=True, font_size=9, font_color="white", bg_color=NAVY)
    for i, h in enumerate(headers):
        ws.write(6, 1 + i, h, th)

    numfmts = [None, None, None, None, None, None, None, None, None, None, None, None,
               NUM, NUM1, NUM1, NUM2, NUM2, NUM2, NUM2, NUM2, NUM2, DEC2]

    def cellfmt(j, bg, bold=False):
        kw = {"font_size": 9, "bg_color": bg}
        if bold:
            kw["bold"] = True
        if numfmts[j]:
            kw["num_format"] = numfmts[j]
        return st.get(**kw)

    def intstr(v):
        """Invoice numbers come through as floats; the reference stores them as ints."""
        return int(v) if isinstance(v, float) and v == int(v) else (v or "")

    r_ = 7  # 0-indexed
    gtot = [0.0] * 9  # pcs, actual, chrg, basic, outly, svc, fuel, surch, sub
    for acc, lines in ordered:
        custname = names[acc]
        stot = [0.0] * 9
        for line in lines:
            bg = ALT if r_ % 2 == 0 else "white"
            b_, o_, s_, f_, su_, sub_ = line_components(line, ix)
            vals = [
                str(line[ix["Waybill"]]),
                line[ix["Waybill Date"]].strftime("%Y/%m/%d") if isinstance(line[ix["Waybill Date"]], date) else "",
                intstr(line[ix["Invoice"]]),
                acc, custname,
                str(line[ix["Shipper"]] or ""), str(line[ix["Consignee"]] or ""),
                str(line[ix["Orig Hub"]] or ""), str(line[ix["Dest Hub"]] or ""),
                str(line[ix["Dest Place"]] or ""), str(line[ix["Reference"]] or ""),
                str(line[ix["Service"]] or ""),
                line[ix["Pieces"]] or 0, round(line[ix["Actual Mass"]] or 0, 1), round(line[ix["Chrg Mass"]] or 0, 1),
                b_, o_, s_, f_, su_, sub_,
                (sub_ / line[ix["Chrg Mass"]]) if line[ix["Chrg Mass"]] else 0,
            ]
            for j, v in enumerate(vals):
                ws.write(r_, 1 + j, v, cellfmt(j, bg))
            nums = [line[ix["Pieces"]] or 0, line[ix["Actual Mass"]] or 0, line[ix["Chrg Mass"]] or 0, b_, o_, s_, f_, su_, sub_]
            stot = [a + b for a, b in zip(stot, nums)]
            r_ += 1
        def totals_row(label, tvals, bg):
            ws.write(r_, 5, label, cellfmt(4, bg, True))
            for j, v in enumerate(tvals):  # cols N..V = 13..21
                ws.write(r_, 13 + j, round(v, 1) if j in (1, 2) else v, cellfmt(12 + j, bg, True))
            ws.write(r_, 22, (tvals[8] / tvals[2]) if tvals[2] else 0, cellfmt(21, bg, True))

        totals_row(f"{custname}  —  subtotal ({len(lines)})", stot, YELLOW)
        gtot = [a + b for a, b in zip(gtot, stot)]
        r_ += 1
    totals_row_label = "GRAND TOTAL — all customers"
    ws.write(r_, 5, totals_row_label, cellfmt(4, ORANGE, True))
    for j, v in enumerate(gtot):
        ws.write(r_, 13 + j, round(v, 1) if j in (1, 2) else v, cellfmt(12 + j, ORANGE, True))
    ws.write(r_, 22, (gtot[8] / gtot[2]) if gtot[2] else 0, cellfmt(21, ORANGE, True))

    inv_total, inv_kg, inv_lines = gtot[8], gtot[2], len(day_rows)

    # ---------------- Tab 2: Flash Comparison (optional) ----------------
    if flash_file:
        _flash_comparison(wb, st, day, day_rows, ix, flash_file, long_date, inv_total, inv_kg, inv_lines)

    # ---------------- Tab 3: By Customer ----------------
    ws3 = wb.add_worksheet("By Customer")
    ws3.set_tab_color(TAB_BILLING)
    set_rows(ws3, H_BILLING)
    freeze_below(ws3, 7)
    ws3.hide_gridlines(2)
    for i, w in enumerate([2, 8, 30, 7, 11, 12, 11, 11, 12, 12, 13, 8]):
        ws3.set_column(i, i, w)
    cust = defaultdict(lambda: [0.0] * 8)  # pcs kg basic outly svc fuel surch sub
    cnames = {}
    for r in day_rows:
        b_, o_, s_, f_, su_, sub_ = line_components(r, ix)
        k = str(r[ix["Account"]])
        cnames.setdefault(k, str(r[ix["Customer"]]))
        for j, v in enumerate([r[ix["Pieces"]] or 0, r[ix["Chrg Mass"]] or 0, b_, o_, s_, f_, su_, sub_]):
            cust[k][j] += v
    ranked = sorted(((k, cnames[k], v) for k, v in cust.items()), key=lambda kv: -kv[2][7])
    title_block(ws3, st, "L", "SUNRISE LOGISTICS",
                f"Billing by Customer — Invoice date {short_date}",
                f"Sub-total per customer with component breakdown · ex-VAT · {len(ranked)} customers · ZAR")
    hdr3 = ["Account", "Customer", "Pcs", "Chrg kg", "Basic", "Outly", "Service Fee", "Fuel", "Surcharge", "Sub-Total", "R/kg"]
    fmts3 = [None, None, NUM, NUM1, NUM2, NUM2, NUM2, NUM2, NUM2, NUM2, DEC2]
    for i, h in enumerate(hdr3):
        ws3.write(6, 1 + i, h, th)
    rr = 7
    for acc, cname, v in ranked:
        bg = ALT if rr % 2 == 0 else "white"
        row = [acc, cname, v[0], round(v[1], 1), *v[2:], (v[7] / v[1]) if v[1] else 0]
        for j, x in enumerate(row):
            kw = {"font_size": 9, "bg_color": bg}
            if fmts3[j]:
                kw["num_format"] = fmts3[j]
            ws3.write(rr, 1 + j, x, st.get(**kw))
        rr += 1
    tot = [sum(v[j] for _, _, v in ranked) for j in range(8)]
    trow = ["TOTAL", f"{len(ranked)} customers", tot[0], round(tot[1], 1), *tot[2:], (tot[7] / tot[1]) if tot[1] else 0]
    for j, x in enumerate(trow):
        kw = {"font_size": 9, "bold": True, "bg_color": ORANGE}
        if fmts3[j]:
            kw["num_format"] = fmts3[j]
        ws3.write(rr, 1 + j, x, st.get(**kw))

    # ---------------- Tab 4: Consolidations ----------------
    _consolidations(wb, st, th, day_rows, ix, short_date)

    # ---------------- Tab 5: Credit Notes ----------------
    _credit_notes(wb, st, day, credits_file, dm, short_date)

    wb.close()
    return out_path


def _flash_comparison(wb, st, day, day_rows, ix, flash_file, long_date, inv_total, inv_kg, inv_lines):
    f = openpyxl.load_workbook(flash_file, data_only=True).active
    f_rev, f_wbs, f_kg = f["B8"].value or 0, f["D8"].value or 0, f["F8"].value or 0
    f_branch, f_rep = {}, {}
    section = None
    for row in f.iter_rows(min_col=2, max_col=3):
        v = row[0].value
        if v in ("BY BRANCH (origin)", "BY REP", "TOP 10 CUSTOMERS"):
            section = v
        elif section == "BY BRANCH (origin)" and v and row[1].value is not None and v != "Branch":
            f_branch[v] = row[1].value
        elif section == "BY REP" and v and row[1].value is not None and v != "Rep":
            f_rep[str(v).split(" — ")[0]] = row[1].value

    inv_branch = defaultdict(float)
    inv_rep = defaultdict(float)
    for r in day_rows:
        sub = r[ix["Subtotal"]] or 0
        inv_branch[BRANCH_MAP.get(str(r[ix["Orig Hub"]]), "Other")] += sub
        inv_rep[str(r[ix["Salesrep"]])] += sub
    rep_names = {str(r[ix["Salesrep"]]): str(r[ix["Rep"]]) for r in day_rows if r[ix["Rep"]]}

    ws = wb.add_worksheet("Flash Comparison")
    ws.set_tab_color(TAB_BILLING)   # no freeze in the reference
    ws.hide_gridlines(2)
    for i, w in enumerate([2, 26, 16, 16, 15, 12]):
        ws.set_column(i, i, w)
    title_block(ws, st, "F", "SUNRISE LOGISTICS",
                f"{long_date} — Invoice-date Billing vs Flash (Waybill) Report",
                f"Left = invoices raised on {day.day} {day.strftime('%b')} (this workbook). Right = waybills moved on "
                f"{day.day} {day.strftime('%b')} (flash report). Differences are timing — invoicing lags shipping.")
    sect = st.get(bold=True, font_size=11, font_color="white", bg_color=NAVY)
    colh = st.get(bold=True, font_size=9, font_color="white", bg_color=NAVY2, text_wrap=True, align="center")

    def block(r0, title_, rows_, total=None):
        """rows_ = list of (label, invoice, flash, wantvar); returns next row"""
        ws.merge_range(r0, 1, r0, 5, title_, sect)
        ws.write(r0 + 1, 1, "", colh)
        for j, h in enumerate(["Invoice date\n(billing)", "Waybill / Flash\n(shipping)", "Variance", "Var %"]):
            ws.write(r0 + 1, 2 + j, h, colh)
        rr = r0 + 2
        for i, (lab, a, b, wantvar, emphas) in enumerate(rows_):
            bg = YELLOW if emphas else (ALT if rr % 2 == 0 else "white")
            bold = bool(emphas)
            dec = isinstance(a, float) and a < 100
            base = {"font_size": 10, "bg_color": bg, "bold": bold}
            ws.write(rr, 1, lab, st.get(**base))
            nf = DEC2 if dec else NUM
            ws.write(rr, 2, a, st.get(num_format=nf, **base))
            ws.write(rr, 3, b, st.get(num_format=nf, **base))
            if wantvar:
                ws.write(rr, 4, a - b, st.get(num_format=NUM, **base))
                ws.write(rr, 5, (a - b) / b if b else 0, st.get(num_format=PCT1, **base))
            rr += 1
        return rr

    rr = block(6, "TOTAL & KEY METRICS", [
        ("Revenue (Subtotal ex-VAT)", round(inv_total), round(f_rev), True, True),
        ("Chargeable kg", round(inv_kg), round(f_kg), True, False),
        ("R / kg", round(inv_total / inv_kg, 2) if inv_kg else 0.0, round(f_rev / f_kg, 2) if f_kg else 0.0, False, False),
        ("Line count", inv_lines, f_wbs, True, False),
    ])
    branches = ["JHB", "Cape Town", "Durban", "Other"]
    rows_ = [(b, round(inv_branch.get(b, 0)), round(f_branch.get(b, 0) or 0), True, False) for b in branches]
    rows_.append(("Total", round(inv_total), round(f_rev), True, True))
    rr = block(rr + 1, "BY BRANCH (origin)", rows_)
    rows_ = [(f"{c} — {rep_names.get(c, c)}", round(inv_rep.get(c, 0)), round(f_rep.get(c, 0) or 0), True, False) for c in BUDGET_REPS]
    other_inv = inv_total - sum(inv_rep.get(c, 0) for c in BUDGET_REPS)
    other_f = f_rev - sum(f_rep.get(c, 0) or 0 for c in BUDGET_REPS)
    rows_.append(("Other", round(other_inv), round(other_f), True, False))
    rows_.append(("Total", round(inv_total), round(f_rev), True, True))
    rr = block(rr + 1, "BY REP", rows_)

    note = st.get(font_size=8)
    gap = f_rev - inv_total
    ws.merge_range(rr + 1, 1, rr + 1, 5,
                   f"Reading the gap: waybills moved on the {day.day}th (R{f_rev:,.0f}) "
                   f"{'exceeded' if gap > 0 else 'trailed'} invoices raised that day (R{inv_total:,.0f}) by R{abs(gap):,.0f} "
                   f"({gap / inv_total:+.1%}) — normal invoicing lag; some of the day's shipments invoice on later days, "
                   f"and some of the day's invoices cover earlier waybills.", note)
    ws.merge_range(rr + 2, 1, rr + 2, 5,
                   "Note: the flash was a same-day snapshot; the waybill file firms up afterwards as more of the day's "
                   "waybills are captured — so the true shipping-vs-billing gap may be wider than shown here.", note)
    ws.merge_range(rr + 3, 1, rr + 3, 5,
                   "Rep and branch splits differ by basis because a waybill's origin/rep is fixed at shipping, "
                   "while invoices group by billing account.", note)


def _consolidations(wb, st, th, day_rows, ix, short_date):
    groups = defaultdict(list)
    for r in day_rows:
        fr = str(r[ix["First Ref"]]).strip()
        if fr:
            groups[fr].append(r)
    cons = {fr: g for fr, g in groups.items() if any(str(x[ix["Consolidated"]]) == "Yes" for x in g)}
    r0_first = sorted(cons.items(), key=lambda kv: (sum((x[ix["Subtotal"]] or 0) for x in kv[1]) != 0,))

    ws = wb.add_worksheet("Consolidations")
    ws.set_tab_color(TAB_CREDIT)
    set_rows(ws, {7: 20.1})
    freeze_below(ws, 7)
    ws.hide_gridlines(2)
    for i, w in enumerate([2, 14, 6, 8, 26, 24, 6, 6, 6, 6, 9, 11, 8]):
        ws.set_column(i, i, w)
    n_r0 = sum(1 for _, g in cons.items() if sum((x[ix["Subtotal"]] or 0) for x in g) == 0)
    title_block(ws, st, "M", "SUNRISE LOGISTICS",
                f"Consolidation Groups — Invoice date {short_date}",
                f"Waybills grouped by consolidation reference (First Ref) · {len(cons)} groups · "
                f"{n_r0} billed at R0 (highlighted red) · ex-VAT · ZAR")
    hdr = ["Waybill", "Cons", "Account", "Customer", "Consignee", "Orig", "Dest", "Svc", "Pcs", "Chrg kg", "Sub-Total", "R/kg"]
    for i, h in enumerate(hdr):
        ws.write(6, 1 + i, h, th)
    rr = 7
    for fr, g in r0_first:
        total = sum((x[ix["Subtotal"]] or 0) for x in g)
        is_r0 = total == 0
        if is_r0:
            tag = "⚠ NOT BILLED anywhere — check"
            hstyle = st.get(bold=True, font_size=9, font_color="white", bg_color=RED)
        else:
            tag = f"consolidated — billed on master this day (R{total:,.0f})"
            hstyle = st.get(bold=True, font_size=9, font_color="white", bg_color=NAVY2)
        ws.merge_range(rr, 1, rr, 12, f"Ref {fr}   —   {len(g)} waybills   —   {tag}", hstyle)
        rr += 1
        kg_t = pcs_t = 0.0
        for i, x in enumerate(g):
            bg = RED_LIGHT if is_r0 else (ALT if rr % 2 == 0 else "white")
            sub = x[ix["Subtotal"]] or 0
            kg = x[ix["Chrg Mass"]] or 0
            vals = [str(x[ix["Waybill"]]), str(x[ix["Consolidated"]] or "No"), str(x[ix["Account"]]),
                    str(x[ix["Customer"]]), str(x[ix["Consignee"]] or ""), str(x[ix["Orig Hub"]] or ""),
                    str(x[ix["Dest Hub"]] or ""), str(x[ix["Service"]] or ""), x[ix["Pieces"]] or 0,
                    kg, sub, (sub / kg) if kg else 0]
            fmts = [None, None, None, None, None, None, None, None, NUM, NUM1, NUM2, DEC2]
            for j, v in enumerate(vals):
                kw = {"font_size": 9, "bg_color": bg}
                if fmts[j]:
                    kw["num_format"] = fmts[j]
                ws.write(rr, 1 + j, v, st.get(**kw))
            kg_t += kg
            pcs_t += x[ix["Pieces"]] or 0
            rr += 1
        gt = st.get(bold=True, font_size=9, bg_color=ORANGE)
        ws.write(rr, 1, "Group total", gt)
        ws.write(rr, 10, kg_t, st.get(bold=True, font_size=9, bg_color=ORANGE, num_format=NUM1))
        ws.write(rr, 11, total, st.get(bold=True, font_size=9, bg_color=ORANGE, num_format=NUM2))
        ws.write(rr, 12, (total / kg_t) if kg_t else 0, st.get(bold=True, font_size=9, bg_color=ORANGE, num_format=DEC2))
        rr += 2


def _credit_notes(wb, st, day, credits_file, dm, short_date):
    hdr, rows = load_credit_sheet(credits_file)
    ic = {n: hdr.index(n) for n in ["Receipt", "Account", "Customer Name", "Date", "Subtotal", "Reference", "Type", "Rep", "Reason", "Branch", "Credit Controller"]}
    notes = [r for r in rows
             if str(r[ic["Type"]]) in CREDIT_TYPES and r[ic["Date"]] == day]

    ws = wb.add_worksheet(f"Credit Notes {dm}")
    ws.set_tab_color(TAB_CREDIT)
    set_rows(ws, H_BILLING_LATE)
    ws.hide_gridlines(2)
    for i, w in enumerate([2, 10, 9, 28, 16, 13, 22, 12, 26]):
        ws.set_column(i, i, w)
    total = sum(r[ic["Subtotal"]] or 0 for r in notes)
    title_block(ws, st, "I", "SUNRISE LOGISTICS",
                f"Credit Notes Passed — {short_date}",
                f"Credit notes processed on {short_date} · {len(notes)} notes · total R{total:,.0f} (reduces revenue) · ex-VAT · ZAR")
    ws.merge_range("B7:I7", "BY REASON", st.get(bold=True, font_size=11, font_color="white", bg_color=NAVY))
    rr = 7
    reasons = defaultdict(lambda: [0, 0.0])
    for r in notes:
        rs = str(r[ic["Reason"]]) or "(no reason)"
        reasons[rs][0] += 1
        reasons[rs][1] += r[ic["Subtotal"]] or 0
    for rs, (n, val) in sorted(reasons.items(), key=lambda kv: -kv[1][1]):
        bg = ALT if rr % 2 == 1 else "white"
        ws.write(rr, 1, rs, st.get(font_size=9, bg_color=bg))
        ws.write(rr, 6, f"{n} note(s)", st.get(font_size=9, bg_color=bg))
        ws.write(rr, 7, val, st.get(font_size=9, bg_color=bg, num_format=NUM2))
        rr += 1
    rr += 1
    th2 = st.get(bold=True, font_size=9, font_color="white", bg_color=NAVY)
    for j, h in enumerate(["CN #", "Account", "Customer", "Rep", "Branch", "Reason", "Value", "Credit Controller"]):
        ws.write(rr, 1 + j, h, th2)
    freeze_below(ws, rr + 1)      # moves with the by-reason block above it
    rr += 1
    for r in notes:
        bg = ALT if rr % 2 == 0 else "white"
        rcpt = r[ic["Receipt"]]
        vals = [str(int(rcpt)) if isinstance(rcpt, float) else str(rcpt),
                str(r[ic["Account"]]), str(r[ic["Customer Name"]]),
                str(r[ic["Rep"]]), str(r[ic["Branch"]]),
                str(r[ic["Reason"]]), r[ic["Subtotal"]] or 0,
                str(r[ic["Credit Controller"]])]
        for j, v in enumerate(vals):
            kw = {"font_size": 9, "bg_color": bg}
            if j == 6:
                kw["num_format"] = NUM2
            ws.write(rr, 1 + j, v, st.get(**kw))
        rr += 1
    ws.write(rr, 1, "TOTAL", st.get(bold=True, font_size=9, bg_color=ORANGE))
    ws.write(rr, 7, total, st.get(bold=True, font_size=9, bg_color=ORANGE, num_format=NUM2))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--date", required=True)
    p.add_argument("--inv-file", required=True)
    p.add_argument("--credits-file", required=True)
    p.add_argument("--flash-file", default=None)
    p.add_argument("--out-dir", default=".")
    a = p.parse_args()
    print(build(date.fromisoformat(a.date), a.inv_file, a.credits_file, a.out_dir, a.flash_file))
