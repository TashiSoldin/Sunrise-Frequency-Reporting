"""Open-ended query path — quote line 4's fence (Day 5).

Anything the named tools do not cover, answered from the database directly.
The 3h bought the fence, not per-question logic; the fence is:

- SELECT-only, enforced here before Firebird (sql_guard, plus the read-only
  transaction and the grant-less role behind it);
- a table allowlist — every relation a query touches must be on it, and every
  entry is justified from the 6 Aug schema survey (Database Reference folder);
- a per-table column deny list (QT-000007 line 2, 20 Oct 2026) — password,
  banking, contact and infrastructure columns are refused when named
  anywhere in the SQL (a WHERE on a password column is an oracle), and a
  projection star (`SELECT *`, `alias.*`) is refused on any statement that
  touches a table with withheld columns (Fable F1: a star under a column
  alias list or a UNION carries them out unnamed); the schema resource omits
  them, and a cursor-name drop sits behind the gate as defence in depth;
- a window rule on the two big relations (QT-000007 line 4, 21 Oct 2026) —
  ROUTING and VIEW_EVENTSCANS are queryable only with a waybill / manifest
  key or a bounded literal date range on every occurrence, widths set from
  measured plans (WINDOWED); the time cap cannot stop Firebird server-side,
  so this predicate check is the real load guard for them;
- row and time caps — a cap that is HIT refuses the answer rather than
  truncating silently, the same rule every revenue fetcher applies;
- date plausibility flags on every date column in the result — Parcel Perfect
  carries 1899-12-30 placeholders and mis-keyed years as a matter of course,
  and an aggregate over them is the project's recorded date-column failure
  mode (day_guards.plausible_window owns the arithmetic);
- the honest boundary: an open answer reads the raw data and does NOT carry
  the export rules or the verification of the named tools. The same raw data
  once produced R3.49m of "unbilled" freight that was nothing of the sort.
  Questions in named-tool territory get that caveat attached, and the named
  tool recommended.

Every call is audit-logged (question, SQL, rows, duration, outcome) by the
server layer — never response bodies.
"""

import datetime as _dt
import json
import re
import socket
import sys
import time
from functools import lru_cache
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "revenue_reports"))

from day_guards import PP_NULL_DATE, classify_dates, plausible_window

from mcp_server.db import run_select
from mcp_server.sql_guard import (
    GuardError,
    _strip_literals_and_comments,
    assert_select_only,
)

__all__ = [
    "ALLOWLIST",
    "DENIED_COLUMNS",
    "WINDOWED",
    "check_open_query",
    "run_open_query",
    "schema_context",
]

# --- caps ---------------------------------------------------------------------
# An open answer is a read of raw rows, not an extract feeding a report — 500
# rows is presentable; more means the question wants an aggregate or a filter.
ROW_CAP = 500
# Socket-level cap on how long we WAIT. Honest limitation: Firebird may keep
# executing an aborted aggregate server-side after the socket closes — the cap
# bounds the answer, not the production load (the quote's deleted-sentence
# lesson). Firebird 3.0.13 has no SET STATEMENT TIMEOUT, so a true DB-side cap
# is impossible on this engine.
#
# The allowlist keeps the 100M+-row EVENT-family tables unreachable, but it
# does NOT bound load on its own: a self-cross-join of an allowlisted table
# (AGENTDRIVER is 723k rows, MANIFEST 308k) or an unbounded aggregate over
# VIEW_WBANALYSE (3.1M) runs the DB hot for far longer than 15s server-side
# while the client has already given up — and the row cap sees only the one
# COUNT row it returns. This residual availability risk is flagged to Larry
# (18 Aug Day 5 review); it is inherent to an open SQL path on FB3, not a bug
# the fence can close without a fragile cartesian-detector.
TIMEOUT_S = 15

# --- the allowlist --------------------------------------------------------------
# Relation -> why it is on the list. Justifications cite the 6 Aug 2026 schema
# survey (row counts, columns, readability all verified there). Nothing is
# reachable that is not in this dict.
ALLOWLIST: dict[str, str] = {
    # The sanctioned views — PP's own reporting surfaces, verified in
    # production use by Alex's reports and the revenue extraction.
    "VIEW_WBANALYSE": (
        "Waybill analysis view, 134 cols, one row per waybill — the surface "
        "Alex's frequency/POD reports and the revenue extraction query. The "
        "sanctioned way to read waybills; the raw WAYBILL table stays off. "
        "The consignor/consignee phone columns are withheld; ORIGPERCONTACT, "
        "DESTPERCONTACT and SPECINSTRUCTION are the person names and "
        "instructions typed on the waybill and can carry contact detail the "
        "column guard cannot strip."
    ),
    "VIEW_SURCHARGES": "Surcharge names view (2 cols) — decodes surcharge codes.",
    "VIEW_USERCODE": (
        "User codes view (10 cols) — who captured/actioned records. The raw "
        "USERCODE table is refused to this login; the view is the granted path."
    ),
    "VIEW_CUSTOMERS": (
        "Customer view (30 cols) — the surface the revenue tools' customer "
        "matching reads; account codes and names without CUSTOMER's 164 raw "
        "columns of terms and rates."
    ),
    # Billing documents.
    "RECEIPT": (
        "Receipts and credit notes (77,522 rows, 21 cols) — negative receipt "
        "numbers are credit notes; the credits export reads this table."
    ),
    "INVOICE": (
        "Invoice headers (516,143 rows, 50 cols) — what was invoiced, when, "
        "to which account. Survey-verified readable; billing questions that "
        "stray past the named tools carry the honest-boundary caveat."
    ),
    # Parties.
    "CUSTOMER": (
        "Customer master (1,959 rows, 164 cols) — accounts, names, terms, "
        "rate and surcharge defaults. Phone/fax/email, banking and the "
        "inter-company login columns are withheld (DENIED_COLUMNS). NOTE and "
        "SPECINSTRUCTION are free text typed by staff and can carry contact "
        "detail the column guard cannot strip."
    ),
    "CONTACT": (
        "Customer contact people (4,591 rows, 18 cols) — names, positions, "
        "cost centres. Phone/cell/email and the web-login password columns "
        "are withheld (DENIED_COLUMNS)."
    ),
    "AGENT": (
        "Agents/vehicles (1,220 rows, 70 cols) — carries VEHICLE, REGNO, "
        "CAPACITY, VOLCAPACITY, VEHICLEID, USEDRIVER, GPSMODE: the readable "
        "half of Larry's fleet questions (the VEHICLE table itself is refused "
        "to this login and is only a 4-column type lookup). Checked live "
        "18 Aug 2026: those vehicle columns are essentially UNPOPULATED — "
        "REGNO and VEHICLE are null on every row, CAPACITY set on one. Say "
        "what the data shows; do not promise fleet answers off this table."
    ),
    # Operational tables, survey-verified — the 6 Aug finding that settled
    # Larry's utilisation ask: the figure is computed from these, not read.
    "MANIFEST": (
        "Trips (307,955 rows, 67 cols) — AGENT, DRIVER, ROUTE, STARTKM/ENDKM, "
        "PIECES, CHARGEMASS, ACTKG, VOLCM, DEPARTTIME, CLOSED, ALLDELIVERED. "
        "The utilisation raw material named in the 6 Aug survey."
    ),
    "AGENTDRIVER": (
        "Driver-per-trip link (723,357 rows, 8 cols) — joins MANIFEST activity "
        "to drivers; in the survey's vehicles/fleet group."
    ),
    "ACTROUTE": "Actual line-haul routes (1,004 rows, 11 cols).",
    "ACTLEG": "Actual line-haul route legs (1,288 rows, 8 cols).",
    "SERVICE": "Service types lookup (138 rows, 16 cols).",
    "SERVICEGROUP": "Service group lookup (31 rows, 4 cols).",
    # Small reference lookups a readable answer needs to join through.
    "HUB": "Depot/hub lookup (226 rows, 16 cols) — decodes hub codes.",
    "PLACE": "Place lookup (8,748 rows, 21 cols) — towns/suburbs.",
    "AREA": "Area lookup (715 rows, 4 cols).",
    "BRANCH": "Branch lookup (16 rows, 26 cols).",
    "HOLIDAY": "Public holidays (50 rows, 2 cols) — the trading-calendar edge.",
    # QT-000007 line 1 (Reuven, approved 19 Oct 2026): customer rates, agent
    # rates, waybill notes and collections. Row counts are the 6 Aug 2026
    # survey; every one SELECT-granted to the BI login in
    # schema_privileges_2026-08-06.csv and confirmed with a live SELECT FIRST 1
    # on 20 Oct 2026.
    "RATE": (
        "Customer rate cards (680,552 rows, 26 cols) — one row per account x "
        "rate number x service x origin/destination hub (or postcode): the "
        "handling, docs, non-docs and per-kg surcharge parameters a waybill "
        "is priced from. Unbounded reads hit the row cap — filter by ACCNUM "
        "and RATENUM."
    ),
    "MASSRATE": (
        "Mass-break rate lines (774,355 rows, 7 cols) — the TOKG / CHARGE "
        "steps of each RATE row (RATE is the key). Filter through RATE by "
        "account; an unbounded read hits the row cap."
    ),
    "ITEMRATE": (
        "Per-item rate lines (8,116 rows, 10 cols) — charges per default item "
        "(DEFITEM) for a RATE row."
    ),
    "RATENUM": (
        "Rate-card versions (6,656 rows, 4 cols) — which RATENUM applies to an "
        "account from which STARTDATE; the key for 'what rate was in force'."
    ),
    "SURCHRATE": (
        "Surcharge rate rules (477,914 rows, 20 cols) — per surcharge code, "
        "account or customer group, service and lane: amount, percentage "
        "floor and ceiling. Filter by ACCNUM/CUSTGROUP; unbounded reads hit "
        "the row cap."
    ),
    "SURCHNUM": (
        "Surcharge rate versions (61,234 rows, 4 cols) — SURCHNUM in force "
        "per account from STARTDATE."
    ),
    "AGRATE": (
        "Agent (carrier) cost rates (33,382 rows, 21 cols) — what Sunrise pays "
        "an agent per lane/service: handling, non-docs, per-kg surcharge, "
        "capacity. Joins MANIFEST.AGRATE and AGENT."
    ),
    "AGRATENUM": (
        "Agent rate versions (3,384 rows, 3 cols) — AGRATENUM in force per "
        "agent from STARTDATE."
    ),
    "NOTE": (
        "Waybill notes (117,916 rows, 27 cols) — the free-text notes staff "
        "attach to a waybill (MEMO blob, MEMOSTRING first 80 chars), typed by "
        "NOTETYPE, with due/close dates and claim references. The text is "
        "operational (short deliveries, damages, delivery instructions, "
        "customer-service correspondence) and occasionally contains contact "
        "detail typed in by hand — a column guard cannot strip that; relay "
        "notes as the operational record they are, not as a contact source."
    ),
    "COLLECT": (
        "Collection bookings (880,487 rows, 68 cols) — who booked a "
        "collection, where, when, assigned agent/driver, status, pieces and "
        "mass. Phone/cell/email columns are withheld (DENIED_COLUMNS). NOTES "
        "and NOTESINT are free text and CONTACT / BOOKINGCONTACT are person "
        "names typed at booking — all four can carry contact detail the "
        "column guard cannot strip. Filter by COLLECTIONDATE or ACCNUM — "
        "unbounded reads hit the row cap."
    ),
    # QT-000007 lines 3-4 (21 Oct 2026): the two big relations, WINDOWED —
    # see that dict for the rule and the measurements behind it.
    "ROUTING": (
        "Manifest contents (6,018,355 rows at the 6 Aug 2026 survey, 6.22M on "
        "21 Oct; 67 cols) — one row per waybill per leg: WAYBILL, LEG, MBRANCH, "
        "MTYPE (M line haul / R local delivery / C collection), MANIFEST, AGENT, "
        "AGENTDATE, hubs, status. The full waybill-to-manifest history (the 18 Aug "
        "line-haul probe recovered 124/124 of a trip's waybills through it). "
        "WINDOWED: every query needs WAYBILL (= or IN, up to 100) or MANIFEST "
        "(= or IN, up to 20; add MBRANCH and MTYPE to pin one trip) or an "
        "AGENTDATE range of at most 31 days — set from the live plans in "
        "research/db_query_interface/routing_eventscans_plans_2026-10-21.md "
        "(keyed reads 2-25 ms; 31 days = 48,680 rows in 168 ms; the unbounded "
        "count is 7.9 s). BOOKDATE is indexed but populated only on local-delivery "
        "rows, so it is a filter, not a window. Masses on ROUTING are unreliable "
        "(branch-1 rows carry CHARGEMASS 0 / VOLMASS NULL) — take mass and "
        "revenue from VIEW_WBANALYSE joined on WAYBILL."
    ),
    "VIEW_EVENTSCANS": (
        "Scan history view (29 cols) over the 113M-row EVENT family: a UNION of "
        "EVENT-TRACK-WAYBILL (parcel-level tracking numbers) and EVENT-WAYBILL, "
        "with the event description (NAME), hub, user, agent, POD and waybill "
        "header columns looked up per row. One row per scan: WAYBILL, TRACKNO, "
        "EVENTDATE, EVENTTIME, NAME, HUB, MANIFEST, plus ACCNUM / WAYDATE / "
        "hubs from the waybill. WINDOWED: every query needs WAYBILL or TRACKNO "
        "(= or IN, up to 100) or MANIFEST (= or IN, up to 20) or an EVENTDATE "
        "range of at most 3 days — set from the live plans in research/"
        "db_query_interface/routing_eventscans_plans_2026-10-21.md (a waybill's "
        "scans in 8 ms; 1/3/7 days of EVENTDATE = 1.2/3.5/6.9 s warm, ~50k "
        "scans a day, so a date window is for aggregates or date + hub / name "
        "questions). WAYDATE, ACCNUM, NAME, HUB, USERNAME and AGENTNAME are "
        "lookup-side filters, not windows: on their own the planner scans TRACK "
        "and WAYBILL. RECIPIENT and USERNAME are people's names (POD recipient, "
        "the staff member who scanned) and are served, as names are elsewhere. "
        "Scans by type over a date range are the event-counts tool Reuven asked "
        "for on 20 Oct 2026, quoted separately; EVENT itself stays off."
    ),
}

