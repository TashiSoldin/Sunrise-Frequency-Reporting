"""Production revenue extraction — Phase 2 of PLAN.md.

Produces the three daily files Larry's process drops in
"Dashboards and Data Analysis/2. Revenue Data", replacing the manual
"Analyze Waybills" export:

    WB Date - March{Y} - Feb{Y+1}..xlsx    (waybill-date basis, current FY)
    INV Date - March{Y} - Feb{Y+1}..xlsx   (invoice-date basis, current FY)
    Credits - March{Y-2} - Feb{Y+1}.xlsx   (credit notes, 3 FYs — pending
                                            table discovery, see CREDITS_SQL)

Run on the BI server from the repo root (same .env as the smoke test):

    uv run revenue_reports/extract_revenue.py --out-dir "<shared folder>/2. Revenue Data"

Reconciliation contract (validated 29 Jul 2026 vs the 28 Jul manual export):
  - Source: VIEW_WBANALYSE. Export layouts are renamed view columns.
  - Exclude tilde waybills (WAYBILL LIKE '%~%') — re-delivery duplicates.
  - Exclude STATUS = 'Cancelled' — the manual export omits them.
  - No upper date cap: the manual export includes future-dated waybills
    (pre-captured collections, e.g. dated 31 Jul in a 28 Jul pull).
  - All other statuses are included on the WB basis; the INV basis is
    implicitly Invoiced-only because INVDATE is set at invoicing.
  - Same-status rows matched the manual export exactly (0 subtotal diffs on
    2,431 rows); all remaining deltas were live-DB drift (re-rated rows whose
    status changed between pulls).

Column mapping status (verified 29 Jul against the manual export via
research/revenue_extract_verify.py — per-column diff on 2,431 same-status
waybills, 22-27 Jul window):
  - Surcharge order comes from VIEW_SURCHARGES: S1=Sameday, S2=Tail-lift,
    S3=Late/Early, S4=Sat/Sun, S5=Futile, S6=Fuel, S7=Chainstore,
    S8=DC Chainstore, S9=Townships. Confirmed by the diff.
  - Cost centres are crossed in PP's export: "Waybill Cost Centre"=CCNAME,
    "Customer Cost Centre"=COSTCNTRNAME (both 100% after swap).
  - Export's "Last Delivery Driver" duplicates "Delivery Agent" (equal in
    all 3,287 window rows) — both map to DELIVERYAGENT. The view's
    LASTDELDRIVER (person names) appears nowhere in the export.
  - INPUTMETHOD and COLSTATUS are codes; VALUE_MAPS renders the export names.
  - Flags are written as Excel booleans (export shows TRUE/FALSE).
  - Times are truncated to whole seconds (export drops microseconds).
  - All money/mass/count columns matched 100%.
Headers mapped to None are emitted blank (no known source; see UNRESOLVED).
Still open: "Consolidated" (not Ref Count>1 / First Ref — WAYREF/WAYREFTYPE
hunt queued) and "Scan Batch" (not PODBATCH; candidates IMAGEBATCH1 /
PAGEEVENTBATCH). Everything else the report builders read is verified.
"""

from __future__ import annotations

import argparse
import collections
import os
from datetime import date, time
from decimal import Decimal

import firebirdsql
from dotenv import load_dotenv
from openpyxl import Workbook

