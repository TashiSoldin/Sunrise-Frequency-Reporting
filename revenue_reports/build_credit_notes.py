"""Build the standalone Credit Notes report.

No reference output exists for this one (HANDOFF: "not started") — it packages the
credit-notes analysis from the Revenue Dashboard's "MTD Credit Notes" tab as its own
workbook, following the same conventions (types Credit Note + Journal Credit only;
Subtotal excl VAT; reduces revenue).

Tabs: Overview (KPIs, FY27 monthly trend, MTD by reason) / By Customer (MTD) /
Detail (MTD, by credit note number — Reuven's change request, QT-000006,
23 Sep 2026: Credit Note No, Waybill(s), Invoice(s), Reason Code, Description,
Processed By; Credit Controller dropped; count + total in the title block).

Usage:
    python build_credit_notes.py --credits-file ".../Credits - March24 - Feb27.xls" \
        [--month YYYY-MM] --out-dir out
"""

import argparse
import calendar
from collections import defaultdict
from datetime import date

import xlsxwriter
from day_guards import plausible_window
from style import (
    ALT,
    NAVY,
    NAVY2,
    NUM,
    NUM2,
    ORANGE,
    PCT1,
    TAB_CREDIT,
    TAB_SUMMARY,
    Styles,
    freeze_below,
    set_rows,
    title_block,
)
from xlsxvalues import Vals, div

from data import excel_serial_to_date  # noqa: F401  (used via Credits loader pattern)

CREDIT_TYPES = ("Credit Note", "Journal Credit")
FY_START = date(2026, 3, 1)  # FY27


def load_credits(path, data=None):
    if data is not None:
        hdr, rows = data
    else:
        from data import load_credit_sheet

        hdr, rows = load_credit_sheet(path)
    ic = {
        n: hdr.index(n)
        for n in [
            "Receipt",
            "Account",
            "Customer Name",
            "Date",
            "Subtotal",
            "Reference",
            "Type",
            "Rep",
            "Reason",
            "Branch",
        ]
    }
    # Columns an older credits file may not carry: Waybills / Invoices were
    # added to the extract on 23 Sep 2026 (QT-000006) and the staff .xls never
    # had them; minimal fixtures lack User Name / Comment too. Blank, never
    # KeyError, so a hand run against an old file still builds.
    opt = {n: (hdr.index(n) if n in hdr else None) for n in OPTIONAL_COLS}

    def text(r, n):
        i = opt[n]
        return "" if i is None or r[i] is None else str(r[i]).strip()

    out = []
    for r in rows:
        if str(r[ic["Type"]]) not in CREDIT_TYPES or r[ic["Date"]] is None:
            continue
        rec = r[ic["Receipt"]]
        out.append(
            {
                "date": r[ic["Date"]],
                # The credit note number: Parcel Perfect stores credit notes
                # as negative receipt numbers (a float when read from .xls).
                "receipt": int(float(rec)) if rec not in (None, "") else None,
                "acct": str(r[ic["Account"]]).strip(),
                "customer": str(r[ic["Customer Name"]]).strip(),
                "value": r[ic["Subtotal"]] or 0,
                "ref": str(r[ic["Reference"]]).strip(),
                "reason": str(r[ic["Reason"]]).strip() or "(unspecified)",
                "rep": str(r[ic["Rep"]]).strip(),
                "branch": str(r[ic["Branch"]]).strip(),
                "type": str(r[ic["Type"]]).strip(),
                "user": text(r, "User Name"),  # Processed By
                "comment": text(r, "Comment"),  # Description
                "waybills": text(r, "Waybills"),
                "invoices": text(r, "Invoices"),
            }
        )
    return out


OPTIONAL_COLS = ("User Name", "Comment", "Waybills", "Invoices")

# Detail sheet columns, in Reuven's agreed order (QT-000006, 17 Sep 2026).
DETAIL_HEADERS = [
    "Date",
    "Credit Note No",
    "Waybill(s)",
    "Invoice(s)",
    "Reference",
    "Account",
    "Customer",
    "Rep",
    "Branch",
    "Reason Code",
    "Description",
    "Value",
    "Processed By",
]
DETAIL_WIDTHS = [2, 9, 13, 40, 22, 24, 9, 32, 18, 14, 22, 30, 12, 18]
DETAIL_VALUE_COL = DETAIL_HEADERS.index("Value")  # 0-based within the headers


def credit_note_no(n: dict) -> int | str:
    """The number shown in Credit Note No: the receipt number SIGNED, as
    Parcel Perfect's RECEIPT field holds it and as the Billing Detail credits
    tab has shown it since 3 Aug 2026 (Akha's decision, 23 Sep 2026 — the
    first build that morning showed it unsigned). The sort is separate: the
    Detail sheet orders by the ABSOLUTE value ascending, so the oldest note
    comes first and the sheet reads the way Reuven asked, 'lowest to
    highest', while every number carries its sign."""
    return n["receipt"] if n["receipt"] is not None else ""