# --- column deny list (QT-000007 line 2, 20 Oct 2026) ---------------------------
# Relation -> column names never served on the open path. Built from the
# 6 Aug 2026 column survey (schema_columns_2026-08-06.csv) by name match
# (PASS|PWD|BANK|ACCNO|TEL|PHONE|CELL|FAX|EMAIL|MOBILE, and since the 20 Oct
# re-review HASH|KEY|SECRET|TOKEN — that sweep found only CONTACT.HASHED,
# CONTACT.SECRETKEY and INVOICE.INVHASH across the 30 tables) as the floor, then
# read column by column — the edge cases below were decided from live values
# on 20 Oct 2026, never from the name alone. Enforced three ways: a denied
# name appearing as an identifier ANYWHERE in the SQL refuses the query (a
# WHERE or ORDER BY on a password column is an oracle, so hiding the column
# is not enough); a projection star (SELECT *, alias.*) anywhere in a
# statement that touches a table with a non-empty set here refuses it too
# (Fable review F1, 20 Oct 2026 — `SELECT * FROM (SELECT * FROM CONTACT) t
# (A1, …)` and a UNION named by a WHERE 1=0 first branch carried every
# withheld value out under other headers; COUNT(*) is still fine); and,
# behind both, a denied column that somehow arrives in a result is dropped
# by cursor-description name with a note. Matching is on the bare column name across
# every table the statement references — a coincidental same-named column on
# another table in the same query is refused too, and the message says so.
#
# Every allowlisted table has an entry, even an empty one, so "not covered"
# cannot be mistaken for "nothing sensitive" (pinned by a test).
#
# What stays: person NAMES (CONTACT.NAME, CUSTOMER.CONTACT, COLLECT.CONTACT,
# BOOKINGCONTACT, INVCONTACT, ORIGPERCONTACT, PODRECIPIENT) — waybill_status
# already serves recipient names and the quote's words were password,
# banking, phone, cell, email; street ADDRESS lines — they are the freight
# data; WEBSITE — public; VAT/company registration numbers — printed on every
# invoice; notification FLAGS whose names contain EMAIL/FAX/SMS (see
# CUSTOMER); free text (NOTE.MEMO, COLLECT.NOTES) — see the NOTE
# justification.
DENIED_COLUMNS: dict[str, frozenset[str]] = {
    "CUSTOMER": frozenset(
        {
            # contact detail
            "PHONE",
            "AFTHOURSNO",  # after-hours phone number — missed by the name
            #   regex, caught by reading the list (VARCHAR(30) next to PHONE)
            "CELL",
            "FAX",
            "EMAIL",
            "EMAILSMS",  # VARCHAR(40) email-to-SMS gateway address: an address
            #   column by type (empty on every row live, but the shape is an
            #   address, so withheld)
            # banking. CUSTOMER.BANK is a SMALLINT 1–8 bank code (live: 1,700
            # NULL, the rest spread over 8 values) — on its own it names a
            # bank, but beside BANKACCNO it is the customer's banking detail
            # and Reuven's ask was "banking" — both withheld.
            "BANK",
            "BANKACCNO",
            # credentials for the inter-company (IC) link: user name,
            # password and the endpoint they log in to. ICPASS is populated on
            # 43 customers live (CHAR(20), plain text).
            "ICUSER",
            "ICPASS",
            "ICDNSPATH",
        }
    ),
    # Decided NOT to withhold on CUSTOMER, from live values 20 Oct 2026:
    # EMAILINVIMAGE, PODEMAIL, PODFAX, PODSINGLEFAX, PODSINGLEEMAIL,
    # PODSINGLESMS, EVENTEMAIL, EVENTORIGEMAIL, EVENTDESTEMAIL, EVENTORIGSMS,
    # EVENTDESTSMS, SMSDELNOTIFY, DISABLEINVIMAGE, INVMAILMODE — every one a
    # SMALLINT (NULL / 0 / 1 / 2 live): notification preference flags, not
    # addresses. The PODFAX pair (PODFAX, PODSINGLEFAX) are 0/NULL on every
    # row. SMSDELMSG is the SMS template text, not a number.
    "CONTACT": frozenset(
        {
            "CELL",
            "PHONE",
            "EMAIL",
            "RECOVERYEMAIL",
            # the web-portal login: password (populated on all 4,766 rows
            # live; HASHED=1 on 1,319 of them, i.e. most are stored in clear),
            # the MFA secret, and the two flags that describe how the
            # password is stored / whether MFA is on — password metadata is
            # withheld with the password.
            "WEBPASSWORD",
            "SECRETKEY",
            "HASHED",
            "MFA",
        }
    ),
    # CONTACT.PODEMAIL is a SMALLINT flag (NULL on every row live) — stays.
    "AGENT": frozenset(
        {
            "PHONE",
            "AFTERHOURS",  # after-hours phone (VARCHAR(30)) — name regex
            #   misses it; same decision as CUSTOMER.AFTHOURSNO
            "FAX",
            "CELL",
            "EMAIL",
            # ACCNO: live values are 5–6 char alphanumerics (AG…, KS…, 30…),
            # populated on 361 of 1,227 agents, zero of them matching a
            # CUSTOMER.ACCNUM — it reads as the agent's creditor/ledger
            # account reference, not a bank account. Withheld anyway: the
            # name says account number, nothing operational needs it, and
            # the cost of withholding is nil. Revisit if Reuven asks for it.
            "ACCNO",
            # inter-company link credentials, as on CUSTOMER (ICPASS is empty
            # on every agent live — withheld on shape, not on content).
            "ICUSER",
            "ICPASS",
            "ICDNSPATH",
        }
    ),
    "COLLECT": frozenset({"PHONE", "PHONE2", "CELL", "BOOKINGEMAIL"}),
    # COLLECT.EVENTEMAIL is a SMALLINT flag (NULL/0/1 live) — stays.
    "INVOICE": frozenset(
        {
            "INVPHONE",
            "INVPHONE2",
            "INVCELL",
            # the stored invoice PDFs: binary blobs that carry the printed
            # banking details and the customer's full address block — not
            # queryable data, and 500 of them is not an answer.
            "PDFCOPY",
            "PDFORIG",
            # INVHASH (VARCHAR(64), Fable re-review N1): a per-invoice
            # SHA-256 — 3,821 of 3,968 invoices since 1 Sep 2026 populated,
            # all distinct, all 64 chars. Not a credential and not reversible
            # to one; withheld because nothing queries it and the deny list is
            # where the next scan looks (HASH|KEY|SECRET|TOKEN is now part of
            # the floor pattern).
            "INVHASH",
        }
    ),
    # RECEIPT.BANK: SMALLINT 1–8 (live: NULL 50,925 · 3 26,635 · 7 1,355 …)
    # — the code of the bank the receipt was paid INTO, i.e. which of
    # Sunrise's own accounts, not a customer's banking detail and not an
    # account number. Stays queryable: it is how receipts split by bank.
    "RECEIPT": frozenset(),
    "VIEW_CUSTOMERS": frozenset({"PHONE", "AFTERHOURSPHONE", "CELL", "FAX", "EMAIL"}),
    "VIEW_USERCODE": frozenset({"CELL", "EMAIL"}),
    # STAFFID stays: short codes/initials live (3–6 chars), not ID numbers.
    "VIEW_WBANALYSE": frozenset({"ORIGPERPHONE", "DESTPERPHONE"}),
    # Fable review F2 (20 Oct 2026): the branch table also carries the
    # installation's plumbing — internal IPs, the database file path, the
    # replication server and the RTM path. Infrastructure detail, not freight
    # data; withheld. The survey scan for IP|PATH|SERVER|HOST|PORT|URL|DSN|
    # CONNECT across all 30 tables found nothing else of that kind: EXPORT /
    # WEBEXPORT / MOBEXPORT / REPORT / PORTALMODE are flags, EXPORTERNUM /
    # IMPORTERNUM are customs registration numbers, NEXTIMPORT is a counter,
    # MOBRECEIPT is a layout blob, and ICDNSPATH is already withheld above.
    "BRANCH": frozenset({"EMAIL", "IP", "DBPATH", "RDBSERVER", "RTMPATH"}),
    # Nothing sensitive by name or by reading the column list:
    "VIEW_SURCHARGES": frozenset(),
    "MANIFEST": frozenset(),
    "AGENTDRIVER": frozenset(),
    "ACTROUTE": frozenset(),
    "ACTLEG": frozenset(),
    "SERVICE": frozenset(),
    "SERVICEGROUP": frozenset(),
    "HUB": frozenset(),
    "PLACE": frozenset(),
    "AREA": frozenset(),
    "HOLIDAY": frozenset(),
    # The rate tables carry no contact or banking columns (survey, re-read
    # 20 Oct): keys, lanes, charge parameters and dates only.
    "RATE": frozenset(),
    "MASSRATE": frozenset(),
    "ITEMRATE": frozenset(),
    "RATENUM": frozenset(),
    "SURCHRATE": frozenset(),
    "SURCHNUM": frozenset(),
    "AGRATE": frozenset(),
    "AGRATENUM": frozenset(),
    # NOTE: no name-matched columns; MEMO/MEMOSTRING are free text — see the
    # ALLOWLIST justification. CONTACT here is an INTEGER key, not a name.
    "NOTE": frozenset(),
    # QT-000007 line 4 (21 Oct 2026). ROUTING has no contact or banking
    # column by name (floor pattern re-run on schema_columns_2026-08-06.csv:
    # only TOTPAID, a money column, matched on 'TOTP'). DELOTP VARCHAR(10) is
    # the delivery one-time PIN the recipient gives the driver to confirm a
    # delivery — credential-shaped (a PIN that proves presence), nothing
    # operational on the open path needs it, and the cost of withholding is
    # nil, so it goes in on the same footing as INVHASH. Live 21 Oct: see the
    # Decisions entry for how many rows carry one.
    "ROUTING": frozenset({"DELOTP"}),
    # VIEW_EVENTSCANS: no contact, banking or credential column by name or by
    # reading the 29 (survey CSV re-read 21 Oct). RECIPIENT (POD recipient)
    # and USERNAME (the staff member who scanned) are person NAMES and stay,
    # per the Chunk 2 decision that names are served.
    "VIEW_EVENTSCANS": frozenset(),
}