# --- DB -> export-header map, in exact manual-export column order (157 cols).
# Value = VIEW_WBANALYSE column, or ("calc", name) for computed, or None (blank).
# "# VERIFY" = unconfirmed guess, checked by research/revenue_extract_verify.py.
COLUMN_MAP: list[tuple[str, object]] = [
    ("Waybill", "WAYBILL"),
    ("Waybill Date", "WAYDATE"),
    ("Service", "SERVICE"),
    ("Customer", "CUSTNAME"),
    ("Account", "ACCNUM"),
    ("Invoice", "INVOICE"),
    ("Reference", "REFERENCE"),
    ("Shipper", "ORIGPERS"),
    ("Consignee", "DESTPERS"),
    ("Delivery Agent", "DELIVERYAGENT"),
    ("Orig Hub", "ORIGHUB"),
    ("Orig Place", "ORIGTOWN"),
    ("Dest Hub", "DESTHUB"),
    ("Dest Place", "DESTTOWN"),
    ("Pieces", "PIECES"),
    ("Actual Mass", "ACTKG"),
    ("Vol Mass", None),  # candidate: VOLCM x VOLRATE — confirm before mapping
    ("Chrg Mass", "CHARGEMASS"),
    ("Subtotal", "SUBTOTAL"),
    ("Fuel", "SURCHARGE6"),  # verified (VIEW_SURCHARGES + diff)
    ("Chainstore", "SURCHARGE7"),  # verified
    ("DC Chainstore", "SURCHARGE8"),  # verified
    ("Handling", "HANDLING"),
    ("Insurance Amount", "INSURANCE"),
    ("VAT", "VAT"),
    ("Total", "TOTAL"),
    ("Decl Value", "DECLAREDVALUE"),
    ("Insurance", "INSURANCEFLAG"),
    ("Insurance Type", "INSURANCEDESCRIPTION"),
    ("Waybill Cost Centre", "CCNAME"),  # verified — PP export crosses these two
    ("Orig Ring", "ORIGRING"),
    ("Dest Ring", "DESTRING"),
    ("Dest Ops Hub", "DESTOPSHUB"),
    ("Orig Ops Hub", "ORIGOPSHUB"),
    ("Branch", "BRANCHNAME"),
    ("Due Date", "DUEDATE"),
    ("Due Time", "DUETIME"),
    ("POD Recipient", "PODRECIPIENT"),
    ("POD Date", "PODDATE"),
    ("POD Time", "PODTIME"),
    ("Scan Batch", "IMAGEBATCH1"),  # verified 29 Jul (scanbatch dump):
    #   best candidate by far; residual both-populated conflicts (~6%) are
    #   re-scan drift (newer batch numbers DB-side). NOT PODBATCH.
    ("POD Capture Date", "PODCAPTUREDATE"),
    ("POD Capture Time", "PODCAPTURETIME"),  # truncated to seconds on write
    ("POD Discrepancy", "PODDISCREPANCY"),
    ("SLA Transit Days", None),
    ("Ref Count", "WAYREF_COUNT"),
    ("First Ref", "WAYREF_FIRST"),
    ("Notes", "NOTEPRESENT"),  # verified (Y/N → boolean)
    ("In Spec", None),
    ("Fail Type", "FAILTYPE_DESC"),
    ("Special Quote", "SPECQUOTEFLAG"),
    ("Special Instructions", "SPECINSTRUCTION"),
    ("Salesrep", "REP"),
    ("Booking Date", "BOOKDATE"),
    ("Start Time", "BOOKSTARTTIME"),
    ("End Time", "BOOKENDTIME"),
    ("Capture Date", "CAPTUREDATE"),
    ("Sameday", "SURCHARGE1"),  # verified (VIEW_SURCHARGES + diff)
    ("Tail - lift Truck", "SURCHARGE2"),  # verified
    ("Late / Early Collection", "SURCHARGE3"),  # verified
    ("Saturday / Sunday Morning", "SURCHARGE4"),  # verified
    ("Futile Trip", "SURCHARGE5"),  # verified
    ("Townships", "SURCHARGE9"),  # verified
    ("AWB", "AGENTWAYBILL"),
    ("Cust Group", "CUSTGROUP"),
    ("Customs Duties", "CUSTOMSDUTIES"),
    ("Customs VAT", "CUSTOMSVAT"),
    ("Exch Rate", "CURRATE"),
    ("Currency Subtotal", "CURRENCYSUBTOTAL"),
    ("Currency", "CURRENCY"),
    ("Customer Currency", "CUSTCURRENCY"),
    ("Non Dox Charge", "NONDOCS"),
    ("Doc Charge", "DOCS"),
    ("Special Surcharge", "SPECIALSURCH"),
    ("Non Dox", "NONDOXFLAG"),
    ("Sender Contact", "ORIGPERCONTACT"),
    ("Quote Date", "QUOTEDATE"),
    ("Consignee Contact", "DESTPERCONTACT"),
    ("Inhouse", "INHOUSENAME"),
    ("Customer Cost Centre", "COSTCNTRNAME"),  # verified — crossed, see above
    ("Basic Charge", "CARTAGE"),  # verified
    ("Outlying Charge", "OUTLY"),
    ("Custom Waybill", None),
    ("Mass Ratio", None),
    ("Rep", "REPNAME"),
    ("MinShip", "MINSHIPFLAG"),
    ("Original Waybill", "WAYBILLORIG"),
    ("Last Delivery Date", "LASTDELDATE"),
    ("Status", "STATUS"),
    ("Waybill Input Method", "INPUTMETHOD"),  # code → name via VALUE_MAPS
    ("Last Delivery Driver", "DELIVERYAGENT"),  # verified — export duplicates
    #   Delivery Agent here; the view's LASTDELDRIVER is not in the export
    ("Receipt", "RECEIPT"),
    ("Receipt User", "RECEIPT_USERNAME"),  # VERIFY: view RECEIPTUSER is mostly
    #   null; export shows names — joined via RECEIPT.USERCODE → VIEW_USERCODE
    ("PIF", "PIF"),
    ("Collection Agent", "COLLECTIONAGENT"),
    ("Customs Value", "CUSTOMSVALUE"),
    ("Customs Group", ("calc", "customs_group")),  # VERIFY: window showed
    #   constant 'Documents' while CUSTOMSGROUP was blank — default-fill
    ("Invoice Date", "INVDATE"),
    ("Handover Batch", None),  # candidate: PAGEEVENTBATCH / IMAGEBATCH1
    ("First Manifesting Agent", "FIRST_TT_AGENT"),
    ("VAT Type", "VATDESCRIPTION"),  # verified
    ("Early Del Time", "EARLYDELTIME"),
    ("Collection", "COLLECT"),
    ("Collection Date", "COLLECTIONDATE"),
    ("Collect Status", "COLSTATUS"),  # code → name via VALUE_MAPS
    ("Any Other Details", "PODDETAILS"),  # verified
    ("POD Image Present", "PODIMGPRESENT"),
    ("Del AWB", None),
    ("Col Agent", None),
    ("Actual Transit Days", None),
    ("Origperphone", "ORIGPERPHONE"),
    ("Destperphone", "DESTPERPHONE"),
    ("Orig Pcode", "ORIGPERPCODE"),
    ("Dest Pcode", "DESTPERPCODE"),
    ("Volcm", "VOLCM"),
    ("POD User", None),
    ("Last Delivery Failtype", "LAST_FAILTYPE"),
    ("POD Input", None),
    ("Orig Hub Type", None),
    ("Dest Hub Type", None),
    ("POD Debrief Status", None),
    ("Customer Sector", None),
    ("Last Manifest Failtype", None),  # ROUTING_FAILTYPE holds codes, not
    #   the export's descriptions — unmapped pending a better source
    ("Orig Zone", None),
    ("Dest Zone", None),
    ("Chrg Unit", "CHARGEUNIT"),
    ("Customs Value (ZAR)", None),
    ("Dest Area", "DESTAREANAME"),
    ("Orig Area", "ORIGAREANAME"),
    ("Transit Days Difference", None),
    ("Signature", None),
    ("Last Tripsheet", None),
    ("Customer Category", None),
    ("Responsible", None),
    ("POH", None),
    ("Dest Routecode", None),
    ("Orig Routecode", None),
    ("Total Surch.", "WB_TOTSURCHARGE"),  # VERIFY: sum(S1..9) fell short on
    #   ~0.5% of rows (extra WAYSURCH charges) — joined WAYBILL.TOTSURCHARGE
    ("Orig Ops Branch", None),
    ("Dest Ops Branch", None),
    ("Last Manifest", None),
    ("Receipt Amount", None),
    ("Credit Amount", None),
    ("Started Trading", None),
    ("Booking Contact", None),
    ("Avg R per kg", ("calc", "r_per_kg")),  # Subtotal / Chrg Mass
    ("First Arrival Date", None),
    ("Volrate", "VOLRATE"),
    ("First Arrival Time", None),
    ("Delivery Driver Wait Time (Mins)", None),
    ("Consolidated", ("calc", "consolidated")),  # DERIVED — no stored DB flag
    #   found (WAYBILL.*, WAYREF, merge tables all ruled out). PP's Analyze
    #   screen marks the zero-charged children of billing consolidations:
    #   Invoiced AND Subtotal=0 AND Service not in (NCH/SCH/N/C = no-charge
    #   services) AND Account != '000' (internal). Verified 99.989% on BOTH
    #   the WB and INV manual exports (8 residuals each: one-off manually
    #   zeroed waybills; zero revenue impact — all zero-subtotal rows).
    ("Credit Controller", None),  # likely a CUSTOMER-table join — pending
    ("Orig Pers Email", None),
    ("Dest Pers Email", None),
    ("Track Count", None),
    ("Converted From", None),
    ("Destpercell", None),
]

