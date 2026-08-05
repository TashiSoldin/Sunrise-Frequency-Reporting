"""Line-level detail for the mis-keyed waybills — Larry's request, 4 Aug 2026.

    "Can you pull me a more detailed report - including the following details
     Shipper, consignee, number of pieces - etc. similar to the format of the
     detailed invoice report we do daily."

Same column set and layout as the daily Billing Detail, so it reads the way he
is used to.

WHY THIS NEEDS THE DATABASE. The summary workbook was built from the
dropped-rows CSV, which carries nine columns. This needs about twenty-two.
Those rows are no longer in the FY27 export either — the bounded extract
(commit 21fef49) correctly excludes them, and the last unbounded export was
overwritten by the 4 Aug dry run. So the waybill numbers survive in the CSV but
nothing else does, and the detail has to come from Parcel Perfect directly.

Read-only: one SELECT keyed on those waybill numbers, no writes, no email.

    run_miskeyed_detail.bat

or by hand on the BI server:

    uv run research/build_miskeyed_detail.py ^
        --csv     "<synced>\\...\\2. Revenue Data\\_diagnostics\\dropped rows 2026-08-04.csv" ^
        --out-dir "<synced>\\...\\Dashboards and Data Analysis\\Data Quality"

TWO DIFFERENCES FROM THE DAILY REPORT, both labelled on the sheet rather than
left for him to notice:

  * Invoice # and Invoice Date are empty on 338 of the 340. That is the point
    of the list, but in a layout he associates with invoiced work it would
    otherwise read as missing data. The two that WERE invoiced keep their
    numbers and are called out on the Overview.
  * The stored waybill date is wrong on every row, so the date column is
    doubled: the value in Parcel Perfect, and the likely actual date taken
    from the capture date. In the daily report there is one date and it is
    right.

--from-export rebuilds from a saved pull instead of hitting the database, so
the layout can be worked on without a connection.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import xlsxwriter

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "revenue_reports"))

from style import (ALT, BLUE, DEC2, GRID, NAVY, NAVY2, NUM, NUM1, NUM2,  # noqa: E402
                   ORANGE, RED, Styles, TAB_BILLING, TAB_SUMMARY,
                   freeze_below, set_rows, title_block)

# Export-header -> VIEW_WBANALYSE column, taken from extract_revenue's map.
COLS = [
    ("Waybill", "WAYBILL"), ("Waybill Date", "WAYDATE"), ("Capture Date", "CAPTUREDATE"),
    ("Invoice", "INVOICE"), ("Invoice Date", "INVDATE"), ("Status", "STATUS"),
    ("Account", "ACCNUM"), ("Customer", "CUSTNAME"),
    ("Shipper", "ORIGPERS"), ("Consignee", "DESTPERS"),
    ("Orig Hub", "ORIGHUB"), ("Dest Hub", "DESTHUB"), ("Dest Place", "DESTTOWN"),
    ("Reference", "REFERENCE"), ("Service", "SERVICE"),
    ("Pieces", "PIECES"), ("Actual Mass", "ACTKG"), ("Chrg Mass", "CHARGEMASS"),
    ("Basic Charge", "CARTAGE"), ("Outlying Charge", "OUTLY"), ("Doc Charge", "DOCS"),
    ("Fuel", "SURCHARGE6"), ("Subtotal", "SUBTOTAL"),
]


def waybills_from_csv(path: str) -> list[str]:
    """The 340 waybill numbers. Only the numbers survive locally."""
    out = []
    for r in csv.DictReader(open(path, encoding="utf-8")):
        w = str(r["waybill"]).strip()
        if not re.fullmatch(r"[A-Za-z0-9_\-/]+", w):     # keep the IN-list clean
            raise SystemExit(f"Refusing to query an odd waybill number: {w!r}")
        out.append(w)
    return out


def pull(waybills: list[str]):
    """One read-only SELECT for those waybills."""
    sys.path.insert(0, str(HERE.parent / "revenue_reports"))
    from extract_revenue import connect, fetch

    sel = ", ".join(f"wba.{db}" for _, db in COLS)
    inlist = ", ".join("'" + w.replace("'", "''") + "'" for w in waybills)
    sql = f"SELECT {sel} FROM VIEW_WBANALYSE wba WHERE wba.WAYBILL IN ({inlist})"
    conn = connect()
    try:
        _, rows = fetch(conn, sql)
    finally:
        conn.close()
    return [dict(zip([h for h, _ in COLS], r)) for r in rows]


def norm(v):
    return v.date() if isinstance(v, datetime) else v


def likely_date(wb_date, cap_date):
    """Year taken from the capture date — see build_miskeyed_waybills.py for
    the grounding (91.2% same-day across 88,585 normally-dated waybills)."""
    if not isinstance(wb_date, date) or not isinstance(cap_date, date):
        return None
    best = None
    for yr in (cap_date.year - 1, cap_date.year, cap_date.year + 1):
        try:
            g = wb_date.replace(year=yr)
        except ValueError:
            continue
        diff = abs((g - cap_date).days)
        if best is None or diff < best[0]:
            best = (diff, g)
    return best[1] if best else None


HDR = ["Waybill", "Date in PP", "Likely date", "Invoice #", "Account", "Customer",
       "Shipper", "Consignee", "Orig", "Dest", "Destination", "Cust Ref", "Service",
       "Pcs", "Actual Mass", "Chrge Mass", "Basic", "Outly", "Service Fee", "Fuel",
       "Surcharge", "Sub-Total", "R/kg"]
WIDTHS = [2, 12, 11, 11, 9, 8, 26, 22, 22, 7, 7, 18, 12, 8, 8, 10, 10, 9, 9, 10, 9, 10, 11, 8]
FMTS = [None, None, None, None, None, None, None, None, None, None, None, None, None,
        NUM, NUM1, NUM1, NUM2, NUM2, NUM2, NUM2, NUM2, NUM2, DEC2]


def build(rows: list[dict], out_dir: str) -> str:
    for r in rows:
        r["_wb"] = norm(r["Waybill Date"])
        r["_cap"] = norm(r["Capture Date"])
        r["_likely"] = likely_date(r["_wb"], r["_cap"])
        r["_sub"] = float(r["Subtotal"] or 0)
        r["_invoiced"] = str(r["Status"]) == "Invoiced"
        b, o, s_, f = (float(r[k] or 0) for k in
                       ("Basic Charge", "Outlying Charge", "Doc Charge", "Fuel"))
        r["_parts"] = (b, o, s_, f, r["_sub"] - b - o - s_ - f)

    by_acct = defaultdict(list)
    for r in rows:
        by_acct[str(r["Account"])].append(r)
    for g in by_acct.values():
        g.sort(key=lambda r: -r["_sub"])
    ordered = sorted(by_acct.items(), key=lambda kv: -sum(r["_sub"] for r in kv[1]))

    total = sum(r["_sub"] for r in rows)
    n_inv = sum(1 for r in rows if r["_invoiced"])
    out = f"{out_dir}/Mis-keyed Waybills - line detail - 04 Aug 2026.xlsx"
    wb = xlsxwriter.Workbook(out)
    st = Styles(wb)

    # ---------------- Overview ----------------
    ov = wb.add_worksheet("Overview")
    ov.set_tab_color(TAB_SUMMARY)
    ov.hide_gridlines(2)
    ov.set_column("A:A", 2)
    for c, w in zip("BCDEF", (30, 14, 16, 12, 46)):
        ov.set_column(f"{c}:{c}", w)
    title_block(ov, st, "F", "SUNRISE LOGISTICS",
                "Mis-keyed waybills — line detail",
                f"{len(rows)} waybills · R{total:,.2f} · same columns as the daily "
                "Billing Detail · Sub-Total excl VAT · ZAR")
    body = st.get(font_size=9, border=0, text_wrap=True)
    head = st.get(bold=True, font_size=11, font_color="white", bg_color=NAVY, border=0)
    r_ = 7
    for line in [
        ("h", "What this is"),
        ("p", "The same waybills as 'Mis-keyed Waybill Dates', at line level, in the "
              "layout of the daily Billing Detail. Grouped by account, subtotal per "
              "customer, grand total at the foot."),
        ("h", "Two columns that differ from the daily report"),
        ("p", f"Invoice # is empty on {len(rows) - n_inv} of the {len(rows)}. That is what "
              f"the list is — freight with no invoice against it. {n_inv} were invoiced and "
              "keep their numbers."),
        ("p", "The date is shown twice. 'Date in PP' is the value stored in Parcel Perfect, "
              "which carries the mis-keyed year. 'Likely date' takes the year from the "
              "capture date; on normally-dated waybills the two fall on the same day 91.2% "
              "of the time, within a week 99.3%, across 88,585 waybills."),
    ]:
        kind, text = line
        ov.merge_range(r_, 1, r_, 5, text, head if kind == "h" else body)
        if kind == "p":
            ov.set_row(r_, 30)
        r_ += 1
    ov.merge_range(r_ + 1, 1, r_ + 1, 5,
                   "Source: Parcel Perfect, read directly on the BI server, keyed on the "
                   "waybill numbers from the 4 August date-bounds check. Produced by sam et al.",
                   st.get(font_size=8, font_color="#595959", border=0))

    # ---------------- Detail ----------------
    ws = wb.add_worksheet("Line detail")
    ws.set_tab_color(TAB_BILLING)
    ws.hide_gridlines(2)
    set_rows(ws, {7: 21.9})
    freeze_below(ws, 7)
    for i, w in enumerate(WIDTHS):
        ws.set_column(i, i, w)
    title_block(ws, st, "X", "SUNRISE LOGISTICS",
                "Mis-keyed waybills — line detail",
                f"Grouped by account, largest first · {len(rows)} waybills · "
                f"{len(rows) - n_inv} with no invoice · ex-VAT · ZAR")
    th = st.get(bold=True, font_size=9, font_color="white", bg_color=NAVY,
                align="center", text_wrap=True)
    for i, h in enumerate(HDR):
        ws.write(6, 1 + i, h, th)

    def cell(j, bg, bold=False):
        kw = {"font_size": 9, "bg_color": bg, "bold": bold}
        if FMTS[j]:
            kw["num_format"] = FMTS[j]
        kw["font_color"] = NAVY if bold else (BLUE if 13 <= j <= 22 else "black")
        return st.get(**kw)

    rr, grand = 7, [0.0] * 8
    for acct, lines in ordered:
        sub = [0.0] * 8
        for ln in lines:
            bg = ALT if rr % 2 == 0 else "white"
            b, o, s_, f, surch = ln["_parts"]
            pcs = float(ln["Pieces"] or 0)
            akg = float(ln["Actual Mass"] or 0)
            ckg = float(ln["Chrg Mass"] or 0)
            vals = [str(ln["Waybill"]), ln["_wb"], ln["_likely"],
                    (int(ln["Invoice"]) if isinstance(ln["Invoice"], float)
                     and ln["Invoice"] else (ln["Invoice"] or "")),
                    acct, str(ln["Customer"]), str(ln["Shipper"] or ""),
                    str(ln["Consignee"] or ""), str(ln["Orig Hub"] or ""),
                    str(ln["Dest Hub"] or ""), str(ln["Dest Place"] or ""),
                    str(ln["Reference"] or ""), str(ln["Service"] or ""),
                    pcs, round(akg, 1), round(ckg, 1), b, o, s_, f, surch, ln["_sub"],
                    (ln["_sub"] / ckg) if ckg else 0]
            for j, v in enumerate(vals):
                fmt = cell(j, bg)
                if j in (1, 2) and isinstance(v, date):
                    fmt = st.get(font_size=9, bg_color=bg, num_format="yyyy/mm/dd",
                                 font_color=(RED if j == 1 else BLUE), align="center")
                ws.write(rr, 1 + j, v, fmt)
            sub = [a + b_ for a, b_ in zip(sub, [pcs, akg, ckg, b, o, s_, f, ln["_sub"]])]
            rr += 1
        band = st.get(font_size=9, bold=True, bg_color=ALT, font_color=NAVY)
        for c in range(1, 24):
            ws.write(rr, c, "", band)
        ws.write(rr, 6, f"{lines[0]['Customer']}  —  {len(lines)} waybills", band)
        for j, v in zip((13, 14, 15, 16, 17, 18, 19, 21), sub):
            ws.write(rr, 1 + j, v, cell(j, ALT, bold=True))
        ws.write(rr, 23, (sub[7] / sub[2]) if sub[2] else 0, cell(22, ALT, bold=True))
        grand = [a + b_ for a, b_ in zip(grand, sub)]
        rr += 1

    tot = st.get(font_size=9, bold=True, bg_color=ORANGE, font_color=NAVY)
    for c in range(1, 24):
        ws.write(rr, c, "", tot)
    ws.write(rr, 6, f"GRAND TOTAL — {len(rows)} waybills, {len(ordered)} accounts", tot)
    for j, v in zip((13, 14, 15, 16, 17, 18, 19, 21), grand):
        kw = {"font_size": 9, "bold": True, "bg_color": ORANGE, "font_color": NAVY}
        if FMTS[j]:
            kw["num_format"] = FMTS[j]
        ws.write(rr, 1 + j, v, st.get(**kw))
    ws.write(rr, 23, (grand[7] / grand[2]) if grand[2] else 0,
             st.get(font_size=9, bold=True, bg_color=ORANGE, font_color=NAVY,
                    num_format=DEC2))

    ws.set_landscape()
    ws.set_paper(8)                 # A3 — 23 columns does not fit A4 legibly
    ws.fit_to_pages(1, 0)
    ws.repeat_rows(6)
    ws.print_area(1, 1, rr, 23)

    wb.close()
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--csv", required=True, help="dropped rows CSV (supplies the waybill numbers)")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--from-export", default=None,
                   help="rebuild from a saved pull instead of querying the database")
    p.add_argument("--save-pull", default=None,
                   help="write the raw pull here, so the layout can be reworked offline")
    a = p.parse_args()

    if a.from_export:
        rows = []
        for r in csv.DictReader(open(a.from_export, encoding="utf-8")):
            for k in ("Waybill Date", "Capture Date", "Invoice Date"):
                r[k] = datetime.strptime(r[k], "%Y-%m-%d").date() if r[k] else None
            rows.append(r)
    else:
        wanted = waybills_from_csv(a.csv)
        rows = pull(wanted)
        print(f"pulled {len(rows)} rows for {len(wanted)} waybill numbers")
        missing = set(wanted) - {str(r["Waybill"]) for r in rows}
        if missing:
            print(f"WARNING: {len(missing)} not found in Parcel Perfect: "
                  f"{sorted(missing)[:10]}", file=sys.stderr)
        if a.save_pull:
            with open(a.save_pull, "w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=[h for h, _ in COLS])
                w.writeheader()
                for r in rows:
                    w.writerow({k: (norm(v).isoformat() if isinstance(norm(v), date)
                                    else v) for k, v in r.items() if k in dict(COLS)})
            print(f"raw pull saved to {a.save_pull}")

    print(build(rows, a.out_dir))


if __name__ == "__main__":
    main()