# One sentence for refusal messages and the schema resource.
_WITHHELD_WHY = (
    "contact (phone/cell/fax/email), banking and password/credential columns "
    "are not served on the open path (QT-000007, Reuven 16 Oct 2026)"
)


def _denied_for(tables) -> dict[str, list[str]]:
    """Denied column name -> the referenced tables it is denied on."""
    out: dict[str, list[str]] = {}
    for t in tables:
        for c in DENIED_COLUMNS.get(t, ()):
            out.setdefault(c, []).append(t)
    return out


# Known relations that are deliberately NOT queryable, with the reason said
# outright — a tailored refusal beats "not on the allowlist" for the tables
# people will actually ask about.
DENIED: dict[str, str] = {
    "EVENT": (
        "EVENT is deliberately off the allowlist: 113,123,238 rows on the live "
        "freight system. A waybill's full scan history is on VIEW_EVENTSCANS "
        "(keyed by WAYBILL, TRACKNO or MANIFEST, or an EVENTDATE window of at "
        "most 3 days); scans by event type over a date range are the "
        "event-counts tool Reuven asked for on 20 Oct 2026 — a separate quote, "
        "measured on 21 Oct, not an open-path read."
    ),
    "WAYBILL": (
        "the raw WAYBILL table (3.1M rows, 146 cols) is off the allowlist — "
        "VIEW_WBANALYSE is the sanctioned waybill surface; query that instead."
    ),
    "TRACK": (
        "TRACK (14.1M rows, parcel tracking numbers) is off the allowlist — "
        "VIEW_EVENTSCANS resolves parcel-level TRACKNOs to their waybill."
    ),
    "PAGEEVENT": "PAGEEVENT (12.8M rows) is off the allowlist — event-family scale.",
    "SCANLOG": "SCANLOG (3.8M rows) is off the allowlist — event-family scale.",
    "WAYEVENT": "WAYEVENT (573k rows) is off the allowlist — event-family scale.",
    "CONTENTS": "CONTENTS (7.3M rows) is off the allowlist.",
    "WAYREF": "WAYREF (5.3M rows) is off the allowlist.",
    "GPSLOG": "GPSLOG (4.6M rows) is off the allowlist.",
    "WAYEDIT": "WAYEDIT (20.2M rows) is an edit log and off the allowlist.",
    "MFEDIT": "MFEDIT (3.1M rows) is an edit log and off the allowlist.",
    "CUSTEDIT": "CUSTEDIT (839k rows) is an edit log and off the allowlist.",
    "COLLEDIT": "COLLEDIT (3.2M rows) is an edit log and off the allowlist.",
    "AUDIT": "AUDIT (1.6M rows) is an audit log and off the allowlist.",
    "POD": (
        "the raw POD table (2.0M rows) is off the allowlist — VIEW_WBANALYSE "
        "carries the POD fields, and waybill_status answers them per waybill."
    ),
}

# Named-tool territory: results read from these carry the honest-boundary
# caveat and a pointer at the verified tool. VIEW_WBANALYSE only triggers it
# when the SQL touches billing columns — tracking/ops reads of the same view
# are not revenue questions.
_REVENUE_TABLES = {"RECEIPT", "INVOICE", "VIEW_SURCHARGES"}
_REVENUE_COLUMNS = re.compile(
    r"\b(SUBTOTAL|TOTAL|VAT|INVNUM|INVOICEDATE|REVENUE|CHARGEAMT)\b", re.IGNORECASE
)

HONEST_BOUNDARY = (
    "HONEST BOUNDARY: this is a correct read of the RAW data — it does not "
    "carry the export rules (tilde/Cancelled exclusions, invoice-date basis, "
    "net-of-credits) or the verification behind the named revenue tools, so "
    "its figures need not match a report's. The same raw data once produced "
    "R3.49m of 'unbilled' freight that was nothing of the sort. For revenue, "
    "sales, unbilled or credit questions, prefer sales_report / "
    "revenue_summary / unbilled_report / credit_notes."
)


# --- table extraction -----------------------------------------------------------

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")
_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*|[(),]")

# Keywords that end a FROM list or cannot be a table name in table position.
_STOP = {
    "WHERE",
    "GROUP",
    "HAVING",
    "ORDER",
    "UNION",
    "ROWS",
    "FETCH",
    "OFFSET",
    "PLAN",
    "FOR",
    "INTO",
    "ON",
    "USING",
    "JOIN",
    "INNER",
    "LEFT",
    "RIGHT",
    "FULL",
    "CROSS",
    "NATURAL",
    "OUTER",
    "WITH",
    "SELECT",
    "AS",
    "FIRST",
    "SKIP",
    "DISTINCT",
}

_PLAN_WORD = re.compile(r"\bPLAN\b", re.IGNORECASE)
_WITH_WORD = re.compile(r"\bWITH\b", re.IGNORECASE)
_FIRST_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")


def _check_characters(sql: str) -> None:
    """Character whitelist, applied to the raw SQL before anything else
    (Fable fourth review, Q1, 22 Oct 2026): printable ASCII 0x20-0x7E plus
    LF and TAB only. A bare carriage return ends a -- comment for Firebird
    but not for the guard's strippers, so everything after it was invisible
    to every gate; the same class covers FF, VT, NUL, the Unicode line and
    paragraph separators, zero-width characters, NBSP and smart quotes."""
    for pos, ch in enumerate(sql):
        o = ord(ch)
        if 0x20 <= o <= 0x7E or ch in "\n\t":
            continue
        raise GuardError(
            f"character U+{o:04X} at position {pos} is not accepted on the open path "
            "— only printable ASCII, line feed and tab are; remove it (a bare carriage "
            "return, a non-breaking space or a smart quote are the usual causes)"
        )


def _check_no_comments(sql: str) -> None:
    """Comments are refused outright (Q1): every stripper in the guard had its
    own idea of where a comment ends, and the audit log since 1 Oct (2,012
    calls) shows nobody sends one. Outside a plain '...' literal, -- or /*
    refuses; the strippers stay as defence in depth but are no longer
    load-bearing."""
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch == "'":
            j = i + 1
            while j < n and sql[j] != "'":
                j += 1
            i = j + 1
        elif sql[i : i + 2] in ("--", "/*"):
            raise GuardError("comments are not accepted on the open path — remove them")
        else:
            i += 1


_STARTING_WITH = re.compile(
    r"(?<![A-Za-z0-9_$])STARTING\s+WITH(?![A-Za-z0-9_$])", re.IGNORECASE
)
_WITH_LOCK = re.compile(r"\bWITH\s+LOCK\b", re.IGNORECASE)
_MAX_SQL_CHARS = (
    4000  # the audit log's truncation point; the longest logged call is 3,071
)
_RELATIONS = frozenset(
    json.loads(
        (Path(__file__).resolve().parent / "relations_2026-08-06.json").read_text()
    )
)


def _check_introduced_literals(sql: str) -> None:
    """Refuse Firebird's introduced literals — q'{…}', Q'…', x'41', X'…',
    _utf8'…' — before any stripper runs (Fable third review, T3, 22 Oct
    2026). Neither sql_guard's literal stripper nor the window tokenizer
    models them, so a quote inside one desyncs the stripper and can hide an
    OR, a forbidden keyword, a denied column or a table. The rule: outside a
    plain '…' literal or a comment, an identifier character immediately
    followed by a quote refuses. Plain literals with doubled quotes
    ('O''Reilly') and DATE '…' with a space are untouched."""
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch == "'":
            j = i + 1
            while j < n and sql[j] != "'":
                j += 1
            i = j + 1  # a doubled quote simply opens the next literal
        elif ch == "-" and sql[i : i + 2] == "--":
            j = sql.find("\n", i)
            i = n if j == -1 else j
        elif ch == "/" and sql[i : i + 2] == "/*":
            j = sql.find("*/", i + 2)
            i = n if j == -1 else j + 2
        else:
            if (ch.isalnum() or ch in "_$") and i + 1 < n and sql[i + 1] == "'":
                raise GuardError(
                    "introduced string literals (q'…', x'…', _charset'…') are not "
                    "accepted on the open path — write string literals with plain "
                    "single quotes"
                )
            i += 1