# Headers we cannot source yet, kept blank in the output. The report builders
# need none of these except "Consolidated" (billing-detail consolidations tab).
UNRESOLVED = [h for h, src in COLUMN_MAP if src is None]

# Select-list aliases that come from joins, not VIEW_WBANALYSE columns.
ALIAS_COLS = {"RECEIPT_USERNAME", "WB_TOTSURCHARGE"}
# CUSTOMSGROUP feeds the "Customs Group" calc but has no direct map entry.
DB_COLS = sorted(({src for _, src in COLUMN_MAP if isinstance(src, str)}
                  - ALIAS_COLS) | {"CUSTOMSGROUP"})

# Code -> display-name maps (from the 29 Jul per-column diff).
VALUE_MAPS = {
    "Waybill Input Method": {"": "Parcel Perfect", "0": "Parcel Perfect",
                             "1": "PPOnline", "2": "PPMobile"},
    "Collect Status": {"": "Unknown", "W": "Unknown", "N": "Unknown",
                       "V": "Unknown", "F": "Checked In",
                       "C": "Collected", "U": "Unassigned",
                       "A": "Assigned to Agent", "X": "Cancelled"},
}

# Export renders these as Excel TRUE/FALSE; the view holds 0/1 or Y/N.
# NB full-file diff: PIF and "POD Image Present" stay raw Y/N strings,
# "Collection" is the collection NUMBER, "POD Discrepancy" is raw FREE TEXT.
BOOL_HEADERS = {"Insurance", "Notes", "Special Quote", "Non Dox", "MinShip"}
_TRUTHY = {"1", "1.0", "Y", "T", "TRUE"}

