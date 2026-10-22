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
  truncating silently, the same rule every revenue fetcher applies; the time
  cap is wall-clock (a worker with a deadline; the connection is cancelled
  and closed on expiry), not the driver's per-read socket timeout;
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
import threading
import time
from functools import lru_cache
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "revenue_reports"))

from day_guards import PP_NULL_DATE, classify_dates, plausible_window

from mcp_server.db import cancel_thread, run_select
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
# WALL-CLOCK cap on how long we WAIT (sixth review S2/S5, 22 Oct 2026: the
# driver's socket timeout is per read, so a statement that answered nothing
# for 30 s ran 30 s). The fetch runs in a worker thread with this deadline;
# on expiry the answer is refused at once and the worker's connection gets a
# best-effort Firebird cancel (op_cancel) and its socket shut, see db.
# cancel_thread. Honest limitation: Firebird 3.0.13 has no SET STATEMENT
# TIMEOUT and firebirdsql 1.3 exposes no cancel call, so whether the server
# stops the statement depends on it honouring op_cancel or noticing the
# closed socket — the cap bounds the answer, not the production load (the
# quote's deleted-sentence lesson).
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
# ROUTING carries per-leg money columns too (review L2, 21 Oct 2026); its own
# justification says to take revenue from the view, so the caveat rides along.
_ROUTING_MONEY = re.compile(
    r"\b(SUBTOTAL|VAT|TOTAL|INVAMOUNT|TOTPAID|VATPAID)\b", re.IGNORECASE
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


# The join-word sequences Firebird 3 accepts (OUTER needs LEFT / RIGHT / FULL;
# NATURAL joins carry no ON and are refused by the window check as "natural").
_JOIN_FORMS = {
    ("JOIN",),
    ("INNER", "JOIN"),
    ("CROSS", "JOIN"),
    ("LEFT", "JOIN"),
    ("LEFT", "OUTER", "JOIN"),
    ("RIGHT", "JOIN"),
    ("RIGHT", "OUTER", "JOIN"),
    ("FULL", "JOIN"),
    ("FULL", "OUTER", "JOIN"),
}


class _Item:
    """One item in table position, as the single FROM-list walk saw it: a
    base relation / CTE name or a derived table, its alias, how it was joined
    and the character span of its ON condition. The allowlist scan and the
    window check both read THIS list (sixth review S1, 22 Oct 2026: the
    window check used to walk the FROM list a second time with its own loop,
    which stopped silently at a derived table's column list while the
    scanner read past it — two walks that could disagree)."""

    __slots__ = ("alias", "char", "derived", "join_words", "name", "on", "tok", "using")

    def __init__(self, tok, char, name, derived, join_words):
        self.tok, self.char, self.name, self.derived = tok, char, name, derived
        self.join_words = join_words  # () first item, (",") comma, else join words
        self.alias = None
        self.on = None  # (start char, stop char) of the ON condition, or None
        self.using = False

    @property
    def kind(self):
        w = self.join_words
        if w == ():
            return "from"
        if w == (",",):
            return "comma"
        if w not in _JOIN_FORMS:
            return (
                "natural"  # NATURAL, or a malformed join: the window check refuses it
            )
        for outer in ("LEFT", "RIGHT", "FULL"):
            if outer in w:
                return outer.lower()
        return "cross" if "CROSS" in w else "inner"


def _from_items(cleaned: str) -> tuple[list, str | None]:
    """THE FROM-list walk: every item in table position across EVERY FROM
    list in the statement, in order of appearance, plus a problem message if
    any FROM list could not be read to its end.

    Hot-fix 21 Oct 2026 (Fable re-review R1): the Day 5 scanner stopped at
    the first ON or closing paren, so a comma-listed table after `JOIN … ON …`
    or after a derived table was never seen by the allowlist, the column deny
    list or the star ban. Each FROM is parsed through to its terminator:
    table [alias] { , table | <join words> table [alias] [ON … | USING …] }.
    After ON / USING the condition is skipped at the list's own depth up to
    the next join word, comma or terminator. Anything in table position the
    walk does not understand — a parenthesised join, a procedure call, a
    stray token, a dangling comma — is reported as a problem, and the caller
    refuses: the fence never falls through with a partial table set.

    Sixth review S1 (22 Oct 2026): this is the only walk. The window check
    attributes these items to SELECT blocks by character offset and refuses
    any it cannot place (see _attribute_items) instead of walking again."""
    matches = list(_FT.finditer(cleaned))
    toks = [m.group(0) for m in matches]
    char_at = [m.start() for m in matches]
    n = len(toks)
    end_char = len(cleaned) + 1
    items: list[_Item] = []
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

    def is_ident(i):
        return i < n and _IDENT.fullmatch(toks[i]) is not None

    def is_join_word(i):
        return (
            is_ident(i)
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
        ')' cannot legitimately end it. Returns (items, problem)."""
        out: list[_Item] = []
        expect_table = True
        join_words: tuple = ()
        while i < n:
            tok = toks[i]
            u = tok.upper()
            if expect_table:
                if tok == "(":
                    if is_ident(i + 1) and toks[i + 1].upper() in ("SELECT", "WITH"):
                        item = _Item(i, char_at[i], None, True, join_words)
                        i = skip_paren(
                            i
                        )  # derived table; its own FROM is walked separately
                    else:
                        return out, "a parenthesised join or a bracketed FROM item"
                elif is_ident(i) and u not in _STOP and u not in _JOIN_WORDS:
                    item = _Item(i, char_at[i], u, False, join_words)
                    i += 1
                    if i < n and toks[i] == "(":
                        # SOME_PROC(args): not a base relation. The name is
                        # still reported so the allowlist refuses it by name;
                        # the problem makes the refusal certain either way.
                        out.append(item)
                        return out, f"{u}(…) in table position (a procedure call)"
                else:
                    return out, f"'{tok}' where a table name was expected"
                # optional alias
                if is_ident(i) and toks[i].upper() == "AS":
                    if is_ident(i + 1):
                        item.alias = toks[i + 1].upper()
                        i += 2
                    else:
                        out.append(item)
                        return out, "AS without an alias"
                elif (
                    is_ident(i)
                    and toks[i].upper() not in _STOP
                    and toks[i].upper() not in _JOIN_WORDS
                ):
                    item.alias = toks[i].upper()
                    i += 1
                # a derived table may name its columns: (SELECT …) t (A1, A2)
                if item.derived and i < n and toks[i] == "(":
                    i = skip_paren(i)
                out.append(item)
                expect_table = False
                continue
            # after a table reference
            if tok == ",":
                expect_table = True
                join_words = (",",)
                i += 1
                continue
            if is_join_word(i):
                words = []
                while is_join_word(i):
                    words.append(toks[i].upper())
                    i += 1
                join_words = tuple(words)
                expect_table = True
                continue
            if is_ident(i) and u in ("ON", "USING"):
                item = out[-1]
                i += 1
                start = i
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
                if u == "USING":
                    item.using = True
                else:
                    item.on = (
                        char_at[start] if start < n else end_char,
                        char_at[i] if i < n else end_char,
                    )
                continue
            if tok == ")":
                return out, ("a ')' with no open paren" if top else None)
            if is_ident(i) and u in _FROM_END:
                return out, None
            return out, f"'{tok}' after a table reference"
        if expect_table:
            return out, "a FROM list that ends after a comma or JOIN"
        return out, None

    i = 0
    while i < n:
        if is_ident(i) and toks[i].upper() == "FROM":
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
            found, prob = parse_list(i + 1, encl[i] == -1)
            items.extend(found)
            if prob and problem is None:
                problem = _FROM_LIST_PROBLEM.format(what=prob)
        i += 1
    items.sort(key=lambda it: it.tok)
    return items, problem


def _scan_from_lists(
    cleaned: str, with_positions: bool = False
) -> tuple[list, str | None]:
    """Every relation name in table position (the single FROM walk's items,
    derived tables left out), in order of appearance, plus the walk's problem
    message if a FROM list could not be read to its end."""
    items, problem = _from_items(cleaned)
    named = [it for it in items if not it.derived]
    if with_positions:
        return [(it.char, it.name) for it in named], problem
    return [it.name for it in named], problem


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
# Predicate rules — a WHITELIST (rewritten after the Fable review of 21 Oct
# 2026, B1–B4 / H1 / M1 / M2): the statement is split into SELECT blocks
# (outer query, each UNION branch, each CTE body, derived table and subquery);
# a block that reads a windowed table is accepted only if that table's alias
# carries, as a DIRECT top-level AND conjunct of the block's WHERE or of the
# ON of an INNER / comma join (never an outer join's ON — B2; never HAVING or
# the select list), a bare predicate of exactly one of these forms:
#   alias.KEY = 'literal'            alias.KEY IN ('literal', …)   (limit as signed)
#   alias.DATE BETWEEN lit AND lit   alias.DATE >= lit AND alias.DATE <= lit
# (DATE 'x' / TIMESTAMP 'x' prefixes read; plain grouping parens around one
# such predicate are fine). Nothing wrapped around or inside it — no CASE,
# IIF, COALESCE, IS FALSE/TRUE, = FALSE, NOT, function, arithmetic or OR
# (B3: a comparison that restricts nothing counted as the key). Literals:
# string keys are quoted, non-empty strings (M1: an unquoted number makes
# Firebird convert the column, not the literal, and scan; M2: '' is a shared
# junk TRACKNO); MANIFEST is a positive integer (B4: MANIFEST = 0 is the
# no-manifest sentinel on ~41% of EVENT). A bare column (no alias) is accepted
# only in a single-table block. Ranges are inclusive: BETWEEN a AND b =
# (b - a) + 1 days; >= a AND < b = b - a. The check lives after the allowlist,
# identifier and star gates and is driven by this dict (the suite proves
# emptying it lets an unwindowed statement through — Fable F3's lesson).
WINDOWED: dict[str, dict] = {
    "ROUTING": {
        "keys": {"WAYBILL": 100, "MANIFEST": 20},  # key column -> max IN-list literals
        "key_only": ("MANIFEST",),  # S2: only ever = / IN — a range changes the plan
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
            "every SELECT that reads ROUTING must carry, as a direct AND conjunct of "
            "its WHERE or of an inner join's ON, a bare key (WAYBILL = 'quoted "
            "literal' or IN (up to 100); MANIFEST = positive integer or IN (up to "
            "20)) or a bare window (AGENTDATE BETWEEN two literal dates or >= and "
            "<= literal dates, at most 31 days) on the ROUTING alias — nothing "
            "wrapped around or inside it, the key or date range outside any OR, not "
            "under NOT, not in an outer join's ON; MANIFEST may appear only as such a "
            "key (a manifest range is not supported); BOOKDATE, "
            "AGENT, hub, MTYPE and STATUS are filters only; and wherever ROUTING is "
            "read, every VIEW_WBANALYSE, MANIFEST or AGENTDRIVER in the statement "
            "must carry its own key the same way (WAYBILL / MANIFEST / AGENT = or "
            "IN, or a WAYDATE range of at most 31 days on the view) (QT-000007 "
            "line 4, measured 21 Oct 2026)"
        ),
    },
    "VIEW_EVENTSCANS": {
        "keys": {"WAYBILL": 100, "TRACKNO": 100, "MANIFEST": 20},
        "key_only": ("MANIFEST",),  # S2: only ever = / IN — a range changes the plan
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
            "every SELECT that reads VIEW_EVENTSCANS must carry, as a direct AND "
            "conjunct of its WHERE or of an inner join's ON, a bare key (WAYBILL or "
            "TRACKNO = 'quoted literal' or IN (up to 100); MANIFEST = positive "
            "integer or IN (up to 20)) or a bare window (EVENTDATE BETWEEN two "
            "literal dates or >= and <= literal dates, at most 3 days) on its alias "
            "— nothing wrapped around or inside it, the key or date range outside any "
            "OR, not under NOT, not in an outer join's ON; MANIFEST may appear only as "
            "such a key (a manifest range is not supported); "
            "WAYDATE, ACCNUM, NAME, HUB, USERNAME and AGENTNAME are filters only — "
            "the view is for waybill and manifest lookups; a scans-by-type-over-a-"
            "date-range question is the event-counts tool, quoted separately; and "
            "wherever the view is read, every VIEW_WBANALYSE, MANIFEST or "
            "AGENTDRIVER in the statement must carry its own key the same way "
            "(QT-000007 line 4, measured 21 Oct 2026)"
        ),
    },
}

# Sixth review S2 (22 Oct 2026): a MANIFEST comparison that is not a key, beside
# a window, made Firebird AND a bitmap over the whole EV_MANIFEST / RO_MANIFEST
# index — `v.EVENTDATE = '2026-10-21' AND v.MANIFEST > 0` (a one-day window)
# planned INDEX (EV_EVENTDATE, EV_MANIFEST) and ran past the cap; the fifth
# review measured the ROUTING twin at 5.8 s. The window bounds one index, not
# the plan, so on the two windowed tables MANIFEST may appear ONLY as a valid key.
_KEY_ONLY_HINT = (
    "{ref} may appear on {table} only as a key ({ref} = a positive integer or {ref} IN "
    "(up to {limit})) — {what} is not a key, and a manifest range is not supported: any "
    "other comparison on MANIFEST makes Firebird AND a bitmap over the whole MANIFEST "
    "index beside the window (a one-day EVENTDATE window with MANIFEST > 0 ran past the "
    "15 s cap on 22 Oct 2026) — drop the MANIFEST condition or write it as a key"
)

_MANIFEST_HINT = (
    "manifest numbers repeat across branches and leg types (37733 is 133 rows "
    "by MANIFEST alone, 124 with MBRANCH = 0 AND MTYPE = 'M') — add MBRANCH and "
    "MTYPE to pin one trip"
)

# Tokens for the window check — unlike the guard's cleaned text, string
# literals are KEPT (the dates and keys live in them); comments are blanked.
_W_TOKEN = re.compile(
    r"(?i:STARTING\s+WITH)"  # one operator token (fourth review Q2) — never a clause end
    r"|'(?:[^']|'')*'"
    r"|[A-Za-z_][A-Za-z0-9_$]*"
    r"|\d+(?:\.\d+)?"
    r"|~=|\^=|!=|<>|<=|>=|~<|\^<|~>|\^>|!<|!>|\|\||[=<>()*,.?+\-/]"
    r"|[^\s]"  # anything else is a token too — never silently dropped (review R4)
)
_NOT_EQUAL_OPS = {"<>", "!=", "~=", "^="}
_NEGATED_RANGE_OPS = {"~<", "^<", "~>", "^>", "!<", "!>"}
_SET_OPS = {"UNION"}  # Firebird 3 has no EXCEPT / INTERSECT (fifth review F1)
_OUTER = {"LEFT", "RIGHT", "FULL"}
_JOIN_KW = {"JOIN", "INNER", "CROSS", "NATURAL"} | _OUTER
# Keywords that end a FROM list or a WHERE / ON clause at the block level.
_CLAUSE_END = {
    "WHERE",
    "GROUP",
    "HAVING",
    "ORDER",
    "ROWS",
    "FETCH",
    "OFFSET",
    "PLAN",
    "FOR",
    "WITH",
} | _SET_OPS
_DATE_PREFIX = {"DATE", "TIMESTAMP"}
_LO_OPS = {">=", ">"}
_HI_OPS = {"<=", "<"}


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


def _w_tokens_pos(sql: str) -> tuple[list[tuple[str, str]], list[int]]:
    """(text, kind) with kind in LIT / NUM / ID / P (anything else), plus the
    character offset each token starts at — the offsets are what ties these
    tokens to the FROM walk's items (the walk runs on the literal-blanked
    text, which keeps every offset)."""
    toks = []
    starts = []
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
        starts.append(m.start())
    return toks, starts


def _w_tokens(sql: str) -> list[tuple[str, str]]:
    """(text, kind) with kind in LIT / NUM / ID / P (anything else)."""
    return _w_tokens_pos(sql)[0]


def _paren_structure(toks):
    """group[i] = index of the innermost '(' enclosing token i (-1 at top);
    match[open] = close; is_sub[open] = the paren opens a SELECT."""
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
    """The query block paren a token belongs to: the innermost enclosing
    paren that opens a SELECT, or -1 for the outer statement. Grouping
    parens are skipped."""
    g = group[i]
    while g != -1 and not is_sub.get(g, False):
        g = group[g]
    return g


def _parse_date(text):
    """'YYYY-MM-DD' (optionally followed by a time) -> date, else None."""
    try:
        return _dt.date.fromisoformat(text.strip()[:10])
    except ValueError:
        return None


def _days(n: int) -> str:
    return "1 day" if n == 1 else f"{n} days"


# --- SELECT blocks ----------------------------------------------------------------
# The statement is split into SELECT blocks: every SELECT — the outer query,
# each UNION/EXCEPT/INTERSECT branch, each CTE body, each derived table, each
# scalar / IN / EXISTS subquery — is its own block with its own FROM list and
# its own WHERE. Fable review B1 (21 Oct 2026): UNION branches shared one
# scope, so a key on one alias covered every branch and the second branch
# planned a NATURAL scan.


class _Ref:
    __slots__ = ("alias", "derived", "is_cte", "kind", "name")

    def __init__(self, name, alias, kind, is_cte=False, derived=False):
        self.name, self.alias, self.kind = name, alias, kind
        self.is_cte, self.derived = is_cte, derived


class _Block:
    __slots__ = (
        "end",
        "g",
        "n",
        "ons",
        "or_clauses",
        "refs",
        "start",
        "unsupported",
        "where",
    )

    def __init__(self, n, g, start, end):
        self.n, self.g, self.start, self.end = n, g, start, end
        self.refs: list[_Ref] = []
        self.where: list[list[int]] = []  # conjuncts: lists of token indices
        self.ons: list[tuple[str, list[list[int]]]] = []  # (join kind, conjuncts)
        self.unsupported: str | None = None
        self.or_clauses: list[str] = []  # clauses with a top-level OR (R3)


def _blocks(toks, group, match, is_sub):
    out = []
    n = len(toks)
    for s, (t, k) in enumerate(toks):
        if k != "ID" or t.upper() != "SELECT":
            continue
        g = group[s]
        limit = match.get(g, n) if g != -1 else n
        e = s + 1
        while e < limit:
            if group[e] == g and toks[e][1] == "ID" and toks[e][0].upper() in _SET_OPS:
                break
            e += 1
        out.append(_Block(len(out) + 1, g, s, e))
    return out


def _level_tokens(block, toks, group, is_sub):
    """Indices of the block's own tokens: at the block's paren level, outside
    any nested paren (nested parens appear as their '(' only)."""
    g = block.g
    idx = []
    i = block.start
    while i < block.end:
        if group[i] == g:
            idx.append(i)
        i += 1
    return idx


def _split_conjuncts(level_idx, toks, group, match):
    """Split a clause's level tokens on AND into conjuncts, keeping each
    conjunct as the full token range (nested parens included) it spans. The
    AND of a BETWEEN is part of its conjunct. Returns (conjuncts, has_or):
    with a top-level OR present the clause is `a OR (b AND c)` in Firebird's
    precedence, so NONE of its conjuncts bounds the read (review R3) — the
    caller treats the clause as having no conjuncts."""
    conjs: list[list[int]] = []
    cur: list[int] = []
    between = False
    has_or = False
    case_depth = 0  # CASE … END is an opaque span (review T1): its ANDs and
    #                 ORs sit at this level but belong to the CASE, so a key
    #                 inside one must never escape as a bare conjunct
    for i in level_idx:
        t, k = toks[i]
        u = t.upper() if k == "ID" else t
        if k == "ID" and u == "CASE":
            case_depth += 1
        elif k == "ID" and u == "END" and case_depth:
            case_depth -= 1
        if case_depth:
            cur.append(i)
            continue
        if k == "ID" and u == "OR":
            has_or = True
        if k == "ID" and u == "AND" and not between:
            if cur:
                conjs.append(cur)
            cur = []
            continue
        if k == "ID" and u == "BETWEEN":
            between = True
        elif k == "ID" and u == "AND" and between:
            between = False
        cur.append(i)
    if case_depth:
        raise GuardError(
            "a CASE without a matching END — the window check cannot tell where the "
            "expression ends; write CASE … END in full"
        )
    if cur:
        conjs.append(cur)
    # expand each conjunct to the full contiguous range it covers
    full = []
    for c in conjs:
        a, b = c[0], c[-1]
        if toks[b][0] == "(" and toks[b][1] == "P":
            b = match.get(b, b)
        full.append(list(range(a, b + 1)))
    return full, has_or


def _clause_region(level_idx, start_pos, toks, stop_on_join=False):
    """Level tokens from start_pos (exclusive) up to the next clause-ending
    keyword (and, for ON clauses, the next join keyword)."""
    region = []
    for i in level_idx:
        if i <= start_pos:
            continue
        t, k = toks[i]
        if stop_on_join and t == "," and k == "P":
            break  # a comma-listed table after JOIN … ON (the R1 shape)
        if k == "ID":
            u = t.upper()
            is_function = (
                u in ("LEFT", "RIGHT") and i + 1 < len(toks) and toks[i + 1][0] == "("
            )
            if u in _CLAUSE_END or (stop_on_join and u in _JOIN_KW and not is_function):
                break
        region.append(i)
    return region


_UNATTRIBUTED = (
    "{what} is read somewhere the window check could not attribute to a SELECT "
    "block — write a plain FROM / JOIN … ON list"
)


def _attribute_items(items, blocks, toks, starts, group, match, is_sub, ctes):
    """Place every item of the single FROM walk in exactly one SELECT block,
    by character offset, and fill block.refs / block.ons from it. REFUSES —
    never skips — an item that lands on a token the window tokenizer does not
    see or inside no block (sixth review S1). The walk and this attribution
    are the only readers of table position: whatever the allowlist saw, the
    window check judges."""
    at = {s: i for i, s in enumerate(starts)}
    by_scope: dict[int, list] = {}
    for b in blocks:
        by_scope.setdefault(b.g, []).append(b)
    levels: dict[int, list[int]] = {}
    for it in items:
        what = it.name or "a derived table"
        wi = at.get(it.char)
        placed = wi is not None and (
            (it.derived and toks[wi] == ("(", "P"))
            or (
                not it.derived
                and toks[wi][1] == "ID"
                and toks[wi][0].upper() == it.name
            )
        )
        if not placed:
            raise GuardError(_UNATTRIBUTED.format(what=what))
        scope = _scope_of(wi, group, is_sub)
        block = next(
            (b for b in by_scope.get(scope, ()) if b.start <= wi < b.end), None
        )
        if block is None:
            raise GuardError(_UNATTRIBUTED.format(what=what))
        kind = it.kind
        block.refs.append(
            _Ref(
                it.name,
                it.alias or it.name,
                kind,
                is_cte=(not it.derived and it.name in ctes),
                derived=it.derived,
            )
        )
        if kind == "natural":
            block.unsupported = (
                block.unsupported or "a NATURAL join or a join without JOIN"
            )
        elif it.using:
            block.unsupported = block.unsupported or "a USING join"
        elif it.on is not None:
            level = levels.get(block.n)
            if level is None:
                level = levels[block.n] = _level_tokens(block, toks, group, is_sub)
            lo, hi = it.on
            region = [i for i in level if lo <= starts[i] < hi]
            cs, has_or = _split_conjuncts(region, toks, group, match)
            if has_or:
                block.or_clauses.append(f"the ON of the {kind.upper()} join")
                cs = []
            block.ons.append((kind, cs))
        elif kind in ("inner", "left", "right", "full"):
            block.unsupported = block.unsupported or "a JOIN without ON"


def _parse_where(block, toks, group, match, is_sub):
    """Fill block.where from the block's own WHERE clause; flatten the ONs."""
    level = _level_tokens(block, toks, group, is_sub)
    where_i = next(
        (i for i in level if toks[i][1] == "ID" and toks[i][0].upper() == "WHERE"), None
    )
    if where_i is not None:
        region = _clause_region(level, where_i, toks)
        cs, has_or = _split_conjuncts(region, toks, group, match)
        if has_or:
            block.or_clauses.append("the WHERE clause")
            cs = []
        block.where = _flatten(cs, toks, group, match, is_sub)
    block.ons = [
        (kind, _flatten(cs, toks, group, match, is_sub)) for kind, cs in block.ons
    ]


def _attributed_table_refs(sql: str) -> list[tuple[str, int]]:
    """(name, SELECT block number) for every item of the FROM walk — the
    attribution the window check relies on, exposed so the suite can assert
    that every table the allowlist scan sees is judged in some block."""
    sql = sql.rstrip().removesuffix(";")
    cleaned = _strip_literals_and_comments(sql)
    items, problem = _from_items(cleaned)
    if problem:
        raise GuardError(problem)
    toks, starts = _w_tokens_pos(sql)
    group, match, is_sub = _paren_structure(toks)
    ctes = {m.group(1).upper() for m in _CTE_NAME.finditer(cleaned)}
    blocks = _blocks(toks, group, match, is_sub)
    _attribute_items(items, blocks, toks, starts, group, match, is_sub, ctes)
    return [(r.name or "(derived)", b.n) for b in blocks for r in b.refs]


def _flatten(conjs, toks, group, match, is_sub):
    """Plain grouping parentheses around AND-ed predicates are just grouping:
    `(a AND b) AND c` -> a, b, c. A paren group holding an OR stays whole."""
    out = []
    for c in conjs:
        if (
            c
            and toks[c[0]][0] == "("
            and toks[c[0]][1] == "P"
            and match.get(c[0]) == c[-1]
            and not is_sub.get(c[0])
        ):
            inner_level = [i for i in c[1:-1] if group[i] == c[0]]
            inner, inner_or = _split_conjuncts(inner_level, toks, group, match)
            if inner_or:
                out.append(c)  # an OR'd group is opaque — never a bound
                continue
            if len(inner) > 1 or (len(inner) == 1 and inner[0] != c[1:-1]):
                out.extend(_flatten(inner, toks, group, match, is_sub))
                continue
        out.append(c)
    return out


# --- the whitelist judge ------------------------------------------------------------


def _ref_at(toks, c, j):
    """alias.COL or COL at conjunct offset j -> (alias|None, COL, next offset)."""
    if (
        j + 2 < len(c)
        and toks[c[j]][1] == "ID"
        and toks[c[j + 1]][0] == "."
        and toks[c[j + 2]][1] == "ID"
    ):
        return toks[c[j]][0].upper(), toks[c[j + 2]][0].upper(), j + 3
    if j < len(c) and toks[c[j]][1] == "ID":
        return None, toks[c[j]][0].upper(), j + 1
    return None, None, j


def _lit_at(toks, c, j):
    """A bare literal at offset j: ('str', text) / ('num', text) / ('date', text)
    with the next offset, or (None, None, j). DATE 'x' / TIMESTAMP 'x' count
    as 'date'-prefixed strings."""
    if j >= len(c):
        return None, None, j
    t, k = toks[c[j]]
    if k == "LIT":
        return "str", t, j + 1
    if k == "NUM":
        return "num", t, j + 1
    if (
        k == "ID"
        and t.upper() in _DATE_PREFIX
        and j + 1 < len(c)
        and toks[c[j + 1]][1] == "LIT"
    ):
        return "date", toks[c[j + 1]][0], j + 2
    return None, None, j


def _bare_shape(toks, c, group, match, is_sub):
    """Match a conjunct (token index list) against the exact whitelist and
    return (alias, col, kind, values) or None. kinds: eq / in / between / lo / hi.
    values: [(littype, text), ...]. A conjunct that is one plain paren group
    around a single bare predicate matches through it."""
    if not c:
        return None
    # ( bare ) — plain grouping parentheses, nothing else in the conjunct
    if (
        toks[c[0]][0] == "("
        and toks[c[0]][1] == "P"
        and match.get(c[0]) == c[-1]
        and not is_sub.get(c[0])
    ):
        inner_level = [i for i in c[1:-1] if group[i] == c[0]]
        inner, inner_or = _split_conjuncts(inner_level, toks, group, match)
        if len(inner) == 1 and not inner_or:
            return _bare_shape(toks, inner[0], group, match, is_sub)
        return None
    alias, col, j = _ref_at(toks, c, 0)
    if col is None or j >= len(c):
        return None
    op = toks[c[j]]
    u = op[0].upper()
    if op[1] == "P" and u == "=":
        lt, lv, j2 = _lit_at(toks, c, j + 1)
        if lt and j2 == len(c):
            return alias, col, "eq", [(lt, lv)]
        return None
    if op[1] == "P" and (u in _LO_OPS or u in _HI_OPS):
        lt, lv, j2 = _lit_at(toks, c, j + 1)
        if lt and j2 == len(c):
            return alias, col, ("lo" if u in _LO_OPS else "hi"), [(lt, lv, u)]
        return None
    if op[1] == "ID" and u == "BETWEEN":
        lt1, lv1, j2 = _lit_at(toks, c, j + 1)
        if not lt1 or j2 >= len(c) or toks[c[j2]][0].upper() != "AND":
            return None
        lt2, lv2, j3 = _lit_at(toks, c, j2 + 1)
        if lt2 and j3 == len(c):
            return alias, col, "between", [(lt1, lv1), (lt2, lv2)]
        return None
    if op[1] == "ID" and u == "IN":
        if j + 1 >= len(c):
            return None
        o = c[j + 1]
        if (
            toks[o][0] != "("
            or toks[o][1] != "P"
            or is_sub.get(o)
            or match.get(o) != c[-1]
        ):
            return None
        items = []
        expect_item = True
        for i in c[j + 2 : -1]:
            t, k = toks[i]
            if group[i] != o:
                return None  # something nested inside the list
            if expect_item:
                if k == "LIT":
                    items.append(("str", t))
                elif k == "NUM":
                    items.append(("num", t))
                else:
                    return None
                expect_item = False
            else:
                if t != "," or k != "P":
                    return None
                expect_item = True
        if expect_item or not items:
            return None
        return alias, col, "in", items
    return None


def _why_not(toks, c, group, match, is_sub, ref_label):
    """One plain reason why a conjunct that mentions the alias is not a bound."""
    text = [toks[i] for i in c]
    ids = {t.upper() for t, k in text if k == "ID"}
    ops = {t for t, k in text if k == "P"}
    if any(is_sub.get(i) for i in c if toks[i][0] == "("):
        return f"{ref_label} is compared through a subquery — write literal values"
    if "?" in ops:
        return f"{ref_label} is compared to a parameter (?) — write the literal value"
    if any(x.startswith("CURRENT_") for x in ids):
        return f"{ref_label} is compared with CURRENT_DATE arithmetic — write literal dates 'YYYY-MM-DD'"
    if "OR" in ids:
        return f"{ref_label} sits inside an OR — an OR widens the read; put alternatives in IN (…)"
    if "NOT" in ids:
        return f"{ref_label} is negated (NOT) — a negation does not bound the read"
    if (
        "LIKE" in ids
        or "STARTING" in ids
        or "CONTAINING" in ids
        or "SIMILAR" in ids
        or any(t.upper().startswith("STARTING") for t, k in text if k == "P")
    ):
        return f"{ref_label} LIKE / STARTING WITH … is not a key — use = or IN (…)"
    if ops & _NOT_EQUAL_OPS:
        return f"{ref_label} <> / != / ~= / ^= … is not a key — use = or IN (…)"
    if ops & _NEGATED_RANGE_OPS:
        return (
            f"{ref_label} ~< / ~> / ^< / ^> / !< / !> … is not a date range — use BETWEEN "
            "or >= and <= literal dates"
        )
    if (
        "IS" in ids
        or "CASE" in ids
        or "IIF" in ids
        or "COALESCE" in ids
        or "FALSE" in ids
        or "TRUE" in ids
    ):
        return (
            f"{ref_label} is wrapped (CASE / IIF / COALESCE / IS / = FALSE) — a wrapped comparison "
            "restricts nothing; write the bare predicate as its own AND conjunct"
        )
    if "ANY" in ids or "SOME" in ids or "ALL" in ids:
        return f"{ref_label} = ANY / SOME / ALL is not a key — use = or IN (…)"
    return (
        f"{ref_label} appears in a conjunct that is not a bare key or window predicate "
        "(a function call, arithmetic, concatenation or an unsupported form) — write "
        f"{ref_label} = 'literal', IN (…), BETWEEN two literal dates, or >= and <= literal dates"
    )


def _is_join_equality(toks, c):
    """`a.X = b.Y` with two different aliases — a join condition, not a bound."""
    if len(c) != 7 or toks[c[3]] != ("=", "P"):
        return False
    a1, _col1, j1 = _ref_at(toks, c, 0)
    a2, _col2, j2 = _ref_at(toks, c, 4)
    return a1 is not None and a2 is not None and a1 != a2 and j1 == 3 and j2 == 7


def _mentions(toks, c, alias, col):
    """Does the conjunct contain alias.col (or bare col when alias is None)?"""
    for j in range(len(c)):
        a, cc, _ = _ref_at(toks, c, j)
        if cc == col and (a == alias or (alias is None and a is None)):
            if j >= 1 and toks[c[j - 1]][0] == ".":
                continue
            return True
    return False


def _judge(table, spec, alias, conjs, outer_conjs, single):
    """Whitelist judgement for one table reference: qualifying descriptions
    and the reasons for near-misses. `conjs` are the direct AND conjuncts of
    the block's WHERE and inner-join ONs; `outer_conjs` those of outer-join
    ONs (never bounds — reported). `single` = the block has one table ref,
    so a bare column may be attributed to it."""
    label = f"{alias}." if alias.upper() != table else ""
    alias_u = alias.upper()
    qualifying: list[str] = []
    reasons: list[str] = []
    hard: list[str] = []  # refusals that stand even when a key or window qualifies
    key_only = spec.get("key_only", ())
    lows: list[_dt.date] = []
    highs: list[_dt.date] = []
    pins_seen: set[str] = set()
    interest = (
        set(spec["keys"])
        | ({spec["date"]} if spec["date"] else set())
        | set(spec["filters_only"])
        | set(spec["pins"])
    )
    toks, group, match, is_sub = spec["_ctx"]

    def mine(shape):
        a = shape[0]
        return a == alias_u or (a is None and single)

    for c in conjs:
        shape = _bare_shape(toks, c, group, match, is_sub)
        if shape is not None and mine(shape):
            _a, col, kind, values = shape
            ref = f"{label}{col}"
            if col in spec["pins"]:
                pins_seen.add(col)
            if col in spec["keys"]:
                limit = spec["keys"][col]
                vals = values if kind == "in" else (values if kind == "eq" else None)
                if vals is None:
                    if col in key_only:
                        hard.append(
                            _KEY_ONLY_HINT.format(
                                ref=ref,
                                table=table,
                                limit=limit,
                                what=f"{ref} compared with {values[0][2] if kind in ('lo', 'hi') else 'BETWEEN'}",
                            )
                        )
                    reasons.append(
                        f"{ref} {('>=' if kind == 'lo' else '<=')} … is not a key — use = or IN (…)"
                    )
                    continue
                bad = _key_literal_problem(col, vals, ref)
                if col in key_only and (bad or (kind == "in" and len(vals) > limit)):
                    hard.append(
                        _KEY_ONLY_HINT.format(
                            ref=ref,
                            table=table,
                            limit=limit,
                            what=bad or f"{ref} IN (…) has {len(vals)} literals",
                        )
                    )
                if bad:
                    reasons.append(bad)
                elif kind == "in" and len(vals) > limit:
                    reasons.append(
                        f"{ref} IN (…) has {len(vals)} literals — the limit is {limit}"
                    )
                elif kind == "in":
                    qualifying.append(f"keyed by {col} IN ({len(vals)} literals)")
                else:
                    qualifying.append(f"keyed by {col} (1 literal)")
            elif spec["date"] and col == spec["date"]:
                if kind in ("eq", "between"):
                    dates = [
                        _parse_date(v[1]) if v[0] in ("str", "date") else None
                        for v in values
                    ]
                    if any(d is None for d in dates):
                        reasons.append(
                            f"{ref} compares to a date that is not 'YYYY-MM-DD' — write dates as 'YYYY-MM-DD'"
                        )
                        continue
                    lo_d, hi_d = dates[0], dates[-1]
                    width = (hi_d - lo_d).days + 1
                    if width <= 0:
                        reasons.append(
                            f"the {ref} bounds are reversed ({lo_d}..{hi_d})"
                        )
                    elif width > spec["max_days"]:
                        reasons.append(
                            f"the {ref} range is {width} days ({lo_d}..{hi_d}) — the limit is {spec['max_days']} days"
                        )
                    else:
                        qualifying.append(
                            f"{col} window {lo_d}..{hi_d} ({_days(width)})"
                        )
                elif kind == "in":
                    reasons.append(
                        f"{ref} IN (…) is a list of dates, not a window — use BETWEEN two "
                        "literal dates or >= and <= literal dates"
                    )
                    continue
                else:
                    lt, lv, op = values[0]
                    d = _parse_date(lv) if lt in ("str", "date") else None
                    if d is None:
                        reasons.append(
                            f"{ref} compares to a date that is not 'YYYY-MM-DD' — write dates as 'YYYY-MM-DD'"
                        )
                        continue
                    if kind == "lo":
                        lows.append(d + _dt.timedelta(days=1) if op == ">" else d)
                    else:
                        highs.append(d - _dt.timedelta(days=1) if op == "<" else d)
            elif col in spec["filters_only"]:
                why = spec["filter_why"].get(col)
                reasons.append(
                    f"{col} is a filter, not a key or window on {table}"
                    + (f" — {why}" if why else "")
                )
            continue
        # not a bare shape on this alias — is the alias's key/date/filter mentioned?
        for col in key_only:
            if _is_join_equality(toks, c):
                continue  # m.MANIFEST = r.MANIFEST joins; it is no range on either side
            if _mentions(toks, c, alias_u, col) or (
                single and _mentions(toks, c, None, col)
            ):
                hard.append(
                    _KEY_ONLY_HINT.format(
                        ref=f"{label}{col}",
                        table=table,
                        limit=spec["keys"][col],
                        what="a comparison other than = / IN, or one wrapped in an expression",
                    )
                )
        ordered = sorted(
            set(spec["keys"]) | ({spec["date"]} if spec["date"] else set())
        ) + sorted(spec["filters_only"])
        for col in ordered:
            if _mentions(toks, c, alias_u, col) or (
                single and _mentions(toks, c, None, col)
            ):
                if col in spec["filters_only"]:
                    if shape is not None:
                        continue
                    why = spec["filter_why"].get(col)
                    reasons.append(
                        f"{col} is a filter, not a key or window on {table}"
                        + (f" — {why}" if why else "")
                    )
                else:
                    reasons.append(
                        _why_not(toks, c, group, match, is_sub, f"{label}{col}")
                    )
                break
        if (
            not single
            and shape is not None
            and shape[0] is None
            and shape[1] in interest
        ):
            reasons.append(
                f"{shape[1]} is unqualified in a multi-table block — qualify it ({alias}.{shape[1]}) "
                f"so the key or window is on {table}"
            )
    for kind_name, c in outer_conjs:
        shape = _bare_shape(toks, c, group, match, is_sub)
        for col in key_only:
            is_key = (
                shape is not None
                and mine(shape)
                and shape[1] == col
                and shape[2] in ("eq", "in")
                and not _key_literal_problem(col, shape[3], f"{label}{col}")
                and len(shape[3]) <= spec["keys"][col]
            )
            if not is_key and (
                _mentions(toks, c, alias_u, col)
                or (single and _mentions(toks, c, None, col))
            ):
                hard.append(
                    _KEY_ONLY_HINT.format(
                        ref=f"{label}{col}",
                        table=table,
                        limit=spec["keys"][col],
                        what=f"a comparison other than = / IN in the ON of a {kind_name.upper()} JOIN",
                    )
                )
        if (
            shape is not None
            and mine(shape)
            and (shape[1] in spec["keys"] or shape[1] == spec["date"])
        ):
            reasons.append(
                f"{label}{shape[1]} sits in the ON of a {kind_name.upper()} JOIN — an outer join's ON "
                f"does not filter {table}; move it to WHERE"
            )
    if lows or highs:
        ref = f"{label}{spec['date']}"
        if not lows or not highs:
            reasons.append(
                f"only one bound on {ref} — give both ends (>= and <= literal dates)"
            )
        else:
            lo_d, hi_d = max(lows), min(highs)
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
    return qualifying, reasons, hard


def _key_literal_problem(col, vals, ref):
    """Key literal rules (review M1, M2, B4): string keys are quoted non-empty
    strings; MANIFEST is a positive integer; AGENT likewise."""
    if col in ("WAYBILL", "TRACKNO"):
        for lt, lv in vals:
            if lt != "str":
                return (
                    f"{ref} = {lv} is an unquoted number — Firebird then converts the column, not the "
                    f"literal, and the index cannot drive it; write {ref} = '{lv}'"
                )
            if not lv.strip():
                return f"{ref} = '' (blank) is a shared junk key, not a waybill or tracking number"
        return None
    for lt, lv in vals:
        if lt != "num" or not lv.isdigit():
            return f"{ref} must be a positive integer literal (got {lv!r})"
        if int(lv) <= 0:
            return (
                f"{ref} = {lv} is the no-manifest sentinel, not a key — about 41% of EVENT rows and "
                "6.6% of ROUTING rows carry MANIFEST = 0 (measured 21 Oct 2026); a manifest number "
                "must be a positive integer"
            )
    return None


# --- join-bound relations -------------------------------------------------------
# Akha's call on the 21 Oct join finding, widened by review H1: if ANY block
# reads a windowed table, EVERY block that reads one of these relations must
# key that relation's alias by the same bare-conjunct rule — the plans read
# 21 Oct 2026 drive such a join from the big side with a NATURAL scan unless
# its own column is bounded (only a single '=' on the ROUTING side propagates,
# and the fence must not depend on the optimizer). VIEW_WBANALYSE may instead
# carry a WAYDATE range (WA_WAYDATE, the daily extraction's path). AGENTDRIVER
# has no MANIFEST column (AGENTDRIVER, AGENT, DRIVER, FROMDATE, FROMTIME,
# USERCODE, LOADLVL, ROUTE), so its key is AGENT. Without a windowed table in
# the statement these relations stay as they were on Day 5.
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

_CONJUNCT_RULE = (
    "a key or window must be a direct AND conjunct of that SELECT block's WHERE "
    "(or of the ON of an INNER / comma join; never an outer join's ON, never "
    "HAVING or the select list), bare — nothing around or inside it"
)


_OR_RULE = (
    "{clause} has a top-level OR — in Firebird AND binds tighter than OR, so every "
    "predicate in it sits inside an OR and none bounds the read; put the key or "
    "window outside the OR (alternatives go in IN (…)), or write separate queries"
)


def _check_windowed(
    sql: str, tables: list[str], windows: list[str] | None, items=None
) -> None:
    """Whitelist: every SELECT block that reads a windowed table must key or
    window that table's alias with an exact bare conjunct; and if any block
    reads a windowed table, every block reading a _JOIN_BOUND relation must
    key it the same way. Describe what was applied (into `windows`) or refuse
    naming the block, the alias and what was missing. Any internal error in
    the check is itself a refusal (review R6) — never an accepted statement,
    never a tool error. `items` are the FROM walk's items as the allowlist
    scan saw them (computed here if not given) — every one of them is
    attributed to a SELECT block or the statement refuses, windowed or not."""
    specs = {t: WINDOWED[t] for t in tables if t in WINDOWED}
    scratch: list[str] = []
    try:
        _check_windowed_blocks(sql, specs, scratch, items)
    except GuardError:
        raise
    except Exception as e:
        rule = next(iter(specs.values()))["rule"] if specs else _CONJUNCT_RULE
        raise GuardError(
            f"the window check could not parse this statement ({type(e).__name__}) — "
            "write the WHERE as plain AND-ed predicates on the table's alias. "
            f"Rule: {rule}."
        ) from None
    if windows is not None:
        windows.extend(scratch)


def _check_windowed_blocks(sql: str, specs: dict, windows: list[str], items) -> None:
    sql = sql.rstrip().removesuffix(";")  # one trailing semicolon is tolerated upstream
    toks, starts = _w_tokens_pos(sql)
    group, match, is_sub = _paren_structure(toks)
    cleaned = _strip_literals_and_comments(sql)
    ctes = {m.group(1).upper() for m in _CTE_NAME.finditer(cleaned)}
    blocks = _blocks(toks, group, match, is_sub)
    if items is None:
        items, problem = _from_items(cleaned)
        if problem:
            raise GuardError(problem)
    # Sixth review S1: ONE walk. The items the allowlist scan read are placed
    # in their SELECT blocks by offset; an item that cannot be placed refuses
    # the statement here, whether or not a windowed table is involved.
    _attribute_items(items, blocks, toks, starts, group, match, is_sub, ctes)
    if not specs:
        return
    for b in blocks:
        _parse_where(b, toks, group, match, is_sub)
    ctx = (toks, group, match, is_sub)
    many = len(blocks) > 1
    # Review R2: refuse if ANY block could not be parsed, wherever it sits,
    # and if a windowed table the allowlist scan saw was attributed to no
    # block — never judge a partial picture.
    for b in blocks:
        if b.unsupported:
            raise GuardError(
                f"SELECT block {b.n} of {len(blocks)} reads through {b.unsupported}, which "
                "the window check does not parse — write a plain FROM / JOIN … ON list. "
                f"Rule: {next(iter(specs.values()))['rule']}."
            )
    seen = {r.name for b in blocks for r in b.refs if not r.is_cte and not r.derived}
    for t in specs:
        if t not in seen:
            raise GuardError(
                f"{t} is read somewhere the window check could not attribute to a SELECT "
                "block — write a plain FROM / JOIN … ON list. "
                f"Rule: {specs[t]['rule']}."
            )

    def where_label(b):
        return f" in SELECT block {b.n} of {len(blocks)}" if many else ""

    def conjunct_sets(b):
        conjs = list(b.where)
        outer = []
        for kind, cs in b.ons:
            if kind in ("inner", "comma", "cross"):
                conjs.extend(cs)
            else:
                outer.extend((kind, c) for c in cs)
        return conjs, outer

    any_windowed = False
    for b in blocks:
        for ref in b.refs:
            if ref.is_cte or ref.derived or ref.name not in specs:
                continue
            any_windowed = True
            if b.unsupported:
                raise GuardError(
                    f"{ref.name}{where_label(b)} is read through {b.unsupported}, which the "
                    f"window check does not parse — write a plain FROM / JOIN … ON list. "
                    f"Rule: {specs[ref.name]['rule']}."
                )
            spec = dict(specs[ref.name], _ctx=ctx)
            conjs, outer = conjunct_sets(b)
            alias_text = _alias_text(toks, b, ref)
            qualifying, reasons, hard = _judge(
                ref.name, spec, alias_text, conjs, outer, len(b.refs) == 1
            )
            label = (
                f"{ref.name} (alias {alias_text})"
                if ref.alias != ref.name
                else ref.name
            )
            if hard:
                # Sixth review S2: MANIFEST on a windowed table only as a key —
                # a range beside the window is refused even when a key or
                # window qualifies, because it changes the plan.
                raise GuardError(
                    f"{'; '.join(hard)}{where_label(b)}. Rule: {spec['rule']}."
                )
            if qualifying:
                short = (
                    f"{ref.name} ({_alias_text(toks, b, ref)})"
                    if ref.alias != ref.name
                    else ref.name
                )
                windows.append(f"{short}: " + "; ".join(qualifying))
                continue
            for clause in b.or_clauses:
                reasons.append(_OR_RULE.format(clause=clause))
            detail = f" — found: {'; '.join(reasons)}" if reasons else ""
            raise GuardError(
                f"no key or window on {label}{where_label(b)}{detail}. {_CONJUNCT_RULE}. "
                f"Rule: {spec['rule']}."
            )
    if not any_windowed:
        return
    for b in blocks:
        for ref in b.refs:
            if ref.is_cte or ref.derived or ref.name not in _JOIN_BOUND:
                continue
            if b.unsupported:
                raise GuardError(
                    f"{ref.name}{where_label(b)} is read through {b.unsupported}, which the "
                    "window check does not parse — write a plain FROM / JOIN … ON list."
                )
            spec = dict(_JOIN_BOUND[ref.name], _ctx=ctx)
            conjs, outer = conjunct_sets(b)
            a = _alias_text(toks, b, ref)
            qualifying, reasons, _hard = _judge(
                ref.name, spec, a, conjs, outer, len(b.refs) == 1
            )
            if qualifying:
                continue
            for clause in b.or_clauses:
                reasons.append(_OR_RULE.format(clause=clause))
            windowed_names = sorted(
                {
                    r.name
                    for bb in blocks
                    for r in bb.refs
                    if not r.is_cte and not r.derived and r.name in specs
                }
            )
            detail = f" (found: {'; '.join(reasons)})" if reasons else ""
            raise GuardError(
                f"{ref.name} (alias {a}){where_label(b)} is read in a statement that also reads "
                f"{' / '.join(windowed_names)}, without a key of its own{detail} — "
                f"{spec['fix'].format(a=a)}. Firebird would otherwise scan the {spec['rows']}-row "
                "relation for that join (plans read 21 Oct 2026); the window on "
                f"{' / '.join(windowed_names)} bounds only its own side."
            )


def _alias_text(toks, block, ref):
    """The alias as the user wrote it (for messages); the name itself when none."""
    for i in range(block.start, block.end):
        t, k = toks[i]
        if k == "ID" and t.upper() == ref.alias:
            return t
    return ref.alias


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
    items, from_problem = _from_items(cleaned)
    placed = [(it.char, it.name) for it in items if not it.derived]
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
    _check_windowed(sql, tables, windows, items)
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


class _DeadlineExceeded(TimeoutError):
    """The fetch did not answer inside the wall-clock cap."""


def _run_with_deadline(run, sql: str, deadline_s: float, cancel=cancel_thread):
    """Run `run(sql, (), ROW_CAP + 1, timeout=deadline_s)` in a worker thread
    and wait at most `deadline_s` of wall-clock time. On expiry the worker's
    database connection is cancelled and closed through `cancel` (keyed by
    the worker's thread ident) and _DeadlineExceeded is raised; the worker
    then dies on its dead socket. Anything the worker raised is re-raised."""
    outcome: dict = {}

    def work():
        try:
            outcome["value"] = run(sql, (), ROW_CAP + 1, timeout=deadline_s)
        except BaseException as e:
            outcome["error"] = e

    worker = threading.Thread(target=work, name="open_query-fetch", daemon=True)
    worker.start()
    worker.join(deadline_s)
    if worker.is_alive():
        cancel(worker.ident)
        raise _DeadlineExceeded(f"no answer inside {deadline_s} s")
    if "error" in outcome:
        raise outcome["error"]
    return outcome["value"]


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
        columns, rows = _run_with_deadline(run, sql, TIMEOUT_S)
    except ConnectionError:
        raise
    except Exception as e:
        # The wall-clock deadline raises _DeadlineExceeded; the driver reports
        # a tripped socket timeout as OperationalError "Can not recv() packets"
        # (fbcore._recv_channel), not TimeoutError — observed live 18 Aug when
        # a MAX() over the 3.1M-row view blew a 30s cap. A genuine mid-query
        # disconnect reads the same; either way the query was abandoned, not
        # answered.
        msg = str(e).lower()
        if isinstance(e, (socket.timeout, TimeoutError)) or (
            "timed out" in msg or "can not recv" in msg
        ):
            return _refused(
                f"the query ran past the {TIMEOUT_S} s wall-clock time cap (or the "
                "connection dropped mid-query) and was abandoned: its connection was "
                "cancelled and closed, so Firebird drops the statement when it honours "
                "the cancel or next touches the connection — narrow it "
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
    if (
        _REVENUE_TABLES & set(tables)
        or ("VIEW_WBANALYSE" in tables and _REVENUE_COLUMNS.search(sql))
        or ("ROUTING" in tables and _ROUTING_MONEY.search(sql))
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