def _cte_spans(cleaned: str) -> dict[str, tuple[int, int]]:
    """CTE name -> (body start, body end) character span of its AS ( … )."""
    spans = {}
    for m in _CTE_NAME.finditer(cleaned):
        name = m.group(1).upper()
        open_at = m.end() - 1  # the '(' the regex ends on
        depth, j = 0, open_at
        while j < len(cleaned):
            if cleaned[j] == "(":
                depth += 1
            elif cleaned[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        spans[name] = (open_at, j)
    return spans


def _check_cte_names(spans: dict) -> None:
    """A CTE may not be named after a relation (fifth review, F2): inside its
    own body a non-recursive CTE cannot see itself, so `WITH CONTACT AS
    (SELECT * FROM CONTACT) …` reads the BASE table there while the guard
    had excluded the name everywhere — every gate skipped it."""
    for name in spans:
        if name in _RELATIONS:
            raise GuardError(
                f"CTE names may not shadow a table ({name} is a relation in this "
                "database) — give the common table expression another name"
            )


def _check_with_position(cleaned: str) -> None:
    """WITH is accepted only as the very first word of the statement (Fable
    third review, T2): a subquery that opens with WITH — EXISTS (WITH q AS
    (…) SELECT 1 FROM EVENT), a scalar (WITH … SELECT FIRST 1 WEBPASSWORD
    FROM CONTACT) — was invisible to the FROM scanner, so every table inside
    it escaped the allowlist, the column deny list and the star ban."""
    # Firebird's STARTING WITH operator is one token (Q2): fold it away
    # before looking for WITH, keeping offsets stable.
    folded = _STARTING_WITH.sub(
        lambda m: "STARTING_" + "W" * (len(m.group(0)) - 9), cleaned
    )
    first = _FIRST_WORD.search(folded)
    first_at = first.start() if first and first.group(0).upper() == "WITH" else -1
    for m in _WITH_WORD.finditer(folded):
        if m.start() == first_at:
            continue
        if True:
            raise GuardError(
                "WITH is accepted only at the start of the statement — write common "
                "table expressions at the top of the statement only"
            )


_CTE_NAME = re.compile(
    r"(?:\bWITH\b|,)\s*(?:RECURSIVE\s+)?([A-Za-z_][A-Za-z0-9_$]*)"
    r"(?:\s*\([^)]*\))?\s+AS\s*\(",
    re.IGNORECASE,
)


# Tokens for the FROM-list scan: identifiers, numbers, parens and commas as
# single tokens, any other run of punctuation as one token (literals and
# comments are already blanked, so they never appear).
_FT = re.compile(
    r"(?i:(?<![A-Za-z0-9_$])STARTING\s+WITH(?![A-Za-z0-9_$]))"  # one operator token (Q2)
    r"|[A-Za-z_][A-Za-z0-9_$]*|\d+(?:\.\d+)?|[(),]|[^\sA-Za-z0-9_$(),]+"
)
_JOIN_WORDS = {"JOIN", "INNER", "LEFT", "RIGHT", "FULL", "CROSS", "NATURAL", "OUTER"}
# Keywords that end a FROM list at its own paren depth.
# Each of these was prepared live as `SELECT 1 FROM HOLIDAY <word>` on
# 22 Oct 2026 and REJECTED by Firebird 3.0.13, so none can be an alias.
# EXCEPT and INTERSECT prepare as aliases (Firebird 3 has no such set
# operators) and are NOT here (fifth review, F1): `FROM HOLIDAY EXCEPT, EVENT e`
# is a cross join with EVENT under an alias named EXCEPT.
_FROM_END = {
    "WHERE",
    "GROUP",
    "HAVING",
    "ORDER",
    "UNION",
    "ROWS",
    "FETCH",
    "OFFSET",
    "PLAN",
    "FOR",
    "INTO",
    "WITH",
}
# Functions whose argument list carries a FROM keyword that is not a table list.
_FROM_FUNCTIONS = {"SUBSTRING", "EXTRACT", "TRIM", "POSITION", "OVERLAY"}
_FROM_LIST_PROBLEM = (
    "the FROM list could not be read to its end ({what}) — the open path refuses "
    "a statement whose table list it cannot be sure of (fail closed); write a "
    "plain FROM / JOIN … ON list of base tables, views and (SELECT …) derived tables"
)


def _scan_from_lists(
    cleaned: str, with_positions: bool = False
) -> tuple[list, str | None]:
    """Every identifier in table position across EVERY FROM list in the
    statement, in order of appearance, plus a problem message if any FROM
    list could not be read to its end.

    Hot-fix 21 Oct 2026 (Fable re-review R1): the Day 5 scanner stopped at
    the first ON or closing paren, so a comma-listed table after `JOIN … ON …`
    or after a derived table was never seen by the allowlist, the column deny
    list or the star ban. Each FROM is now parsed through to its terminator:
    table [alias] { , table | <join words> table [alias] [ON … | USING …] }.
    After ON / USING the condition is skipped at the list's own depth up to
    the next join word, comma or terminator. Anything in table position the
    scanner does not understand — a parenthesised join, a procedure call, a
    stray token, a dangling comma — is reported as a problem, and the caller
    refuses: the fence never falls through with a partial table set."""
    matches = list(_FT.finditer(cleaned))
    toks = [m.group(0) for m in matches]
    char_at = [m.start() for m in matches]
    n = len(toks)
    found: list[tuple[int, str]] = []  # (token position, name)
    problem: str | None = None
    # innermost enclosing '(' per token, and whether that paren opens a SELECT
    # (a subquery) rather than a function / expression — a FROM inside
    # SUBSTRING(x FROM 1 FOR 3) or EXTRACT(YEAR FROM d) is not a table list.
    encl = [-1] * n
    stack: list[int] = []
    for k, tk in enumerate(toks):
        encl[k] = stack[-1] if stack else -1
        if tk == "(":
            stack.append(k)
        elif tk == ")" and stack:
            stack.pop()
    sub_paren = {
        k
        for k, tk in enumerate(toks)
        if tk == "(" and k + 1 < n and toks[k + 1].upper() in ("SELECT", "WITH")
    }

    def is_join_word(i):
        return (
            i < n
            and _IDENT.fullmatch(toks[i]) is not None
            and toks[i].upper() in _JOIN_WORDS
            # LEFT( / RIGHT( are string functions; JOIN ( is a join to a derived table
            and not (
                toks[i].upper() in ("LEFT", "RIGHT")
                and i + 1 < n
                and toks[i + 1] == "("
            )
        )

    def skip_paren(i):
        """i at '(' -> index just past its matching ')' (or n)."""
        depth = 0
        while i < n:
            if toks[i] == "(":
                depth += 1
            elif toks[i] == ")":
                depth -= 1
                if depth == 0:
                    return i + 1
            i += 1
        return n

    def parse_list(i, top):
        """i just after a FROM; top = the list is not inside any paren, so a
        ')' cannot legitimately end it. Returns (names, problem)."""
        names = []
        expect_table = True
        derived = False
        while i < n:
            tok = toks[i]
            u = tok.upper()
            if expect_table:
                derived = False
                if tok == "(":
                    if (
                        i + 1 < n
                        and _IDENT.fullmatch(toks[i + 1])
                        and toks[i + 1].upper() in ("SELECT", "WITH")
                    ):
                        i = skip_paren(
                            i
                        )  # derived table; its own FROM is scanned separately
                        derived = True
                    else:
                        return names, "a parenthesised join or a bracketed FROM item"
                elif _IDENT.fullmatch(tok) and u not in _STOP and u not in _JOIN_WORDS:
                    names.append((i, u))
                    i += 1
                    if i < n and toks[i] == "(":
                        # SOME_PROC(args): not a base relation. The name is
                        # still reported so the allowlist refuses it by name;
                        # the problem makes the refusal certain either way.
                        return names, f"{u}(…) in table position (a procedure call)"
                else:
                    return names, f"'{tok}' where a table name was expected"
                # optional alias
                if i < n and _IDENT.fullmatch(toks[i]) and toks[i].upper() == "AS":
                    if i + 1 < n and _IDENT.fullmatch(toks[i + 1]):
                        i += 2
                    else:
                        return names, "AS without an alias"
                elif (
                    i < n
                    and _IDENT.fullmatch(toks[i])
                    and toks[i].upper() not in _STOP
                    and toks[i].upper() not in _JOIN_WORDS
                ):
                    i += 1
                # a derived table may name its columns: (SELECT …) t (A1, A2)
                if derived and i < n and toks[i] == "(":
                    i = skip_paren(i)
                expect_table = False
                continue
            # after a table reference
            if tok == ",":
                expect_table = True
                i += 1
                continue
            if is_join_word(i):
                while is_join_word(i):
                    i += 1
                expect_table = True
                continue
            if _IDENT.fullmatch(tok) and u in ("ON", "USING"):
                i += 1
                # skip the condition at this depth
                while i < n:
                    t2 = toks[i]
                    if t2 == "(":
                        i = skip_paren(i)
                        continue
                    if t2 == ")" or t2 == ",":
                        break
                    if _IDENT.fullmatch(t2) and (
                        t2.upper() in _FROM_END or is_join_word(i)
                    ):
                        break
                    i += 1
                continue
            if tok == ")":
                return names, ("a ')' with no open paren" if top else None)
            if _IDENT.fullmatch(tok) and u in _FROM_END:
                return names, None
            return names, f"'{tok}' after a table reference"
        if expect_table:
            return names, "a FROM list that ends after a comma or JOIN"
        return names, None

    i = 0
    while i < n:
        if _IDENT.fullmatch(toks[i]) and toks[i].upper() == "FROM":
            if encl[i] != -1 and encl[i] not in sub_paren:
                opener = toks[encl[i] - 1].upper() if encl[i] >= 1 else ""
                if opener in _FROM_FUNCTIONS:
                    i += 1  # SUBSTRING(x FROM 1 FOR 3), EXTRACT(YEAR FROM d) …
                    continue
                if problem is None:
                    problem = _FROM_LIST_PROBLEM.format(
                        what="a FROM inside parentheses that open neither a subquery nor a function"
                    )
                i += 1
                continue
            names, prob = parse_list(i + 1, encl[i] == -1)
            found.extend(names)
            if prob and problem is None:
                problem = _FROM_LIST_PROBLEM.format(what=prob)
        i += 1
    found.sort()
    if with_positions:
        return [(char_at[i], name) for i, name in found], problem
    return [name for _, name in found], problem


def _referenced_tables(cleaned: str) -> list[str]:
    """Every table-position identifier in the statement; raises if a FROM
    list could not be read to its end (see _scan_from_lists)."""
    names, problem = _scan_from_lists(cleaned)
    if problem:
        raise GuardError(problem)
    return names


def _check_denied_columns(cleaned: str, tables: list[str]) -> None:
    """Refuse if any column denied on any referenced table appears as an
    identifier anywhere in the cleaned SQL — select list, expression, alias,
    WHERE, HAVING, ORDER BY, GROUP BY, subquery. String literals and comments
    are already blanked, so a denied NAME inside a literal is data, not a
    reference. Matching is on the bare name: `c.EMAIL`, `EMAIL`, `UPPER(EMAIL)`
    and `x AS EMAIL` all tokenise to the identifier EMAIL."""
    denied = _denied_for(tables)
    if not denied:
        return
    idents = {m.group(0).upper() for m in _IDENT.finditer(cleaned)}
    hits = sorted(idents & set(denied))
    if not hits:
        return
    parts = []
    for col in hits:
        on = ", ".join(sorted(denied[col]))
        # Over-refusal is reported, never silent: name the OTHER referenced
        # tables that carry a column of the same name and are not denied it
        # (RECEIPT.BANK beside CUSTOMER.BANK is the live example).
        same_name_elsewhere = [
            t for t in tables if t not in denied[col] and col in _columns_of(t)
        ]
        note = ""
        if same_name_elsewhere:
            note = (
                " — matched by name across every table in this statement, so "
                f"a same-named column on {', '.join(same_name_elsewhere)} is "
                "refused here too; query that table without "
                f"{on} in the statement"
            )
        parts.append(f"{col} (withheld on {on}){note}")
    raise GuardError(
        f"the query names a withheld column: {'; '.join(parts)}. "
        f"{_WITHHELD_WHY}. Naming one anywhere — select list, expression, "
        "alias, WHERE, ORDER BY or subquery — is refused, not just hidden, "
        "because a filter on it would leak the value."
    )


# Tokens for the star scan: identifiers, numbers, the star itself and the
# punctuation that decides what a star means.
_STAR_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*|\d+(?:\.\d+)?|\*|[(),.+\-]")
# A '(' preceded by one of these is a grouping paren, not a function call —
# so `( * )` after them is not COUNT(*).
_NOT_A_FUNCTION = _STOP | {"AND", "OR", "NOT", "IN", "EXISTS", "BETWEEN", "LIKE"}
_OPERAND_START = re.compile(r"[A-Za-z_0-9(+\-]")


def _has_projection_star(cleaned: str) -> bool:
    """True if any `*` or `alias.*` in the statement is a PROJECTION star —
    in a select list anywhere (outer query, derived table, CTE body, UNION
    branch, scalar subquery). `COUNT(*)` projects nothing and `a * b` is
    arithmetic; both are left alone.

    Fable review F1 (20 Oct 2026): projecting by output NAME was defeated by
    `SELECT * FROM (SELECT * FROM CONTACT) t (A1, …)` and by a UNION whose
    names come from a `WHERE 1=0` first branch. The star is the only way a
    withheld column reaches the result without being named, so the fix is to
    refuse the star, not to chase the shapes it can hide in."""
    toks = _STAR_TOKEN.findall(cleaned)
    for i, tok in enumerate(toks):
        if tok != "*":
            continue
        prev = toks[i - 1].upper() if i else ""
        prev2 = toks[i - 2].upper() if i >= 2 else ""
        nxt = toks[i + 1] if i + 1 < len(toks) else ""
        # COUNT(*) and friends: '(' straight after a function name.
        if (
            prev == "("
            and _IDENT.fullmatch(prev2 or "")
            and prev2 not in _NOT_A_FUNCTION
        ):
            continue
        # SELECT *, SELECT DISTINCT *, `, *`, `alias.*`
        if prev in ("SELECT", "DISTINCT", "ALL", ",", "."):
            return True
        # SELECT FIRST 5 * / SELECT FIRST (5) * / SKIP n * — a star that is
        # not followed by an operand is not a multiplication.
        if not nxt or not _OPERAND_START.match(nxt) or nxt.upper() == "FROM":
            return True
    return False


def _check_star_projection(cleaned: str, tables: list[str]) -> None:
    """When any referenced table carries withheld columns, refuse every
    projection star in the statement (Fable F1). Tables with an empty deny
    set keep their `*`; the cursor-name drop in run_open_query stays behind
    this as defence in depth."""
    guarded = sorted(t for t in tables if DENIED_COLUMNS.get(t))
    if not guarded or not _has_projection_star(cleaned):
        return
    raise GuardError(
        "SELECT * / alias.* is refused when the statement touches a table "
        f"with withheld columns ({', '.join(guarded)}) — a star would carry "
        "them into the result under whatever names the query gives them. "
        "List the columns explicitly; describe_schema('"
        f"{guarded[0]}') lists the ones served. COUNT(*) is fine. In EXISTS "
        "and IN subqueries write SELECT 1, not SELECT *. "
        f"{_WITHHELD_WHY}."
    )


# --- windowed relations (QT-000007 line 4, 21 Oct 2026) ------------------------
# ROUTING (6.2M rows) and VIEW_EVENTSCANS (a UNION over the 113M-row EVENT
# family with eight lookups per row) are on the allowlist only with a KEY or a
# WINDOW on every query. The 15 s client cap cannot stop Firebird 3 server-side,
# so this predicate check is the real load guard. The rule rests on live plans
# and timings measured 21 Oct 2026 (research/db_query_interface/
# routing_eventscans_plans_2026-10-21.md) and was signed by Akha the same day:
#
#   ROUTING          key  WAYBILL = / IN (<= 100 literals) — PK (WAYBILL, LEG), 2 ms;
#                         MANIFEST = / IN (<= 20) — RO_MANIFEST, ~25 ms a trip;
#                         MBRANCH + MTYPE optional (the note says they pin one trip);
#                    window AGENTDATE, <= 31 days — RO_AGNTDATEAGENT, 48,680 rows /
#                         168 ms cold at 31 d; the unbounded COUNT is 7.9 s.
#                    filters only: BOOKDATE (indexed, but populated on 1,178 of
#                         19,856 local-delivery rows in Sept 2026 and on no line-haul
#                         or collection row — a window on it answers 2.6% of the
#                         data), AGENT, ORIGHUB/DESTHUB, MTYPE, STATUS.
#   VIEW_EVENTSCANS  key  WAYBILL / TRACKNO = / IN (<= 100) — pushed into both union
#                         branches (W PK -> TRACK PK -> EV_TRACKDATETIME), 5-8 ms;
#                         MANIFEST = / IN (<= 20) — EV_MANIFEST, 1,456 rows / 40 ms;
#                    window EVENTDATE, <= 3 days — EV_EVENTDATE then the lookups:
#                         1/2/3/7 days = 1.2/2.5/3.5/6.9 s warm, 5.7/7.1/7.9/14.5 s
#                         cold (~50k events a day); 3 days is the widest under
#                         ~5 s warm with its cold time inside the cap.
#                    filters only: WAYDATE, ACCNUM, NAME, HUB, USERNAME, AGENTNAME —
#                         on their own each plans a NATURAL scan of TRACK (14M) and
#                         WAYBILL (3.1M) with an EVENT probe per row (not executed).
#
# Predicate rules: literal values only (no subquery, parameter or CURRENT_DATE
# arithmetic — their width cannot be computed here); on the windowed table's
# OWN alias (ROUTING.WAYBILL = x does not window VIEW_EVENTSCANS in a join, and
# a bare column in a multi-table query is refused as unqualified); in WHERE or
# a JOIN ON clause (HAVING and the select list run after the scan); not negated;
# not inside an OR (an OR widens the read — alternatives go in IN (...)). A
# range is inclusive: BETWEEN a AND b = (b - a) + 1 days; >= a AND < b = b - a.
# Every OCCURRENCE of a windowed table needs its own key or window — a window
# inside a CTE does not cover an outer unwindowed read, and a self-join needs
# both sides. The check lives after the allowlist, identifier and star gates
# and is driven by this dict (the suite proves emptying it lets an unwindowed
# statement through — Fable F3's lesson).
WINDOWED: dict[str, dict] = {
    "ROUTING": {
        "keys": {"WAYBILL": 100, "MANIFEST": 20},  # key column -> max IN-list literals
        "date": "AGENTDATE",
        "max_days": 31,
        "filters_only": ("BOOKDATE", "AGENT", "ORIGHUB", "DESTHUB", "MTYPE", "STATUS"),
        # columns that qualify a MANIFEST key without being keys themselves
        "pins": ("MBRANCH", "MTYPE"),
        "filter_why": {
            "BOOKDATE": (
                "indexed but populated only on local-delivery rows — 1,178 of "
                "19,856 R rows in Sept 2026, none on line-haul or collection legs "
                "— so a BOOKDATE window would silently answer about 2.6% of the data"
            )
        },
        "rule": (
            "every ROUTING query must carry a key (WAYBILL = '…' or IN (up to 100 "
            "literals); MANIFEST = n or IN (up to 20)) or a window (AGENTDATE "
            "between two literal dates, at most 31 days) on the ROUTING alias, in "
            "WHERE or JOIN ON and outside any OR; BOOKDATE, AGENT, hub, MTYPE and "
            "STATUS are filters only; joined to VIEW_WBANALYSE, MANIFEST or "
            "AGENTDRIVER, that relation's own alias must carry its key too "
            "(WAYBILL / MANIFEST / AGENT = or IN, or a WAYDATE range of at most "
            "31 days on the view) (QT-000007 line 4, measured 21 Oct 2026)"
        ),
    },
    "VIEW_EVENTSCANS": {
        "keys": {"WAYBILL": 100, "TRACKNO": 100, "MANIFEST": 20},
        "date": "EVENTDATE",
        "max_days": 3,
        "filters_only": ("WAYDATE", "ACCNUM", "NAME", "HUB", "USERNAME", "AGENTNAME"),
        "pins": (),
        "filter_why": {
            "WAYDATE": (
                "it belongs to the waybill lookup, not the scan: on its own the "
                "planner walks all of TRACK and WAYBILL and probes EVENT per row"
            ),
            "ACCNUM": "it belongs to the waybill lookup — the planner cannot push it into EVENT",
            "NAME": (
                "it is the event description from the SCANRULE lookup — scans by "
                "type over a date range are the event-counts tool, quoted separately"
            ),
        },
        "rule": (
            "every VIEW_EVENTSCANS query must carry a key (WAYBILL or TRACKNO = '…' "
            "or IN (up to 100 literals); MANIFEST = n or IN (up to 20)) or a window "
            "(EVENTDATE between two literal dates, at most 3 days) on its alias, in "
            "WHERE or JOIN ON and outside any OR; WAYDATE, ACCNUM, NAME, HUB, "
            "USERNAME and AGENTNAME are filters only — the view is for waybill and "
            "manifest lookups; a scans-by-type-over-a-date-range question is the "
            "event-counts tool, quoted separately; joined to VIEW_WBANALYSE, "
            "MANIFEST or AGENTDRIVER, that relation's own alias must carry its key "
            "too (WAYBILL / MANIFEST / AGENT = or IN, or a WAYDATE range of at most "
            "31 days on the view) (QT-000007 line 4, measured 21 Oct 2026)"
        ),
    },
}

_MANIFEST_HINT = (
    "manifest numbers repeat across branches and leg types (37733 is 133 rows "
    "by MANIFEST alone, 124 with MBRANCH = 0 AND MTYPE = 'M') — add MBRANCH and "
    "MTYPE to pin one trip"
)

# Tokens for the window check — unlike the guard's cleaned text, string
# literals are KEPT (the dates and keys live in them); comments are blanked.
_W_TOKEN = re.compile(
    r"'(?:[^']|'')*'"
    r"|[A-Za-z_][A-Za-z0-9_$]*"
    r"|\d+(?:\.\d+)?"
    r"|<=|>=|<>|!=|\|\||[=<>()*,.?+\-/]"
)
_CMP_OPS = {"=", "<", ">", "<=", ">="}
_MIRROR = {"<": ">", ">": "<", "<=": ">=", ">=": "<=", "=": "="}
_CLAUSE_KW = {
    "SELECT",
    "FROM",
    "WHERE",
    "ON",
    "GROUP",
    "HAVING",
    "ORDER",
    "UNION",
    "EXCEPT",
    "INTERSECT",
    "ROWS",
    "FETCH",
    "OFFSET",
    "PLAN",
    "WITH",
    "JOIN",
    "INNER",
    "LEFT",
    "RIGHT",
    "FULL",
    "CROSS",
}
_NOT_A_COLUMN = (
    _STOP
    | _CLAUSE_KW
    | {
        "AND",
        "OR",
        "NOT",
        "IN",
        "BETWEEN",
        "LIKE",
        "IS",
        "NULL",
        "CASE",
        "WHEN",
        "THEN",
        "ELSE",
        "END",
        "DATE",
        "TIMESTAMP",
        "TIME",
        "CAST",
        "BY",
        "ASC",
        "DESC",
        "STARTING",
        "CONTAINING",
        "SIMILAR",
        "ESCAPE",
        "EXISTS",
        "ANY",
        "SOME",
        "ALL",
        "CURRENT_DATE",
        "CURRENT_TIMESTAMP",
        "CURRENT_TIME",
    }
)


def _blank_comments(sql: str) -> str:
    """Blank -- and /* */ comments, KEEP string literals (offsets stable).
    sql_guard has already proven the literals are balanced."""
    out = list(sql)
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch == "'":
            j = i + 1
            while j < n and sql[j] != "'":
                j += 1
            i = j + 1
        elif ch == "-" and sql[i : i + 2] == "--":
            j = sql.find("\n", i)
            j = n if j == -1 else j
            for k in range(i, j):
                out[k] = " "
            i = j
        elif ch == "/" and sql[i : i + 2] == "/*":
            j = sql.find("*/", i + 2)
            j = n - 2 if j == -1 else j
            for k in range(i, j + 2):
                out[k] = " "
            i = j + 2
        else:
            i += 1
    return "".join(out)


def _w_tokens(sql: str) -> list[tuple[str, str]]:
    """(text, kind) with kind in LIT / NUM / ID / P (anything else)."""
    toks = []
    for m in _W_TOKEN.finditer(_blank_comments(sql)):
        t = m.group(0)
        if t.startswith("'"):
            toks.append((t[1:-1].replace("''", "'"), "LIT"))
        elif t[0].isdigit():
            toks.append((t, "NUM"))
        elif _IDENT.fullmatch(t):
            toks.append((t, "ID"))
        else:
            toks.append((t, "P"))
    return toks


def _paren_structure(toks):
    """group[i] = index of the innermost '(' enclosing token i (-1 at top);
    match[open] = close; is_sub[open] = the paren holds a SELECT."""
    group = [-1] * len(toks)
    match: dict[int, int] = {}
    stack: list[int] = []
    for i, (t, k) in enumerate(toks):
        group[i] = stack[-1] if stack else -1
        if t == "(" and k == "P":
            stack.append(i)
        elif t == ")" and k == "P" and stack:
            match[stack.pop()] = i
    for s in stack:  # unbalanced — Firebird will refuse; close at the end
        match[s] = len(toks)
    is_sub = {
        s: (
            s + 1 < len(toks)
            and toks[s + 1][1] == "ID"
            and toks[s + 1][0].upper() == "SELECT"
        )
        for s in match
    }
    return group, match, is_sub


def _scope_of(i, group, is_sub):
    """The query block a token belongs to: the innermost enclosing paren that
    holds a SELECT, or -1 for the outer statement. Grouping parens are skipped."""
    g = group[i]
    while g != -1 and not is_sub.get(g, False):
        g = group[g]
    return g


def _table_occurrences(toks, ctes):
    """Every name in table position with its alias (the name itself when none
    is given) and token index. Same walk as _referenced_tables; CTE names are
    returned flagged so scope counting can see them but the window check skips
    them."""
    occ = []
    i, n = 0, len(toks)
    while i < n:
        if toks[i][1] != "ID" or toks[i][0].upper() not in ("FROM", "JOIN"):
            i += 1
            continue
        i += 1
        expect_name = True
        while i < n:
            t, k = toks[i]
            u = t.upper()
            if expect_name:
                if k != "ID" or u in _STOP:
                    break
                name_idx = i
                alias = t
                i += 1
                if i < n and toks[i][1] == "ID" and toks[i][0].upper() == "AS":
                    if i + 1 < n and toks[i + 1][1] == "ID":
                        alias = toks[i + 1][0]
                        i += 2
                elif i < n and toks[i][1] == "ID" and toks[i][0].upper() not in _STOP:
                    alias = toks[i][0]
                    i += 1
                occ.append((u, alias, name_idx, u in ctes))
                expect_name = False
            elif t == "," and k == "P":
                expect_name = True
                i += 1
            else:
                break
    return occ


def _value_at(toks, j, group, match, is_sub):
    """Classify the value starting at token j: ('lit', text, end) for a string
    (also DATE 'x' / TIMESTAMP 'x' / CAST('x' AS …)), ('num', text, end),
    or ('bad', reason, end). end = index of the last token of the value."""
    n = len(toks)
    if j >= n:
        return ("bad", "nothing after the operator", j)
    t, k = toks[j]
    u = t.upper()
    kind, text, end = None, None, j
    if k == "LIT":
        kind, text = "lit", t
    elif k == "NUM":
        kind, text = "num", t
    elif t == "-" and j + 1 < n and toks[j + 1][1] == "NUM":
        kind, text, end = "num", "-" + toks[j + 1][0], j + 1
    elif t == "?":
        return ("bad", "a parameter (?) — write the literal value", j)
    elif (
        k == "ID"
        and u in ("DATE", "TIMESTAMP", "TIME")
        and j + 1 < n
        and toks[j + 1][1] == "LIT"
    ):
        kind, text, end = "lit", toks[j + 1][0], j + 1
    elif k == "ID" and u == "CAST" and j + 1 < n and toks[j + 1][0] == "(":
        close = match.get(j + 1, n)
        if j + 2 < n and toks[j + 2][1] == "LIT":
            kind, text, end = "lit", toks[j + 2][0], close
        else:
            return ("bad", "a CAST of something other than a literal", close)
    elif t == "(" and k == "P":
        close = match.get(j, n)
        if is_sub.get(j, False):
            return ("bad", "a subquery — write literal values", close)
        return ("bad", "an expression in parentheses, not a literal", close)
    elif k == "ID":
        if u.startswith("CURRENT_"):
            return ("bad", f"{u} arithmetic — write literal dates 'YYYY-MM-DD'", j)
        name = t
        if j + 2 < n and toks[j + 1][0] == "." and toks[j + 2][1] == "ID":
            name = f"{t}.{toks[j + 2][0]}"
        return ("bad", f"{name} (a column or function), not a literal", j)
    else:
        return ("bad", "not a literal", j)
    # a literal followed by arithmetic is an expression
    if (
        end + 1 < n
        and toks[end + 1][0] in ("+", "-", "*", "/", "||")
        and toks[end + 1][1] == "P"
    ):
        return ("bad", "arithmetic on a literal — write the final value", end)
    return (kind, text, end)


def _in_list_at(toks, s, group, match, is_sub):
    """Items of an IN ( … ) list opening at token s. Returns (count, reason)."""
    close = match.get(s, len(toks))
    if is_sub.get(s, False):
        return 0, "a subquery — write literal values"
    items = 0
    j = s + 1
    while j < close:
        kind, text, end = _value_at(toks, j, group, match, is_sub)
        if kind == "bad":
            return 0, text
        items += 1
        j = end + 1
        if j < close and toks[j][0] == ",":
            j += 1
    return items, None


def _parse_date(text):
    """'YYYY-MM-DD' (optionally followed by a time) -> date, else None."""
    try:
        return _dt.date.fromisoformat(text.strip()[:10])
    except ValueError:
        return None


class _Pred:
    __slots__ = (
        "alias",
        "bad",
        "clause",
        "col",
        "count",
        "in_or",
        "kind",
        "negated",
        "op",
        "scope",
        "start",
        "values",
    )

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))