# Columns summed in the totals row the manual export appends. Waybill and
# MinShip carry the row count; Avg R per kg is the weighted overall figure.
TOTAL_SUM_HEADERS = {
    "Pieces", "Actual Mass", "Chrg Mass", "Subtotal", "Fuel", "Chainstore",
    "DC Chainstore", "Handling", "Insurance Amount", "VAT", "Total",
    "Decl Value", "Sameday", "Tail - lift Truck", "Late / Early Collection",
    "Saturday / Sunday Morning", "Futile Trip", "Townships", "Customs Duties",
    "Customs VAT", "Currency Subtotal", "Non Dox Charge", "Doc Charge",
    "Special Surcharge", "Basic Charge", "Outlying Charge", "Volcm",
    "Chrg Unit",
}

# --- Credit notes (Phase 3) -------------------------------------------------
# CONFIRMED (discovery run, 29 Jul): the credits pool is the RECEIPT table —
# credits are negative RECEIPT numbers. RECTYPE distribution on negative
# receipts since Mar-24 matches the credits export's Type counts exactly:
#   N=5718 Credit Note, B=497 Bad Debt, X=249 Cancelled, J=1 Journal Credit.
# Reason <- NOTETYPE lookup table (descriptions match export verbatim).
# User Name / Credit Controller <- VIEW_USERCODE (USERCODE, NAME, EMAIL);
# Rep <- CUSTOMER.REP -> REP.NAME (Alex's join pattern in report_generation).
# Verified arithmetic: Subtotal = AMOUNT − VAT − CUSTOMSVAT − CUSTOMSDUTIES;
# Unallocated = AMOUNT + DISCOUNT − ALLOCATED (PP manual's discount rule).
# Export's Reference <-> r.REFERENCE (free text) and Comment <-> r.COMMENT
# (invoice-waybill refs) map directly — confirmed against DB sample.
# RECONCILED 29 Jul vs the manual credits export (357 common receipts since
# 1 Jun): every field 100% — account, customer, date, subtotal/amount
# arithmetic, type, reason, user, rep, credit controller, reference, comment,
# allocated/unallocated, cost centre, branch. Trial-only rows were credits
# captured after the export pull (drift). Capture Date/Time source unknown
# (no RECEIPT column; not consumed by any report builder — left blank).
# The dump includes ALL types — type-level exclusions happen in the builders.
RECTYPE_MAP = {"N": "Credit Note", "J": "Journal Credit",
               "B": "Bad Debt", "X": "Cancelled"}

