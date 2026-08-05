"""Build the Unbilled Waybills report — FY-to-date waybills not yet invoiced.

Replicates "Unbilled Waybills Report FY27 - DD Mon YYYY.xlsx":
tabs Overview / Summary by Customer / Unbilled Detail.

Unbilled = Parcel Perfect invoice status ≤ 0 (status names mapped to PP codes).
Waybills dated on/after the billing frontier (day after the last invoiced
waybill date, weekends included) are excluded — too fresh to have billed.

Usage:
    python build_unbilled.py --wb-file ".../WB Date - March26 - Feb27..xlsx" \
        [--exclude-from YYYY-MM-DD] --out-dir out
"""

import argparse
from collections import defaultdict
from datetime import date, datetime, timedelta

import xlsxwriter
from data import col, load_export
from style import (
    ALT,
    NAVY,
    NUM,
    ORANGE,
    YELLOW,
    Styles,
    freeze_below,
    ordinal,
    set_rows,
)
from xlsxvalues import Vals

# Parcel Perfect invoice-status codes (per PP manuals); ≤ 0 means not invoiced.
STATUS_CODES = {
    "Ready for Approval": 0,
    "Summary Capture": -1,
    "Quote": -2,
    "Collection": -3,
    "Recalc Required": -6,
    "No Rate Found": -7,
    "Checked In": -8,
}


# A waybill date counts as invoiced once this share of its waybills have been.
# Same spirit as HOLIDAY_GUARD in build_flash and TRADING_GUARD in run_daily:
# one row is not evidence that a day is done.
INVOICED_GUARD = 0.5
MIN_WAYBILLS = 20   # ignore weekend and holiday days carrying a handful


def billing_frontier(rows, ix, norm) -> date:
    """First day that is NOT yet invoiced — everything from here on is normal
    billing lag rather than unbilled freight.

    Not `max(invoiced waybill date) + 1`, which is what this was and which
    breaks twice over.

    Mis-keyed years put waybills in 2522 and 9473, two of them marked Invoiced,
    which pushed the frontier to the year 9473 and excluded nothing: 1,050
    waybills and R3.07m reported on 3 Aug 2026 against 35-85 and R10-265k in
    Larry's own reports. Bounding the extract to the financial year fixes that
    at source, but a report should not depend on its input being clean.

    The subtler half is that one invoice moves a max. On 4 Aug 2026 invoicing
    had not run for August at all — 0 of 807 waybills dated the 3rd were
    invoiced at 07:13 — yet by 10:40 a single early invoice carrying a 3 Aug
    waybill date had moved the frontier from 1 Aug to the 4th, reclassifying
    all of Monday's freight as unbilled and taking the report from R41k to
    R731k. Nothing about the day had changed.

    So walk back to the newest day whose invoicing has actually happened, by
    share rather than presence, skipping days too small to judge.
    """
    today = date.today()
    per_day = defaultdict(lambda: [0, 0])          # day -> [invoiced, total]
    for r in rows:
        d = norm(r[ix["Waybill Date"]])
        if not isinstance(d, date) or d > today:   # cannot invoice before shipping
            continue
        cell = per_day[d]
        cell[1] += 1
        if str(r[ix["Status"]]) == "Invoiced":
            cell[0] += 1

    done = [d for d, (inv, tot) in per_day.items()
            if tot >= MIN_WAYBILLS and inv / tot >= INVOICED_GUARD]
    if done:
        return max(done) + timedelta(days=1)

    # Nothing clears the bar — a very new deployment, or a sparse file. Fall
    # back to the old rule so the report still builds, rather than failing.
    any_inv = [d for d, (inv, _) in per_day.items() if inv]
    if not any_inv:
        raise SystemExit("No invoiced waybills found — cannot derive billing frontier.")
    return max(any_inv) + timedelta(days=1)