def _predicates(toks, group, match, is_sub, columns_of_interest):
    """Every comparison on a column of interest: who it is on (alias or bare),
    what shape (eq / in / between / lo / hi / other), the literal values or
    why they are not literals, and the structural facts that disqualify it
    (clause, inside an OR, negated)."""
    n = len(toks)
    preds = []
    i = 0
    while i < n:
        t, k = toks[i]
        u = t.upper()
        if k != "ID" or u in _NOT_A_COLUMN or u not in columns_of_interest:
            i += 1
            continue
        nxt = toks[i + 1][0] if i + 1 < n else ""
        if nxt in (".", "("):  # an alias, or a function call
            i += 1
            continue
        alias, start = None, i
        if i >= 2 and toks[i - 1][0] == "." and toks[i - 2][1] == "ID":
            alias, start = toks[i - 2][0].upper(), i - 2
        elif i >= 1 and toks[i - 1][0] == ".":
            i += 1
            continue
        p = _Pred(
            start=start,
            alias=alias,
            col=u,
            kind="other",
            op=None,
            values=[],
            count=0,
            bad=None,
        )
        j = i + 1
        negated = i >= 1 and toks[i - 1][1] == "ID" and toks[i - 1][0].upper() == "NOT"
        if (
            start >= 1
            and toks[start - 1][1] == "ID"
            and toks[start - 1][0].upper() == "NOT"
        ):
            negated = True
        if j < n and toks[j][1] == "ID" and toks[j][0].upper() == "NOT":
            negated = True
            j += 1
        op = toks[j][0].upper() if j < n else ""
        if op in _CMP_OPS:
            kind, text, _end = _value_at(toks, j + 1, group, match, is_sub)
            p.op = op
            if kind == "bad":
                p.bad = text
            else:
                p.values = [text]
            p.kind = {"=": "eq", "<": "hi", "<=": "hi", ">": "lo", ">=": "lo"}[op]
        elif op == "IN" and j + 1 < n and toks[j + 1][0] == "(":
            p.kind, p.op = "in", "IN"
            p.count, p.bad = _in_list_at(toks, j + 1, group, match, is_sub)
        elif op == "BETWEEN":
            p.kind, p.op = "between", "BETWEEN"
            k1, t1, e1 = _value_at(toks, j + 1, group, match, is_sub)
            if k1 == "bad":
                p.bad = t1
            elif e1 + 1 < n and toks[e1 + 1][0].upper() == "AND":
                k2, t2, _e2 = _value_at(toks, e1 + 2, group, match, is_sub)
                if k2 == "bad":
                    p.bad = t2
                else:
                    p.values = [t1, t2]
            else:
                p.bad = "BETWEEN without AND"
        elif op in ("<>", "!=", "LIKE", "STARTING", "CONTAINING", "SIMILAR", "IS"):
            p.kind, p.op = "other", op
        elif (
            start >= 2
            and toks[start - 1][0] in _CMP_OPS
            and toks[start - 1][1] == "P"
            and toks[start - 2][1] in ("LIT", "NUM")
        ):
            # mirrored: 'x' = alias.COL
            mop = _MIRROR[toks[start - 1][0]]
            p.op = mop
            p.kind = {"=": "eq", "<": "hi", "<=": "hi", ">": "lo", ">=": "lo"}[mop]
            p.values = [toks[start - 2][0]]
        else:
            i += 1
            continue  # not a comparison (select list, GROUP BY, ORDER BY …)
        p.negated = negated
        p.scope = _scope_of(start, group, is_sub)
        p.clause, p.in_or, neg2 = _structure_of(
            toks, start, group, match, is_sub, p.scope
        )
        p.negated = p.negated or neg2
        preds.append(p)
        i += 1
    return preds