CREDITS_HEADERS = [
    "Receipt", "Account", "Customer Name", "Date", "Subtotal", "Vat",
    "Customs Duties", "Customs Vat", "Amount", "Discount", "Reference",
    "Cost Centre", "Type", "Allocated", "Unallocated", "AIF", "Export",
    "User Name", "Comment", "Rep", "Reason", "Bank", "Capture Date",
    "Capture Time", "Branch", "VAT Type", "Cash", "Credit Controller",
]

CREDITS_SQL = """
SELECT r.RECEIPT, r.ACCNUM, c.CUSTNAME, r.RECDATE, r.AMOUNT, r.DISCOUNT,
       r.REFERENCE, r.RECTYPE, nt.DESCRIPTION AS REASON, r.ALLOCATED,
       r.COMMENT, r.AIF, vu.NAME AS USERNAME, r.EXPORT, r.VAT, r.VATTYPE,
       b.NAME AS BRANCHNAME, r.BANK, r.CUSTOMSVAT, r.CUSTOMSDUTIES,
       rep.NAME AS REPNAME, cn.NAME AS COSTCNTRNAME,
       cc.NAME AS CREDCONTROLLER
FROM RECEIPT r
LEFT JOIN CUSTOMER c ON c.ACCNUM = r.ACCNUM
LEFT JOIN NOTETYPE nt ON nt.NOTETYPE = r.NOTETYPE
LEFT JOIN VIEW_USERCODE vu ON vu.USERCODE = r.USERCODE
LEFT JOIN REP rep ON rep.REP = c.REP
LEFT JOIN VIEW_USERCODE cc ON cc.USERCODE = c.CREDCONT
LEFT JOIN BRANCH b ON b.BRANCH = r.BRANCH
LEFT JOIN COSTCNTR cn ON cn.COSTCNTR = c.COSTCNTR
WHERE r.RECDATE >= DATE '{start}'
  AND r.RECEIPT < 0;  -- credits appear as negative receipt numbers
"""


