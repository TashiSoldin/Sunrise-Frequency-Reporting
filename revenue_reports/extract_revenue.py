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

Column mapping status: entries in COLUMN_MAP marked VERIFY are best-guess
mappings pending the per-column diff from research/revenue_extract_verify.py.
Headers mapped to None are emitted blank (no known source in VIEW_WBANALYSE;
see UNRESOLVED below). Every column consumed by the report builders is mapped,
except "Consolidated" (source unknown — under discovery).
"""

from __future__ import annotations

import argparse
import os
from datetime import date
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
    ("Fuel", "SURCHARGE1"),  # VERIFY
    ("Chainstore", "SURCHARGE2"),  # VERIFY
    ("DC Chainstore", "SURCHARGE3"),  # VERIFY
    ("Handling", "HANDLING"),
    ("Insurance Amount", "INSURANCE"),
    ("VAT", "VAT"),
    ("Total", "TOTAL"),
    ("Decl Value", "DECLAREDVALUE"),
    ("Insurance", "INSURANCEFLAG"),
    ("Insurance Type", "INSURANCEDESCRIPTION"),
    ("Waybill Cost Centre", "COSTCNTRNAME"),
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
    ("Scan Batch", "PODBATCH"),
    ("POD Capture Date", "PODCAPTUREDATE"),
    ("POD Capture Time", "PODCAPTURETIME"),
    ("POD Discrepancy", "PODDISCREPANCY"),
    ("SLA Transit Days", None),
    ("Ref Count", "WAYREF_COUNT"),
    ("First Ref", "WAYREF_FIRST"),
    ("Notes", "NOTEPRESENT"),  # VERIFY
    ("In Spec", None),
    ("Fail Type", "FAILTYPE_DESC"),
    ("Special Quote", "SPECQUOTEFLAG"),
    ("Special Instructions", "SPECINSTRUCTION"),
    ("Salesrep", "REP"),
    ("Booking Date", "BOOKDATE"),
    ("Start Time", "BOOKSTARTTIME"),
    ("End Time", "BOOKENDTIME"),
    ("Capture Date", "CAPTUREDATE"),
    ("Sameday", "SURCHARGE4"),  # VERIFY
    ("Tail - lift Truck", "SURCHARGE5"),  # VERIFY
    ("Late / Early Collection", "SURCHARGE6"),  # VERIFY
    ("Saturday / Sunday Morning", "SURCHARGE7"),  # VERIFY
    ("Futile Trip", "SURCHARGE8"),  # VERIFY
    ("Townships", "SURCHARGE9"),  # VERIFY
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
    ("Customer Cost Centre", "CCNAME"),  # VERIFY
    ("Basic Charge", "CARTAGE"),  # VERIFY
    ("Outlying Charge", "OUTLY"),
    ("Custom Waybill", None),
    ("Mass Ratio", None),
    ("Rep", "REPNAME"),
    ("MinShip", "MINSHIPFLAG"),
    ("Original Waybill", "WAYBILLORIG"),
    ("Last Delivery Date", "LASTDELDATE"),
    ("Status", "STATUS"),
    ("Waybill Input Method", "INPUTMETHOD"),
    ("Last Delivery Driver", "LASTDELDRIVER"),
    ("Receipt", "RECEIPT"),
    ("Receipt User", "RECEIPTUSER"),
    ("PIF", "PIF"),
    ("Collection Agent", "COLLECTIONAGENT"),
    ("Customs Value", "CUSTOMSVALUE"),
    ("Customs Group", "CUSTOMSGROUP"),
    ("Invoice Date", "INVDATE"),
    ("Handover Batch", None),  # candidate: PAGEEVENTBATCH / IMAGEBATCH1
    ("First Manifesting Agent", "FIRST_TT_AGENT"),
    ("VAT Type", "VATDESCRIPTION"),  # VERIFY (alt: VATTYPE)
    ("Early Del Time", "EARLYDELTIME"),
    ("Collection", "COLLECT"),
    ("Collection Date", "COLLECTIONDATE"),
    ("Collect Status", "COLSTATUS"),  # VERIFY (alt: COLLECTIONSTATUS)
    ("Any Other Details", "PODDETAILS"),  # VERIFY
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
    ("Last Manifest Failtype", "ROUTING_FAILTYPE"),  # VERIFY
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
    ("Total Surch.", ("calc", "total_surch")),  # VERIFY: sum(SURCHARGE1..9)
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
    ("Consolidated", None),  # source unknown — %CONSOL% column hunt pending.
    #                          Builders consume this; must be resolved before
    #                          the manual export is retired.
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

DB_COLS = sorted({src for _, src in COLUMN_MAP if isinstance(src, str)})
SURCHARGE_COLS = [f"SURCHARGE{i}" for i in range(1, 10)]

# --- Credit notes (Phase 3) -------------------------------------------------
# The credits export is receipts-side data: its first column is a (negative)
# Receipt number, and the PP Accounts manual processes credit notes via
# Process -> Credit Notes "similar to the receipts". The smoke-test scan
# (%CREDIT%/%CNOTE%/%JOURNAL%/%INVOICE%/%DEBTOR%) found no credits table —
# research/revenue_extract_verify.py hunts %RECEIPT% relations next.
# This query is a TEMPLATE: table/column names pending that discovery.
# The dump must include ALL types (Credit Note / Journal Credit / Bad Debt /
# Cancelled) — type-level exclusions happen in the report builders.
CREDITS_SQL_TEMPLATE = """
SELECT r.RECEIPT, r.ACCNUM, r.CUSTNAME, r.RDATE, r.SUBTOTAL, r.VAT,
       r.CUSTOMSDUTIES, r.CUSTOMSVAT, r.AMOUNT, r.DISCOUNT, r.REFERENCE,
       r.COSTCENTRE, r.RTYPE, r.ALLOCATED, r.UNALLOCATED, r.AIF, r.EXPORT,
       r.USERNAME, r.COMMENT, r.REP, r.REASON, r.BANK, r.CAPTUREDATE,
       r.CAPTURETIME, r.BRANCH, r.VATTYPE, r.CASH