def _structure_of(toks, s, group, match, is_sub, scope):
    """Walk up from a predicate: which clause of its query block it is in,
    whether any enclosing level (grouping parens up to the clause) carries an
    OR, and whether a NOT fronts an enclosing paren group."""
    in_or = False
    negated = False
    lvl = group[s]
    while lvl != -1 and not is_sub.get(lvl, False):
        close = match.get(lvl, len(toks))
        for j in range(lvl + 1, close):
            if group[j] == lvl and toks[j][1] == "ID" and toks[j][0].upper() == "OR":
                in_or = True
        if lvl >= 1 and toks[lvl - 1][1] == "ID" and toks[lvl - 1][0].upper() == "NOT":
            negated = True
        lvl = group[lvl]
    # clause region at the scope level
    lo = scope + 1 if scope != -1 else 0
    hi = match.get(scope, len(toks)) if scope != -1 else len(toks)
    clause = "SELECT"
    j = s - 1
    while j >= lo:
        if (
            group[j] == scope
            and toks[j][1] == "ID"
            and toks[j][0].upper() in _CLAUSE_KW
        ):
            clause = toks[j][0].upper()
            break
        j -= 1
    region_start = j + 1 if j >= lo else lo
    j = s + 1
    while j < hi:
        if (
            group[j] == scope
            and toks[j][1] == "ID"
            and toks[j][0].upper() in _CLAUSE_KW
        ):
            break
        j += 1
    region_end = j
    for j in range(region_start, region_end):
        if group[j] == scope and toks[j][1] == "ID" and toks[j][0].upper() == "OR":
            in_or = True
    return clause, in_or, negated


def _days(n: int) -> str:
    return "1 day" if n == 1 else f"{n} days"