def write_credits_xlsx(path: str, db_cols: list[str], rows: list[tuple]) -> None:
    ix = {c: i for i, c in enumerate(db_cols)}

    def g(r, c):
        return _clean(r[ix[c]])

    wb = Workbook(write_only=True)
    ws = wb.create_sheet()
    ws.append(CREDITS_HEADERS)
    tot = collections.defaultdict(float)  # totals row, like the staff export
    for r in rows:
        amount = float(g(r, "AMOUNT") or 0)
        vat = float(g(r, "VAT") or 0)
        cvat = float(g(r, "CUSTOMSVAT") or 0)
        cdut = float(g(r, "CUSTOMSDUTIES") or 0)
        disc = float(g(r, "DISCOUNT") or 0)
        alloc = float(g(r, "ALLOCATED") or 0)
        for k, v in (("Subtotal", amount - vat - cvat - cdut), ("Vat", vat),
                     ("Customs Duties", cdut), ("Customs Vat", cvat),
                     ("Amount", amount), ("Discount", disc),
                     ("Allocated", alloc),
                     ("Unallocated", amount + disc - alloc)):
            tot[k] += v
        ws.append([
            g(r, "RECEIPT"), g(r, "ACCNUM"), g(r, "CUSTNAME"), g(r, "RECDATE"),
            round(amount - vat - cvat - cdut, 2), vat, cdut, cvat, amount,
            disc, g(r, "REFERENCE"), g(r, "COSTCNTRNAME"),
            RECTYPE_MAP.get(str(g(r, "RECTYPE") or "").strip(), ""),
            alloc, round(amount + disc - alloc, 2) + 0.0, g(r, "AIF"), g(r, "EXPORT"),
            g(r, "USERNAME"), g(r, "COMMENT"), g(r, "REPNAME"), g(r, "REASON"),
            g(r, "BANK"), None, None, g(r, "BRANCHNAME"), g(r, "VATTYPE"),
            False, g(r, "CREDCONTROLLER"),
        ])
    # Totals row, mirroring the staff export's final row: Receipt = row count,
    # sums for the eight money columns, everything else blank.
    ws.append([len(rows) if c == "Receipt" else round(tot[c], 2) if c in tot
               else None for c in CREDITS_HEADERS])
    wb.save(path)


def connect() -> firebirdsql.Connection:
    load_dotenv()
    return firebirdsql.connect(
        host=os.getenv("DB_HOST"),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        role=os.getenv("DB_ROLE"),
        charset="latin1",
        use_unicode=True,
    )


def fy_start(today: date | None = None) -> date:
    """Most recent 1 March (financial year runs March-February)."""
    today = today or date.today()
    year = today.year if today.month >= 3 else today.year - 1
    return date(year, 3, 1)


def fy_label(start: date) -> str:
    return f"March{start.year % 100} - Feb{(start.year + 1) % 100}"


def extraction_sql(basis: str, start: date) -> str:
    """The manual-export-equivalent query. basis: 'wb' or 'inv'."""
    date_col = {"wb": "WAYDATE", "inv": "INVDATE"}[basis]
    cols = ", ".join(f"wba.{c}" for c in DB_COLS)
    return f"""
        SELECT {cols},
               ru.NAME AS RECEIPT_USERNAME,
               wb2.TOTSURCHARGE AS WB_TOTSURCHARGE
        FROM VIEW_WBANALYSE wba
        LEFT JOIN RECEIPT rc ON rc.RECEIPT = wba.RECEIPT
        LEFT JOIN VIEW_USERCODE ru ON ru.USERCODE = rc.USERCODE
        LEFT JOIN WAYBILL wb2 ON wb2.WAYBILL = wba.WAYBILL
        WHERE wba.{date_col} >= DATE '{start.isoformat()}'
          AND wba.WAYBILL NOT LIKE '%~%'
          AND wba.STATUS <> 'Cancelled';
    """


def fetch(conn, sql: str) -> tuple[list[str], list[tuple]]:
    with conn.cursor() as cur:
        cur.execute(sql)
        cols = [d[0].strip() for d in cur.description]
        return cols, cur.fetchall()


def _clean(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, time) and v.microsecond:
        return v.replace(microsecond=0)  # export truncates to whole seconds
    if isinstance(v, str):
        # The DB connection decodes as latin1, but PP data is Windows-1252 —
        # transcode so e.g. en-dashes in customer names match the manual export.
        try:
            v = v.encode("latin1").decode("cp1252")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
        return v.strip()
    return v


def _as_bool(v) -> bool:
    return str(v).strip().upper() in _TRUTHY


NO_CHARGE_SERVICES = {"NCH", "SCH", "N/C"}
INTERNAL_ACCOUNTS = {"000"}


def _round2(x: float) -> float:
    """Plain 2dp rounding. Half-up was tried and made the R/kg diff WORSE
    (655 vs 353 one-cent diffs) — the manual export divides PP's float32
    values, so the last cent is unreproducible noise either way. Display-only
    column; every builder computes its own R/kg."""
    return round(x, 2)