FROM {table} r
WHERE r.RDATE >= DATE '{start}'
  AND r.RECEIPT < 0;  -- credits appear as negative receipt numbers
"""


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
    cols = ", ".join(DB_COLS)
    return f"""
        SELECT {cols}
        FROM VIEW_WBANALYSE
        WHERE {date_col} >= DATE '{start.isoformat()}'
          AND WAYBILL NOT LIKE '%~%'
          AND STATUS <> 'Cancelled';
    """


def fetch(conn, sql: str) -> tuple[list[str], list[tuple]]:
    with conn.cursor() as cur:
        cur.execute(sql)
        cols = [d[0].strip() for d in cur.description]
        return cols, cur.fetchall()


def _clean(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, str):
        return v.strip()
    return v


def write_xlsx(path: str, db_cols: list[str], rows: list[tuple]) -> None:
    ix = {c: i for i, c in enumerate(db_cols)}
    s_ix = [ix[c] for c in SURCHARGE_COLS]
    sub_i, kg_i = ix["SUBTOTAL"], ix["CHARGEMASS"]

    wb = Workbook(write_only=True)
    ws = wb.create_sheet()
    ws.append([h for h, _ in COLUMN_MAP])
    for r in rows:
        out = []
        for _, src in COLUMN_MAP:
            if src is None:
                out.append(None)
            elif isinstance(src, tuple):
                if src[1] == "total_surch":
                    out.append(sum(float(r[i] or 0) for i in s_ix))
                elif src[1] == "r_per_kg":
                    kg = float(r[kg_i] or 0)
                    out.append(round(float(r[sub_i] or 0) / kg, 2) if kg else None)
            else:
                out.append(_clean(r[ix[src]]))
        ws.append(out)
    wb.save(path)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", default=".", help="Where the export files land")
    ap.add_argument("--fy-start", default=None,
                    help="FY start date YYYY-MM-DD (default: most recent 1 March)")
    ap.add_argument("--basis", choices=["wb", "inv", "both"], default="both")
    args = ap.parse_args()

    start = date.fromisoformat(args.fy_start) if args.fy_start else fy_start()
    label = fy_label(start)
    conn = connect()

    try:
        if args.basis in ("wb", "both"):
            cols, rows = fetch(conn, extraction_sql("wb", start))
            path = os.path.join(args.out_dir, f"WB Date - {label}..xlsx")
            write_xlsx(path, cols, rows)
            print(f"WB basis: {len(rows)} rows -> {path}")
        if args.basis in ("inv", "both"):
            cols, rows = fetch(conn, extraction_sql("inv", start))
            path = os.path.join(args.out_dir, f"INV Date - {label}..xlsx")
            write_xlsx(path, cols, rows)
            print(f"INV basis: {len(rows)} rows -> {path}")
        # Credits: blocked on receipts-table discovery — see CREDITS_SQL_TEMPLATE.
        print("Credits extraction pending table discovery "
              "(run research/revenue_extract_verify.py).")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
