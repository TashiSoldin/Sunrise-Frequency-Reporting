"""Pull line-level detail for the mis-keyed waybills — Larry's request, 4 Aug 2026.

    "Can you pull me a more detailed report - including the following details
     Shipper, consignee, number of pieces - etc. similar to the format of the
     detailed invoice report we do daily."

Pulls the columns the daily Billing Detail shows and writes them to CSV. The
workbook is built by build_miskeyed_waybills.py --detail, so the line detail
lands as a sixth tab of the summary rather than as a second file with a
confusingly similar name.

WHY THIS NEEDS THE DATABASE. The summary workbook was built from the
dropped-rows CSV, which carries nine columns. This needs about twenty-two.
Those rows are no longer in the FY27 export either — the bounded extract
(commit 21fef49) correctly excludes them, and the last unbounded export was
overwritten by the 4 Aug dry run. So the waybill numbers survive in the CSV but
nothing else does, and the detail has to come from Parcel Perfect directly.

Read-only: one SELECT keyed on those waybill numbers, no writes, no email.

    research\run_miskeyed_detail.bat

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

The saved pull is the reusable artefact: the workbook can be rebuilt from it
any number of times without touching the database again.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "revenue_reports"))

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

CHUNK = 100   # parameters per statement; Firebird caps this and builds differ


def waybills_from_csv(path: str) -> list[str]:
    """The 340 waybill numbers. Only the numbers survive locally.

    No character whitelist. The first version had one and it rejected
    'SL0053788.' on the trailing full stop — Parcel Perfect waybill numbers
    contain spaces, hyphens, slashes, full stops, parentheses, hashes and
    ampersands (6,743 hyphens and 1,096 full stops across the FY27 export), so
    any whitelist narrow enough to be worth having is narrow enough to reject
    real data. The query is parameterised instead, which removes the reason
    for one.
    """
    return [str(r["waybill"]).strip()
            for r in csv.DictReader(open(path, encoding="utf-8"))
            if str(r["waybill"]).strip()]


def pull(waybills: list[str]):
    """Read-only SELECTs for those waybills.

    _clean is applied to every value, which fetch() does not do for you — its
    callers in extract_revenue apply it themselves. It handles the latin1 to
    cp1252 transcode that makes customer names match the manual export, and
    truncates times to whole seconds. It also turns Decimal into float, though
    that part is cosmetic: xlsxwriter writes Decimal correctly, contrary to
    what an earlier version of this comment claimed.
    """
    sys.path.insert(0, str(HERE.parent / "revenue_reports"))
    from extract_revenue import _clean, connect

    sel = ", ".join(f"wba.{db}" for _, db in COLS)
    heads = [h for h, _ in COLS]
    out, conn = [], connect()
    try:
        # Parameterised, and in batches: Firebird caps how many parameters one
        # statement may carry, and 340 is close enough to the limit on some
        # builds to be worth not finding out on the only run that matters.
        for i in range(0, len(waybills), CHUNK):
            batch = waybills[i:i + CHUNK]
            sql = (f"SELECT {sel} FROM VIEW_WBANALYSE wba "
                   f"WHERE wba.WAYBILL IN ({', '.join('?' * len(batch))})")
            with conn.cursor() as cur:
                cur.execute(sql, batch)
                out += [{h: _clean(v) for h, v in zip(heads, r)}
                        for r in cur.fetchall()]
    finally:
        conn.close()
    return out


def reconcile(rows: list[dict], csv_path: str) -> None:
    """Check the pull against Monday's listing before anything is built.

    Three things can go wrong and none of them raise on their own: a waybill
    that no longer exists, a waybill that comes back more than once, and a
    subtotal that has moved since. The last would put two workbooks in front
    of Larry that disagree, so it is worth a line of output either way.
    """
    was = {}
    for r in csv.DictReader(open(csv_path, encoding="utf-8")):
        was[str(r["waybill"])] = float(r["subtotal"] or 0)
    got = defaultdict(list)
    for r in rows:
        got[str(r["Waybill"])].append(float(r["Subtotal"] or 0))

    missing = sorted(set(was) - set(got))
    dupes = sorted(w for w, v in got.items() if len(v) > 1)
    moved = sorted(w for w, v in got.items()
                   if w in was and abs(sum(v) - was[w]) > 0.005)

    print(f"reconciliation against {Path(csv_path).name}:")
    print(f"   expected {len(was)} waybills, pulled {len(rows)} rows "
          f"for {len(got)} distinct waybills")
    for label, items in (("not found in Parcel Perfect", missing),
                         ("returned on more than one row", dupes),
                         ("sub-total differs from Monday", moved)):
        if items:
            print(f"   ** {len(items)} {label}: {items[:10]}"
                  f"{' ...' if len(items) > 10 else ''}", file=sys.stderr)
        else:
            print(f"   none {label}")
    if not (missing or dupes or moved):
        print("   clean — the pull matches Monday's listing exactly")


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


def rows_from_export(path: str) -> list[dict]:
    """Read a saved pull back, with the date columns parsed."""
    out = []
    for r in csv.DictReader(open(path, encoding="utf-8")):
        for k in ("Waybill Date", "Capture Date", "Invoice Date"):
            v = str(r.get(k) or "").strip()
            r[k] = datetime.strptime(v, "%Y-%m-%d").date() if v else None
        out.append(r)
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--csv", required=True,
                   help="dropped rows CSV (supplies the waybill numbers)")
    p.add_argument("--save-pull", required=True, help="where to write the pull")
    a = p.parse_args()

    rows = pull(waybills_from_csv(a.csv))
    reconcile(rows, a.csv)

    heads = [h for h, _ in COLS]
    with open(a.save_pull, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=heads)
        w.writeheader()
        for r in rows:
            w.writerow({k: (norm(v).isoformat() if isinstance(norm(v), date) else v)
                        for k, v in r.items() if k in heads})
    print(a.save_pull)


if __name__ == "__main__":
    main()