def write_xlsx(path: str, db_cols: list[str], rows: list[tuple]) -> None:
    ix = {c: i for i, c in enumerate(db_cols)}
    sub_i, kg_i = ix["SUBTOTAL"], ix["CHARGEMASS"]
    cg_i = ix["CUSTOMSGROUP"]
    st_i, svc_i, acc_i = ix["STATUS"], ix["SERVICE"], ix["ACCNUM"]
    headers = [h for h, _ in COLUMN_MAP]
    tot = collections.defaultdict(float)

    wb = Workbook(write_only=True)
    ws = wb.create_sheet()
    ws.append(headers)
    for r in rows:
        out = []
        for hdr, src in COLUMN_MAP:
            if src is None:
                out.append(None)
            elif isinstance(src, tuple):
                if src[1] == "r_per_kg":
                    kg = float(r[kg_i] or 0)
                    out.append(_round2(float(r[sub_i] or 0) / kg) if kg else None)
                elif src[1] == "customs_group":
                    v = _clean(r[cg_i])
                    out.append(v if v else "Documents")
                elif src[1] == "consolidated":
                    out.append(
                        "Yes"
                        if (str(r[st_i]).strip() == "Invoiced"
                            and float(r[sub_i] or 0) == 0
                            and str(r[svc_i]).strip() not in NO_CHARGE_SERVICES
                            and str(r[acc_i]).strip() not in INTERNAL_ACCOUNTS)
                        else "No"
                    )
            elif hdr in BOOL_HEADERS:
                out.append(_as_bool(r[ix[src]]))
            elif hdr in VALUE_MAPS:
                raw = str(_clean(r[ix[src]]) or "")
                raw = raw.removesuffix(".0")
                out.append(VALUE_MAPS[hdr].get(raw, raw))
            else:
                out.append(_clean(r[ix[src]]))
        for hdr, v in zip(headers, out):
            if hdr in TOTAL_SUM_HEADERS and isinstance(v, (int, float)):
                tot[hdr] += v
        ws.append(out)
    # Totals row, mirroring the manual export's final row.
    kg_total = tot.get("Chrg Mass", 0)
    totals = []
    for hdr in headers:
        if hdr in ("Waybill", "MinShip"):
            totals.append(len(rows))
        elif hdr == "Avg R per kg":
            totals.append(_round2(tot.get("Subtotal", 0) / kg_total) if kg_total else None)
        elif hdr in tot:
            totals.append(round(tot[hdr], 2))
        else:
            totals.append(None)
    ws.append(totals)
    wb.save(path)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", default=".", help="Where the export files land")
    ap.add_argument("--fy-start", default=None,
                    help="FY start date YYYY-MM-DD (default: most recent 1 March)")
    ap.add_argument("--basis", choices=["wb", "inv", "credits", "all"],
                    default="all")
    args = ap.parse_args()

    start = date.fromisoformat(args.fy_start) if args.fy_start else fy_start()
    label = fy_label(start)
    conn = connect()

    try:
        if args.basis in ("wb", "all"):
            cols, rows = fetch(conn, extraction_sql("wb", start))
            path = os.path.join(args.out_dir, f"WB Date - {label}..xlsx")
            write_xlsx(path, cols, rows)
            print(f"WB basis: {len(rows)} rows -> {path}")
        if args.basis in ("inv", "all"):
            cols, rows = fetch(conn, extraction_sql("inv", start))
            path = os.path.join(args.out_dir, f"INV Date - {label}..xlsx")
            write_xlsx(path, cols, rows)
            print(f"INV basis: {len(rows)} rows -> {path}")
        if args.basis in ("credits", "all"):
            cred_start = date(start.year - 2, 3, 1)  # credits span 3 FYs
            cred_label = f"March{cred_start.year % 100} - Feb{(start.year + 1) % 100}"
            cols, rows = fetch(conn, CREDITS_SQL.format(start=cred_start.isoformat()))
            path = os.path.join(args.out_dir, f"Credits - {cred_label}.xlsx")
            write_credits_xlsx(path, cols, rows)
            print(f"Credits: {len(rows)} rows -> {path} "
                  "(NB .xlsx — staff export is .xls; readers to be adapted)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