def build(
    credits_file: str,
    out_dir: str,
    month: date | None = None,
    data: tuple[list[str], list[list]] | None = None,
) -> str:
    """data, when given, is injected (headers, rows) in credits-export shape —
    as load_credit_sheet returns them, or extract_revenue.credits_shaped
    builds them from a live query — and credits_file is not read."""
    notes = load_credits(credits_file, data)
    if month is None:
        # Newest PLAUSIBLE date decides the default month — bounded above by
        # today (day_guards.plausible_window): Parcel Perfect carries
        # mis-keyed future years as a matter of course, and an unbounded
        # max() over a date column is this project's recorded failure mode.
        # run_daily always passes --month; this default is for hand runs.
        _, hi = plausible_window(date.today())
        candidates = [n["date"] for n in notes if FY_START <= n["date"] <= hi]
        if not candidates:
            raise ValueError(
                "No credit notes dated between FY start and today — cannot "
                "derive a default month; pass --month YYYY-MM explicitly."
            )
        month = max(candidates).replace(day=1)
    m_end = date(
        month.year, month.month, calendar.monthrange(month.year, month.month)[1]
    )
    mtd = [n for n in notes if month <= n["date"] <= m_end]
    mtd_total = sum(n["value"] for n in mtd)
    mon_lab = (
        month.strftime("%B FY27") if month >= FY_START else month.strftime("%B %Y")
    )
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
        return F(
            bold=True,
            font_size=14,
            font_color=fc,
            bg_color=bg,
            num_format=fmt,
            align="left",
            valign="vcenter",
        )

    sect = F(bold=True, font_size=11, font_color="white", bg_color=NAVY)
    th = F(bold=True, font_size=9, font_color="white", bg_color=NAVY2)
    note8 = F(font_size=8, font_color=GREY)

    # ---------------- Overview ----------------
    ws = wb.add_worksheet("Overview")
    ws.set_tab_color(TAB_SUMMARY)  # inferred: summary tab, as elsewhere
    set_rows(ws, {7: 14, 8: 18, 12: 18})
    V = Vals(ws)
    ws.hide_gridlines(2)
    for i, w in enumerate([2, 22, 13, 12, 13, 13, 12, 13, 12, 12]):
        ws.set_column(i, i, w)
    title_block(
        ws,
        st,
        "J",
        "SUNRISE LOGISTICS",
        f"Credit Notes Report — {mon_lab}",
        "Credit notes (types Credit Note + Journal Credit) · Subtotal excl VAT · "
        "ZAR · reduces revenue",
    )

    reasons = defaultdict(lambda: [0.0, 0])
    for n in mtd:
        reasons[n["reason"]][0] += n["value"]
        reasons[n["reason"]][1] += 1
    top_reason = (
        max(reasons.items(), key=lambda kv_: kv_[1][0]) if reasons else ("—", [0, 0])
    )
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
    trend_val, trend_cnt = [], []
    for (y, m), vals in sorted(fy.items()):
        bg = ALT if r % 2 == 1 else "white"
        lab = date(y, m, 1).strftime("%b %Y")
        if (y, m) == (month.year, month.month):
            lab += " (MTD)"
        c, d = round(sum(vals)), len(vals)
        trend_val.append(c)
        trend_cnt.append(d)
        ws.write(r - 1, 1, lab, F(font_size=10, bg_color=bg))
        ws.write(r - 1, 2, c, F(font_size=10, bg_color=bg, num_format=NUM))
        ws.write(r - 1, 3, d, F(font_size=10, bg_color=bg, num_format=NUM))
        V.f(
            r - 1,
            4,
            f'=IF(D{r}=0,"",C{r}/D{r})',
            F(font_size=10, bg_color=bg, num_format=NUM),
            value=div(c, d),
        )
        ws.write(
            r - 1, 5, round(max(vals)), F(font_size=10, bg_color=bg, num_format=NUM)
        )
        r += 1
    ob = {"bold": True, "font_size": 10, "bg_color": ORANGE}
    tv, tc = sum(trend_val), sum(trend_cnt)
    ws.write(r - 1, 1, "FY27 to date", F(**ob))
    V.f(r - 1, 2, f"=SUM(C{first_r}:C{r - 1})", F(num_format=NUM, **ob), value=tv)
    V.f(r - 1, 3, f"=SUM(D{first_r}:D{r - 1})", F(num_format=NUM, **ob), value=tc)
    V.f(
        r - 1,
        4,
        f'=IF(D{r}=0,"",C{r}/D{r})',
        F(num_format=NUM, **ob),
        value=div(tv, tc),
    )

    # MTD by reason
    r += 2
    ws.merge_range(
        r - 1, 1, r - 1, 9, f"CREDIT NOTES BY REASON — {mon_short} MTD", sect
    )
    r += 1
    ws.merge_range(r - 1, 1, r - 1, 4, "Reason", th)
    ws.write(r - 1, 5, "Value", th)
    ws.write(r - 1, 6, "# Notes", th)
    ws.write(r - 1, 7, "% of Total", th)
    r += 1
    first_r = r
    ranked_reasons = sorted(reasons.items(), key=lambda kv_: -kv_[1][0])
    reason_tot = sum(round(val) for _, (val, _) in ranked_reasons)
    for reason, (val, cnt) in ranked_reasons:
        bg = ALT if r % 2 == 1 else "white"
        ws.merge_range(r - 1, 1, r - 1, 4, reason, F(font_size=9, bg_color=bg))
        ws.write(r - 1, 5, round(val), F(font_size=9, bg_color=bg, num_format=NUM))
        ws.write(r - 1, 6, cnt, F(font_size=9, bg_color=bg, num_format=NUM))
        V.f(
            r - 1,
            7,
            f"=F{r}/$F${first_r + len(reasons)}",
            F(font_size=9, bg_color=bg, num_format=PCT1),
            value=div(round(val), reason_tot, blank=0),
        )
        r += 1
    ws.merge_range(
        r - 1, 1, r - 1, 4, "Total", F(bold=True, font_size=9, bg_color=ORANGE)
    )
    V.f(
        r - 1,
        5,
        f"=SUM(F{first_r}:F{r - 1})",
        F(bold=True, font_size=9, bg_color=ORANGE, num_format=NUM),
        value=reason_tot,
    )
    V.f(
        r - 1,
        6,
        f"=SUM(G{first_r}:G{r - 1})",
        F(bold=True, font_size=9, bg_color=ORANGE, num_format=NUM),
        value=sum(cnt for _, (_, cnt) in ranked_reasons),
    )
    V.f(
        r - 1,
        7,
        f"=F{r}/F{r}",
        F(bold=True, font_size=9, bg_color=ORANGE, num_format=PCT1),
        value=1.0 if reason_tot else 0,
    )
    r += 2
    ws.merge_range(
        r - 1,
        1,
        r - 1,
        9,
        "Net revenue = gross invoiced (Subtotal, excl VAT) less these credit notes. "
        "Bad-debt reasons appear here for visibility but are treated separately as a "
        "cost in revenue reporting.",
        note8,
    )
    ws.merge_range(
        r,
        1,
        r,
        9,
        "Source: Credits export, Revenue Data folder. Blue = source values; "
        "black = formulas.",
        note8,
    )

    # ---------------- By Customer (MTD) ----------------
    ws2 = wb.add_worksheet(f"By Customer {mon_short}")
    ws2.set_tab_color(TAB_CREDIT)
    set_rows(ws2, {7: 22})
    freeze_below(ws2, 7)
    ws2.hide_gridlines(2)
    for i, w in enumerate([2, 10, 40, 22, 12, 13, 22]):
        ws2.set_column(i, i, w)
    title_block(
        ws2,
        st,
        "G",
        "SUNRISE LOGISTICS",
        f"Credit Notes by Customer — {mon_lab} MTD",
        f"{len(mtd)} notes · total R{mtd_total:,.0f} · Subtotal excl VAT · ZAR",
    )
    cust = defaultdict(lambda: [0.0, 0])
    cnames, ctop = {}, {}
    for n in mtd:
        cust[n["acct"]][0] += n["value"]
        cust[n["acct"]][1] += 1
        cnames.setdefault(n["acct"], n["customer"])
        if n["acct"] not in ctop or n["value"] > ctop[n["acct"]][1]:
            ctop[n["acct"]] = (n["reason"], n["value"])
    for i, h in enumerate(
        ["Account", "Customer", "Rep", "# Notes", "Value (R)", "Top reason (by value)"]
    ):
        ws2.write(6, 1 + i, h, th)
    rep_of = {}
    for n in mtd:
        rep_of.setdefault(n["acct"], n["rep"])
    rr = 8
    cust_cnt, cust_val = 0, 0.0
    for acct, (val, cnt) in sorted(cust.items(), key=lambda kv_: -kv_[1][0]):
        bg = ALT if rr % 2 == 0 else "white"
        ws2.write(rr - 1, 1, acct, F(font_size=9, bg_color=bg))
        ws2.write(rr - 1, 2, cnames[acct], F(font_size=9, bg_color=bg))
        ws2.write(rr - 1, 3, rep_of[acct], F(font_size=9, bg_color=bg))
        ws2.write(rr - 1, 4, cnt, F(font_size=9, bg_color=bg, num_format=NUM))
        ws2.write(
            rr - 1, 5, round(val, 2), F(font_size=9, bg_color=bg, num_format=NUM2)
        )
        ws2.write(rr - 1, 6, ctop[acct][0], F(font_size=9, bg_color=bg))
        cust_cnt += cnt
        cust_val += round(val, 2)
        rr += 1
    V2 = Vals(ws2)
    ws2.write(rr - 1, 1, "TOTAL", F(bold=True, font_size=9, bg_color=ORANGE))
    V2.f(
        rr - 1,
        4,
        f"=SUM(E8:E{rr - 1})",
        F(bold=True, font_size=9, bg_color=ORANGE, num_format=NUM),
        value=cust_cnt,
    )
    V2.f(
        rr - 1,
        5,
        f"=SUM(F8:F{rr - 1})",
        F(bold=True, font_size=9, bg_color=ORANGE, num_format=NUM2),
        value=round(cust_val, 2),
    )

    # ---------------- Detail (MTD) ----------------
    ws3 = wb.add_worksheet(f"Detail {mon_short}")
    ws3.set_tab_color(TAB_CREDIT)
    set_rows(ws3, {7: 22})
    freeze_below(ws3, 7)
    ws3.hide_gridlines(2)
    for i, w in enumerate(DETAIL_WIDTHS):
        ws3.set_column(i, i, w)
    last_col = chr(ord("B") + len(DETAIL_HEADERS) - 1)  # B..N for 13 columns
    title_block(
        ws3,
        st,
        last_col,
        "SUNRISE LOGISTICS",
        f"Credit Note Detail — {mon_lab} MTD",
        # The same two figures the Overview KPI row and the By Customer
        # subtitle compute (len(mtd), mtd_total) — they reconcile by
        # construction. Subtotal, excl VAT: Reuven's call, 17 Sep 2026.
        f"{len(mtd)} notes · total R{mtd_total:,.0f} · Subtotal excl VAT · ZAR",
    )
    for i, h in enumerate(DETAIL_HEADERS):
        ws3.write(6, 1 + i, h, th)
    rr = 8
    detail_tot = 0
    # Credit Note No ascending on the absolute value (Reuven, 16 Sep 2026:
    # "lowest to highest" — oldest note first), displayed signed; date breaks
    # ties for a note without a number.
    for n in sorted(mtd, key=lambda n_: (abs(n_["receipt"] or 0), n_["date"])):
        bg = ALT if rr % 2 == 0 else "white"
        vals = [
            n["date"].strftime("%d %b"),
            credit_note_no(n),
            n["waybills"],  # comma-separated, RECALLOC order; blank if none
            n["invoices"],  # distinct, comma-separated; blank if none
            n["ref"],
            n["acct"],
            n["customer"],
            n["rep"],
            n["branch"],
            n["reason"],
            n["comment"],
            # The source Subtotal, unrounded (NUM displays whole rand): the
            # TOTAL row then equals the header total to the cent. Summing
            # per-row rounded values put the old TOTAL R4 over the month's
            # figure (Sep 2026: 154,422 vs 154,418) — invisible while the
            # header carried no total, visible now that it does.
            n["value"],
            n["user"],
        ]
        for j, v in enumerate(vals):
            kw = {"font_size": 9, "bg_color": bg}
            if j == DETAIL_VALUE_COL:
                kw.update(num_format=NUM, font_color="#0000FF")  # blue = source
            elif j == 1:
                kw.update(num_format="0")  # a number, not 20,998
            elif j in (2, 3):
                # A note can cover dozens of waybills (41 on one Sep 2026
                # note): wrap so the whole list is readable, not cut off.
                kw.update(text_wrap=True)
            ws3.write(rr - 1, 1 + j, v, F(**kw))
        detail_tot += n["value"]
        rr += 1
    ws3.write(rr - 1, 1, "TOTAL", F(bold=True, font_size=9, bg_color=ORANGE))
    vcol = chr(ord("B") + DETAIL_VALUE_COL)  # M
    Vals(ws3).f(
        rr - 1,
        1 + DETAIL_VALUE_COL,
        f"=SUM({vcol}8:{vcol}{rr - 1})",
        F(bold=True, font_size=9, bg_color=ORANGE, num_format=NUM),
        value=round(detail_tot, 2),
    )

    wb.close()
    return out_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--credits-file", required=True)
    ap.add_argument(
        "--month", default=None, help="YYYY-MM (default: latest FY27 month in file)"
    )
    ap.add_argument("--out-dir", default=".")
    a = ap.parse_args()
    m = date.fromisoformat(a.month + "-01") if a.month else None
    print(build(a.credits_file, a.out_dir, m))