def _judge(table, spec, alias, mine, pins_seen):
    """Qualifying descriptions and disqualification reasons for one occurrence."""
    label = f"{alias}." if alias.upper() != table else ""
    qualifying: list[str] = []
    reasons: list[str] = []
    lows: list[tuple[_dt.date, str]] = []
    highs: list[tuple[_dt.date, str]] = []
    for p in mine:
        ref = f"{label}{p.col}"
        if p.clause not in ("WHERE", "ON"):
            reasons.append(
                f"{ref} is in the {p.clause} clause — only a WHERE or JOIN ON predicate bounds the read"
            )
            continue
        if p.negated:
            reasons.append(
                f"{ref} is negated (NOT) — a negation does not bound the read"
            )
            continue
        if p.in_or:
            reasons.append(
                f"{ref} sits inside an OR — an OR widens the read; put alternatives in IN (…)"
            )
            continue
        if p.col in spec["keys"]:
            limit = spec["keys"][p.col]
            if p.kind == "eq":
                if p.bad:
                    reasons.append(f"{ref} = … is {p.bad}")
                else:
                    qualifying.append(f"keyed by {p.col} (1 literal)")
            elif p.kind == "in":
                if p.bad:
                    reasons.append(f"{ref} IN (…) holds {p.bad}")
                elif p.count > limit:
                    reasons.append(
                        f"{ref} IN (…) has {p.count} literals — the limit is {limit}"
                    )
                else:
                    qualifying.append(f"keyed by {p.col} IN ({p.count} literals)")
            else:
                reasons.append(f"{ref} {p.op} … is not a key — use = or IN (…)")
        elif p.col == spec["date"]:
            if p.kind in ("eq", "between"):
                if p.bad:
                    reasons.append(f"the {ref} range is {p.bad}")
                    continue
                dates = [_parse_date(v) for v in p.values]
                if any(d is None for d in dates):
                    reasons.append(
                        f"{ref} compares to a date that is not 'YYYY-MM-DD' — write dates as 'YYYY-MM-DD'"
                    )
                    continue
                lo_d, hi_d = dates[0], dates[-1]
                width = (hi_d - lo_d).days + 1
                if width <= 0:
                    reasons.append(f"the {ref} bounds are reversed ({lo_d}..{hi_d})")
                elif width > spec["max_days"]:
                    reasons.append(
                        f"the {ref} range is {width} days ({lo_d}..{hi_d}) — the limit is {spec['max_days']} days"
                    )
                else:
                    qualifying.append(f"{p.col} window {lo_d}..{hi_d} ({_days(width)})")
            elif p.kind in ("lo", "hi"):
                if p.bad:
                    reasons.append(f"the {ref} bound is {p.bad}")
                    continue
                d = _parse_date(p.values[0])
                if d is None:
                    reasons.append(
                        f"{ref} compares to a date that is not 'YYYY-MM-DD' — write dates as 'YYYY-MM-DD'"
                    )
                    continue
                if p.kind == "lo":
                    lows.append((d + _dt.timedelta(days=1) if p.op == ">" else d, ref))
                else:
                    highs.append((d - _dt.timedelta(days=1) if p.op == "<" else d, ref))
            else:
                reasons.append(
                    f"{ref} {p.op} … is not a date range — use BETWEEN or >= … AND <= …"
                )
        elif p.col in spec["filters_only"]:
            why = spec["filter_why"].get(p.col)
            reasons.append(
                f"{p.col} is a filter, not a key or window on {table}"
                + (f" — {why}" if why else "")
            )
    if lows or highs:
        ref = f"{label}{spec['date']}"
        if not lows or not highs:
            reasons.append(
                f"only one bound on {ref} — give both ends (>= and <= literal dates)"
            )
        else:
            lo_d = max(d for d, _ in lows)
            hi_d = min(d for d, _ in highs)
            width = (hi_d - lo_d).days + 1
            if width <= 0:
                reasons.append(f"the {ref} bounds are reversed ({lo_d}..{hi_d})")
            elif width > spec["max_days"]:
                reasons.append(
                    f"the {ref} range is {width} days ({lo_d}..{hi_d}) — the limit is {spec['max_days']} days"
                )
            else:
                qualifying.append(
                    f"{spec['date']} window {lo_d}..{hi_d} ({_days(width)})"
                )
    keyed_by_manifest = any(q.startswith("keyed by MANIFEST") for q in qualifying)
    if spec["pins"] and keyed_by_manifest and not set(spec["pins"]) <= pins_seen:
        qualifying.append(_MANIFEST_HINT)
    return qualifying, reasons


def _check_windowed(sql: str, tables: list[str], windows: list[str] | None) -> None:
    """For every occurrence of a windowed table, require a qualifying key or
    window predicate on its own alias; describe what was applied (into
    `windows`) or refuse naming what was missing."""
    specs = {t: WINDOWED[t] for t in tables if t in WINDOWED}
    if not specs:
        return
    toks = _w_tokens(sql)
    group, match, is_sub = _paren_structure(toks)
    ctes = {
        m.group(1).upper()
        for m in _CTE_NAME.finditer(_strip_literals_and_comments(sql))
    }
    occurrences = _table_occurrences(toks, ctes)
    scope_count: dict[int, int] = {}
    for _t, _a, idx, _is_cte in occurrences:  # every table, CTE refs included
        sc = _scope_of(idx, group, is_sub)
        scope_count[sc] = scope_count.get(sc, 0) + 1
    interest: set[str] = set()
    for jb in _JOIN_BOUND.values():  # the joined relations' own keys
        interest |= set(jb["keys"]) | ({jb["date"]} if jb["date"] else set())
    for spec in specs.values():
        interest |= (
            set(spec["keys"])
            | {spec["date"]}
            | set(spec["filters_only"])
            | set(spec["pins"])
        )
    preds = _predicates(toks, group, match, is_sub, interest)
    windowed_scopes: set[int] = set()
    for table, alias, idx, is_cte in occurrences:
        if is_cte or table not in specs:
            continue
        spec = specs[table]
        sc = _scope_of(idx, group, is_sub)
        single = scope_count.get(sc, 0) == 1
        alias_u = alias.upper()  # Firebird identifiers are case-insensitive unquoted
        mine = [
            p
            for p in preds
            if p.scope == sc and (p.alias == alias_u or (p.alias is None and single))
        ]
        unqualified = sorted(
            {p.col for p in preds if p.scope == sc and p.alias is None and not single}
        )
        pins_seen = {p.col for p in mine if p.col in spec["pins"]}
        qualifying, reasons = _judge(table, spec, alias, mine, pins_seen)
        label = f"{table} (alias {alias})" if alias_u != table else table
        if qualifying:
            windowed_scopes.add(sc)
            if windows is not None:
                short = f"{table} ({alias})" if alias_u != table else table
                windows.append(f"{short}: " + "; ".join(qualifying))
            continue
        for col in unqualified:
            reasons.append(
                f"{col} is unqualified in a multi-table query — qualify it "
                f"({alias}.{col}) so the key or window is on {table}"
            )
        detail = f" — found: {'; '.join(reasons)}" if reasons else ""
        raise GuardError(f"no key or window on {label}{detail}. Rule: {spec['rule']}.")
    _check_join_bounds(occurrences, preds, group, is_sub, windowed_scopes)


# Akha's call on the 21 Oct join finding: refuse, do not caution. A windowed
# table joined (JOIN or comma list) to one of these large relations needs the
# large relation's OWN literal key — the plans read 21 Oct 2026 show Firebird
# driving such a join from the big side with a NATURAL scan unless its own
# column is bounded (only a single '=' on the ROUTING side propagates, and
# the fence must not depend on the optimizer). VIEW_WBANALYSE may instead
# carry a WAYDATE range (WA_WAYDATE, the daily extraction's path). AGENTDRIVER
# has no MANIFEST column (AGENTDRIVER, AGENT, DRIVER, FROMDATE, FROMTIME,
# USERCODE, LOADLVL, ROUTE), so its key is AGENT. On their own, without a
# windowed table in the query, these relations stay as they were on Day 5.
_JOIN_BOUND: dict[str, dict] = {
    "VIEW_WBANALYSE": {
        "keys": {"WAYBILL": 100},
        "date": "WAYDATE",
        "max_days": 31,
        "filters_only": (),
        "pins": (),
        "filter_why": {},
        "rows": "3.1M",
        "fix": (
            "repeat the waybill filter on the VIEW_WBANALYSE alias ({a}.WAYBILL = "
            "/ IN the same literals, up to 100), or bound it on WAYDATE "
            "({a}.WAYDATE between two literal dates, at most 31 days)"
        ),
    },
    "MANIFEST": {
        "keys": {"MANIFEST": 100},
        "date": None,
        "max_days": 0,
        "filters_only": (),
        "pins": (),
        "filter_why": {},
        "rows": "308k",
        "fix": "repeat the manifest filter on the MANIFEST alias ({a}.MANIFEST = / IN literals, up to 100)",
    },
    "AGENTDRIVER": {
        "keys": {"AGENT": 100},
        "date": None,
        "max_days": 0,
        "filters_only": (),
        "pins": (),
        "filter_why": {},
        "rows": "723k",
        "fix": (
            "repeat the agent filter on the AGENTDRIVER alias ({a}.AGENT = / IN "
            "literals, up to 100 — AGENTDRIVER has no MANIFEST column; AGENT is its key)"
        ),
    },
}


def _check_join_bounds(occurrences, preds, group, is_sub, windowed_scopes):
    """In any query block where a windowed table qualified, every occurrence
    of a _JOIN_BOUND relation must carry its own literal key (or, for the
    view, a WAYDATE range) under the same structural rules; refuse otherwise."""
    for table, alias, idx, is_cte in occurrences:
        if is_cte or table not in _JOIN_BOUND:
            continue
        sc = _scope_of(idx, group, is_sub)
        if sc not in windowed_scopes:
            continue
        spec = _JOIN_BOUND[table]
        alias_u = alias.upper()
        mine = [p for p in preds if p.scope == sc and p.alias == alias_u]
        qualifying, reasons = _judge(table, spec, alias, mine, set())
        if qualifying:
            continue
        others = sorted(
            {
                t
                for t, a, i, c in occurrences
                if not c and t in WINDOWED and _scope_of(i, group, is_sub) == sc
            }
        )
        detail = f" (found: {'; '.join(reasons)})" if reasons else ""
        raise GuardError(
            f"{table} (alias {alias}) is joined to {' / '.join(others)} without a key "
            f"of its own{detail} — {spec['fix'].format(a=alias)}. Firebird would "
            f"otherwise scan the {spec['rows']}-row relation for that join (plans "
            "read 21 Oct 2026); the window on "
            f"{' / '.join(others)} bounds only its own side."
        )


def check_open_query(sql: str, windows: list[str] | None = None) -> list[str]:
    """Full gate: SELECT-only, no quoted identifiers, every relation in table
    position on the allowlist, no withheld column named anywhere, no
    projection star over a table that has withheld columns, and a key or
    window on every occurrence of a WINDOWED table. Returns the tables
    referenced (and, if `windows` is a list, appends one line per windowed
    occurrence saying what bounded it); raises GuardError otherwise."""
    if len(sql) > _MAX_SQL_CHARS:
        raise GuardError(
            f"the statement is {len(sql):,} characters — the open path accepts at "
            f"most {_MAX_SQL_CHARS:,}; shorten it"
        )
    _check_characters(sql)  # Q1: before anything else reads the text
    _check_no_comments(sql)  # Q1: the strippers are no longer load-bearing
    if '"' in sql:
        raise GuardError(
            "quoted identifiers are not supported on the open path — every "
            "Parcel Perfect name is plain uppercase; write it unquoted"
        )
    _check_introduced_literals(sql)  # before any stripper reads the text (T3)
    assert_select_only(sql)
    cleaned = _strip_literals_and_comments(sql).rstrip()
    cleaned = cleaned.removesuffix(
        ";"
    )  # one trailing semicolon, tolerated upstream (Q3)
    _check_with_position(cleaned)  # T2
    if _PLAN_WORD.search(cleaned):
        # Fable re-review R5 (21 Oct 2026): a user PLAN clause beats every
        # index the guard relies on — `… PLAN (R NATURAL)` is a scan on demand.
        raise GuardError(
            "a PLAN clause is not accepted on the open path — the server chooses "
            "the plan; remove it"
        )
    if _WITH_LOCK.search(cleaned):
        raise GuardError("WITH LOCK is not accepted on the open path — remove it")
    spans = _cte_spans(cleaned)
    _check_cte_names(spans)
    placed, from_problem = _scan_from_lists(cleaned, with_positions=True)
    # A CTE name is excluded only for references OUTSIDE its own body; inside
    # it (a non-recursive CTE cannot see itself) the name is the base table.
    tables = [
        t for pos, t in placed if t not in spans or spans[t][0] <= pos <= spans[t][1]
    ]
    if not tables and from_problem is None:
        raise GuardError("no table found in the FROM clause")
    # The names that WERE read are checked first so a refused relation gets
    # its own message; a FROM list the scanner could not finish refuses after
    # that regardless — never a partial table set.
    for t in tables:
        if t in ALLOWLIST:
            continue
        if t in DENIED:
            raise GuardError(DENIED[t])
        if t.startswith(("RDB$", "MON$", "SEC$", "TMP$")):
            raise GuardError(
                f"{t} is a Firebird system relation — the schema resource "
                "(schema://parcel-perfect) already provides the schema"
            )
        raise GuardError(
            f"{t} is not on the open-path allowlist. Queryable relations: "
            + ", ".join(sorted(ALLOWLIST))
        )
    if from_problem:
        raise GuardError(from_problem)
    if not tables:
        raise GuardError("no table found in the FROM clause")
    tables = sorted(set(tables))
    _check_denied_columns(cleaned, tables)
    _check_star_projection(cleaned, tables)
    _check_windowed(sql, tables, windows)
    return tables


# --- execution ------------------------------------------------------------------