def build(wb_file: str, out_dir: str, exclude_from: date | None = None) -> str:
    headers, rows = load_export(wb_file)
    ix = {n: col(headers, n) for n in
          ["Waybill", "Waybill Date", "Account", "Customer", "Service", "Status", "Subtotal"]}

    def norm(v):
        return v.date() if isinstance(v, datetime) else v

    if exclude_from is None:
        exclude_from = billing_frontier(rows, ix, norm)

    unbilled = []
    for r in rows:
        d = norm(r[ix["Waybill Date"]])
        if not isinstance(d, date) or d >= exclude_from:
            continue
        s = str(r[ix["Status"]])
        if s in STATUS_CODES and STATUS_CODES[s] <= 0:
            unbilled.append(dict(
                date=d, waybill=str(r[ix["Waybill"]]), acct=str(r[ix["Account"]]),
                cust=str(r[ix["Customer"]]), svc=str(r[ix["Service"]]),
                status=s, code=STATUS_CODES[s], sub=r[ix["Subtotal"]] or 0))
    unbilled.sort(key=lambda u: (u["date"], u["waybill"]))

    gen = date.today()  # report generation date (export may contain post-dated waybills)
    gen_str = f"{gen.day} {gen.strftime('%b %Y')}"
    total_v = sum(u["sub"] for u in unbilled)

    out_path = f"{out_dir}/Unbilled Waybills Report FY27 - {gen.day:02d} {gen.strftime('%b %Y')}.xlsx"
    wb = xlsxwriter.Workbook(out_path)
    st = Styles(wb)
    GREY = "#808080"

    def F(**kw):
        return st.get(**kw)

    # ---------------- Overview ----------------
    o = wb.add_worksheet("Overview")
    set_rows(o, {1: 27.8, 2: 19.5})     # banner rows, per the reference
    o.hide_gridlines(2)
    for i, w in enumerate([38, 10, 14, 4]):
        o.set_column(i, i, w)
    o.merge_range("A1:D1", "SUNRISE LOGISTICS",
                  F(bold=True, font_size=18, font_color="white", bg_color=NAVY))
    o.merge_range("A2:D2", "Unbilled Waybills Report — FY27 (data to date)",
                  F(font_size=11, font_color="white", bg_color=NAVY))
    cutoff_note = f"Excludes waybills dated {exclude_from.day} {exclude_from.strftime('%b %Y')} and later."
    o.write("A3", f"Generated {gen_str}  ·  Source: {wb_file.split('/')[-1]}  ·  "
                  f"Value = Subtotal (excl VAT).  Unbilled = Invoice status ≤ 0.  {cutoff_note}",
            F(font_size=9, font_color=GREY))

    kpi_or = dict(bold=True, font_size=11, font_color=NAVY, bg_color=ORANGE)
    kpi_ye = dict(bold=True, font_size=11, font_color=NAVY, bg_color=YELLOW)
    o.write("A5", "UNBILLED waybills (ready for billing)", F(**kpi_or))
    o.write("B5", "", F(**kpi_or))
    o.write("C5", len(unbilled), F(num_format=NUM, **kpi_or))
    o.write("A6", "Unbilled value (excl VAT), R", F(**kpi_ye))
    o.write("B6", "", F(**kpi_ye))
    o.write("C6", round(total_v, 2), F(num_format=NUM, **kpi_ye))

    sect = dict(bold=True, font_size=11, font_color="white", bg_color=NAVY)
    body = dict(font_size=11, font_color=NAVY)
    o.write("A8", "Unbilled by status", F(**sect))
    o.write("A9", "Status", F(**sect))
    o.write("B9", "PP Code", F(**sect))
    o.write("C9", "Waybills", F(**sect))
    by_status = defaultdict(int)
    for u in unbilled:
        by_status[u["status"]] += 1
    r = 9
    for s, n in sorted(by_status.items(), key=lambda kv: -kv[1]):
        o.write(r, 0, s, F(**body))
        o.write(r, 1, STATUS_CODES[s], F(**body))
        o.write(r, 2, n, F(num_format=NUM, **body))
        r += 1

    r += 1
    o.write(r, 0, "Unbilled by waybill month", F(**sect))
    r += 1
    o.write(r, 0, "Month", F(**sect))
    o.write(r, 2, "Waybills", F(**sect))
    r += 1
    by_month = defaultdict(int)
    for u in unbilled:
        by_month[(u["date"].year, u["date"].month)] += 1
    last = exclude_from - timedelta(days=1)
    for (y, m), n in sorted(by_month.items()):
        lab = date(y, m, 1).strftime("%b %Y")
        if (y, m) == (last.year, last.month):
            lab += f" (to {ordinal(last.day)})"
        o.write(r, 0, lab, F(**body))
        o.write(r, 2, n, F(num_format=NUM, **body))
        r += 1

    # ---------------- Summary by Customer ----------------
    s_ = wb.add_worksheet("Summary by Customer")
    set_rows(s_, {1: 21.8})
    freeze_below(s_, 1, col=0)    # headings row 1
    s_.hide_gridlines(2)
    for i, w in enumerate([10, 48, 18, 20]):
        s_.set_column(i, i, w)
    th = F(bold=True, font_color="white", bg_color=NAVY, align="center", text_wrap=True)
    for i, h in enumerate(["Account", "Customer", "Unbilled Waybills", "Unbilled Value (R)"]):
        s_.write(0, i, h, th)
    groups = defaultdict(lambda: [0, 0.0, 10 ** 9])  # (acct, cust) -> [n, value, first idx]
    for j, u in enumerate(unbilled):
        g = groups[(u["acct"], u["cust"])]
        g[0] += 1
        g[1] += u["sub"]
        g[2] = min(g[2], j)
    ranked = sorted(groups.items(), key=lambda kv: (-kv[1][1], kv[1][2]))
    for j, ((acct, cust), (n, v, _)) in enumerate(ranked):
        bg = ALT if j % 2 == 1 else "white"
        s_.write(1 + j, 0, acct, F(bg_color=bg))
        s_.write(1 + j, 1, cust, F(bg_color=bg))
        s_.write(1 + j, 2, n, F(num_format=NUM, bg_color=bg))
        s_.write(1 + j, 3, round(v, 2), F(num_format=NUM, bg_color=bg))
    tr = 1 + len(ranked)
    tot = dict(bold=True, bg_color=ORANGE, font_color=NAVY)
    s_.write(tr, 1, "TOTAL", F(**tot))
    Vals(s_).f(tr, 2, f"=SUM(C2:C{tr})", F(num_format=NUM, **tot),
               value=sum(n for _, (n, _, _) in ranked))
    Vals(s_).f(tr, 3, f"=SUM(D2:D{tr})", F(num_format=NUM, **tot),
               value=round(sum(round(v, 2) for _, (_, v, _) in ranked), 2))

    # ---------------- Unbilled Detail ----------------
    d_ = wb.add_worksheet("Unbilled Detail")
    set_rows(d_, {1: 25.5})
    freeze_below(d_, 1, col=0)    # headings row 1
    d_.hide_gridlines(2)
    for i, w in enumerate([13, 12, 9, 48, 9, 20, 8, 15]):
        d_.set_column(i, i, w)
    for i, h in enumerate(["Waybill Date", "Waybill", "Account", "Customer", "Service",
                           "Status", "PP Code", "Subtotal (R)"]):
        d_.write(0, i, h, th)
    for j, u in enumerate(unbilled):
        bg = ALT if j % 2 == 1 else "white"
        vals = [u["date"].isoformat(), u["waybill"], u["acct"], u["cust"], u["svc"],
                u["status"], u["code"], round(u["sub"], 2)]
        for i, v in enumerate(vals):
            kw = dict(bg_color=bg)
            if i == 7:
                kw["num_format"] = NUM
            d_.write(1 + j, i, v, F(**kw))
    tr = 1 + len(unbilled)
    d_.write(tr, 5, "TOTAL", F(**tot))
    Vals(d_).f(tr, 7, f"=SUM(H2:H{tr})", F(num_format=NUM, **tot),
               value=round(sum(round(u["sub"], 2) for u in unbilled), 2))

    wb.close()
    return out_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--wb-file", required=True)
    ap.add_argument("--exclude-from", default=None,
                    help="Exclude waybills on/after this date (default: day after last invoiced)")
    ap.add_argument("--out-dir", default=".")
    a = ap.parse_args()
    print(build(a.wb_file, a.out_dir,
                date.fromisoformat(a.exclude_from) if a.exclude_from else None))