def _value(v):
    """Serialise for the answer: dates/times to ISO, CHAR padding stripped."""
    if isinstance(v, str):
        v = v.strip()
        return v if v else None
    if isinstance(v, (bytes, bytearray)):
        # Binary-subtype BLOBs (NOTE.MEMO) come back as bytes; the connection
        # charset is latin1, so decode the same way — never leak b'...' repr.
        v = bytes(v).decode("latin1", errors="replace").strip()
        return v if v else None
    if isinstance(v, (_dt.datetime, _dt.time)):
        return v.isoformat(timespec="seconds")
    if isinstance(v, _dt.date):
        return v.isoformat()
    return v


def _date_warnings(columns: list[str], rows: list[tuple]) -> list[str]:
    """Flag every date column whose values fall outside the plausible window.
    day_guards.plausible_window owns the arithmetic; this states the finding
    per column so an aggregate over it is never trusted unexamined."""
    today = _dt.date.today()
    warnings = []
    for ix, name in enumerate(columns):
        col = [r[ix] for r in rows]
        if not any(isinstance(v, _dt.date) for v in col):
            continue
        c = classify_dates(col, today)
        if c["placeholder"]:
            warnings.append(
                f"{name}: {c['placeholder']} of {len(rows)} values are "
                f"{PP_NULL_DATE.isoformat()} — Parcel Perfect's null-date "
                "placeholder, not a real date. Any min/aggregate including "
                "them is wrong."
            )
        if c["before_floor"]:
            warnings.append(
                f"{name}: {c['before_floor']} values fall before "
                f"{plausible_window(today)[0].isoformat()} — mis-keyed junk, "
                "not history."
            )
        if c["future"]:
            warnings.append(
                f"{name}: {c['future']} values fall after today — either "
                "legitimately booked ahead or a mis-keyed year (a year-9473 "
                "typo once moved a client-facing frontier). Check before "
                "trusting a max() over this column."
            )
    return warnings


def run_open_query(question: str, sql: str, run=run_select) -> dict:
    """Gate, run and shape one open query. Refusals come back as the same
    {"ok": False, "refused": True, ...} shape the revenue tools use."""
    if not question or not str(question).strip():
        return _refused(
            "a plain-language `question` is required alongside the SQL — it is "
            "the audit trail for why this query ran"
        )
    if not sql or not str(sql).strip():
        return _refused("no SQL provided")
    sql = str(sql).strip()

    windows: list[str] = []
    try:
        tables = check_open_query(sql, windows)
    except GuardError as e:
        return _refused(str(e))

    started = time.perf_counter()
    try:
        columns, rows = run(sql, (), ROW_CAP + 1, timeout=TIMEOUT_S)
    except ConnectionError:
        raise
    except Exception as e:
        # The driver reports a tripped socket timeout as OperationalError
        # "Can not recv() packets" (fbcore._recv_channel), not TimeoutError —
        # observed live 18 Aug when a MAX() over the 3.1M-row view blew a 30s
        # cap. A genuine mid-query disconnect reads the same; either way the
        # query was abandoned, not answered.
        msg = str(e).lower()
        if isinstance(e, (socket.timeout, TimeoutError)) or (
            "timed out" in msg or "can not recv" in msg
        ):
            return _refused(
                f"the query exceeded the {TIMEOUT_S}s time cap (or the "
                "connection dropped mid-query) and was abandoned — narrow it "
                "(add WHERE bounds, or aggregate in SQL rather than fetching "
                "rows)"
            )
        return _refused(
            f"Firebird refused the query: {e}",
            # A Firebird type/conversion error echoes the offending row value
            # (e.g. `conversion error from string "<a customer name>"`). Keep
            # that in the user-facing reason — the user is authorised — but
            # never write it to the audit log, which must carry no data bodies.
            audit_reason=(
                f"Firebird rejected the query ({type(e).__name__}); detail "
                "withheld from the audit log (a DB error can echo row values)"
            ),
        )
    elapsed_ms = round((time.perf_counter() - started) * 1000)

    if len(rows) > ROW_CAP:
        return _refused(
            f"the query returned more than {ROW_CAP} rows — refusing to "
            "truncate silently. Aggregate in SQL (COUNT/SUM/GROUP BY), add "
            f"WHERE bounds, or SELECT FIRST {ROW_CAP} explicitly if a sample "
            f"is genuinely wanted.{_size_hint(tables)}"
        )

    # Second enforcement of the column deny list — defence in depth. After
    # Fable F1 no projection star over a withheld table reaches Firebird and
    # a denied column NAMED in the SQL never gets this far either, so this
    # only fires if a statement the gate accepted somehow returns a denied
    # column name. Drop by cursor-description name and say so.
    denied = _denied_for(tables)
    withheld = [c for c in columns if c.upper() in denied]
    if withheld:
        keep = [i for i, c in enumerate(columns) if c.upper() not in denied]
        if not keep:
            return _refused(
                "every column of the result is withheld "
                f"({', '.join(withheld)}) — {_WITHHELD_WHY}"
            )
        columns = [columns[i] for i in keep]
        rows = [tuple(r[i] for i in keep) for r in rows]

    notes = [
        "Open-path answer: a raw read, not a verified report figure.",
    ]
    for w in windows:
        notes.append(f"Window applied — {w}.")
    if withheld:
        notes.append(
            f"Withheld columns (not in this result): {', '.join(withheld)} — "
            f"{_WITHHELD_WHY}. Dropped by name across every table in the "
            "statement."
        )
    if not rows:
        notes.append(
            "0 rows matched. That is the absence of MATCHING ROWS, not a "
            "verified zero — before answering 'none', check the filters "
            "against the schema resource (date window, exact codes, CHAR "
            "padding) and say what was searched."
        )
    if _REVENUE_TABLES & set(tables) or (
        "VIEW_WBANALYSE" in tables and _REVENUE_COLUMNS.search(sql)
    ):
        notes.append(HONEST_BOUNDARY)

    return {
        "ok": True,
        "question": str(question).strip(),
        "tables": tables,
        "columns": columns,
        "rows": [[_value(v) for v in r] for r in rows],
        "row_count": len(rows),
        "elapsed_ms": elapsed_ms,
        "warnings": _date_warnings(columns, rows),
        "notes": notes,
    }


def _size_hint(tables: list[str]) -> str:
    """' (RATE: 680,552 rows at the 6 Aug survey)' for the big tables in a
    capped query — so the refusal on a rate table says why 500 was never
    going to hold it. Empty when nothing referenced is large."""
    try:
        data = _schema_data()["tables"]
    except Exception:
        return ""
    big = []
    for t in tables:
        n = data.get(t, {}).get("row_count")
        if n and n > ROW_CAP * 20:
            big.append(f"{t}: {n:,} rows")
    if not big:
        return ""
    return (
        f" ({'; '.join(big)} at the {_schema_data()['survey_date']} survey — "
        "filter by account, agent or date before reading rows)"
    )


def _refused(reason: str, audit_reason: str | None = None) -> dict:
    d = {"ok": False, "refused": True, "reason": reason}
    if audit_reason is not None:
        # A log-safe restatement for reasons whose user-facing text may echo a
        # DB value (see the Firebird-error path). audit._outcome prefers it.
        d["audit_reason"] = audit_reason
    return d


# --- schema context ---------------------------------------------------------------

_SCHEMA_JSON = Path(__file__).resolve().parent / "schema_context.json"

_DATE_CAVEAT = (
    "DATE/TIMESTAMP columns: Parcel Perfect carries 1899-12-30 as its "
    "null-date placeholder (live today in DUEDATE / last-delivery columns) "
    "and mis-keyed years (9473 has happened) as a matter of course. Treat "
    "pre-1990 dates as junk, treat future dates as suspect, and bound every "
    "date aggregate — an unbounded min()/max() over a PP date column has "
    "produced a wrong client-facing number three times on this project. "
    "Results flag implausible dates per column automatically."
)


@lru_cache(maxsize=1)
def _schema_data() -> dict:
    return json.loads(_SCHEMA_JSON.read_text())


def _columns_of(table: str) -> set[str]:
    """Survey column names of one allowlisted table (empty if unknown)."""
    try:
        info = _schema_data()["tables"].get(table, {})
    except Exception:
        return set()
    return {c["name"].upper() for c in info.get("columns", ())}


def schema_context(table: str | None = None) -> dict:
    """The schema resource content: real column names/types from the 6 Aug
    survey for the allowlisted tables, each with its justification, plus the
    caveats a correct Firebird query against PP needs."""
    data = _schema_data()
    tables = {}
    for name, info in data["tables"].items():
        denied = DENIED_COLUMNS.get(name, frozenset())
        served = [c for c in info["columns"] if c["name"].upper() not in denied]
        n_withheld = len(info["columns"]) - len(served)
        tables[name] = {
            "why_queryable": ALLOWLIST[name],
            **{k: v for k, v in info.items() if k != "columns"},
            "columns": served,
            # The names themselves are not listed: this resource must carry
            # none of them (pinned by a test). Naming one in SQL is refused.
            "withheld_columns": (
                f"{n_withheld} contact/banking/password column(s) withheld on "
                "this path — not listed here, refused if named in SQL, dropped "
                "from SELECT *"
                if n_withheld
                else "none — no contact, banking or password columns"
            ),
        }
        if name in WINDOWED:
            tables[name]["window_rule"] = WINDOWED[name]["rule"]
    if table is not None:
        t = str(table).strip().upper()
        if t not in tables:
            hint = DENIED.get(t, f"{t} is not on the allowlist")
            return {"error": hint, "queryable_tables": sorted(tables)}
        tables = {t: tables[t]}
    return {
        "database": "Parcel Perfect (Firebird) — live production freight system",
        "survey_date": data["survey_date"],
        "read_this_first": [
            (
                "Only these tables are queryable; everything else is refused "
                "(EVENT and the other 100M+-row tables stay off: a waybill's scan "
                "history is on VIEW_EVENTSCANS, and scans by type over a date "
                "range are the event-counts tool, quoted separately)."
            ),
            (
                "ROUTING and VIEW_EVENTSCANS are windowed: every query must key "
                "them (WAYBILL / TRACKNO / MANIFEST = or IN, literal values) or "
                "bound them with a literal date range on AGENTDATE (at most 31 "
                "days) or EVENTDATE (at most 3 days), on the table's own alias, "
                "in WHERE or JOIN ON, outside any OR — see each table's "
                "window_rule (QT-000007 line 4, measured 21 Oct 2026)."
            ),
            (
                f"Row cap {ROW_CAP} (a hit cap refuses, not truncates); "
                f"time cap {TIMEOUT_S}s."
            ),
            (
                "Contact (phone/cell/fax/email), banking, password and "
                "infrastructure columns are withheld on every table: they are "
                "omitted below, a query that names one anywhere is refused, "
                "and SELECT * / alias.* is refused on any statement that "
                "touches a table with withheld columns — list the columns "
                "(COUNT(*) is fine) (QT-000007, 20 Oct 2026)."
            ),
            (
                "Free-text columns (NOTE.MEMO/MEMOSTRING, COLLECT.NOTES, "
                "CUSTOMER.NOTE/SPECINSTRUCTION, waybill instructions) and "
                "person-name columns may carry hand-typed contact detail that "
                "the column guard cannot strip — relay them as the operational "
                "record they are, never as a contact source."
            ),
            (
                "Firebird SQL: SELECT FIRST n ... (not LIMIT); string literals "
                "in single quotes; CHAR columns are space-padded — compare with "
                "TRIM() or exact padded values."
            ),
            (
                f"Row counts here are the {data['survey_date']} survey snapshot "
                "and drift with live data (AGENT was 1,220 at survey, 1,225 "
                "live on 18 Aug) — never quote them as a live figure; run "
                "SELECT COUNT(*) for a current count."
            ),
            _DATE_CAVEAT,
            HONEST_BOUNDARY,
        ],
        "tables": tables,
    }
