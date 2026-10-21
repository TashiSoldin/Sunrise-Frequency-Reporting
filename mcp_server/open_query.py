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
        "freight system. Full shipment history is a separate quote with a "
        "query plan first — waybill_status answers the last recorded movement."
    ),
    "WAYBILL": (
        "the raw WAYBILL table (3.1M rows, 146 cols) is off the allowlist — "
        "VIEW_WBANALYSE is the sanctioned waybill surface; query that instead."
    ),
    "TRACK": "TRACK (14.1M rows) is off the allowlist — event-family scale.",
    "PAGEEVENT": "PAGEEVENT (12.8M rows) is off the allowlist — event-family scale.",
    "SCANLOG": "SCANLOG (3.8M rows) is off the allowlist — event-family scale.",
    "WAYEVENT": "WAYEVENT (573k rows) is off the allowlist — event-family scale.",
    "VIEW_EVENTSCANS": (
        "VIEW_EVENTSCANS (over the 113M-row EVENT family) is not yet on the "
        "open path — QT-000007 lines 3–4 add it with a waybill or date window "
        "required per query; until that lands, waybill_status answers the "
        "last recorded movement."
    ),
    "CONTENTS": "CONTENTS (7.3M rows) is off the allowlist.",
    "ROUTING": (
        "ROUTING (6.0M rows) is not yet on the open path — QT-000007 lines "
        "3–4 add it with a waybill or date window required per query."
    ),
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
    "EXCEPT",
    "INTERSECT",
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

_CTE_NAME = re.compile(
    r"(?:\bWITH\b|,)\s*(?:RECURSIVE\s+)?([A-Za-z_][A-Za-z0-9_$]*)"
    r"(?:\s*\([^)]*\))?\s+AS\s*\(",
    re.IGNORECASE,
)


# Tokens for the FROM-list scan: identifiers, numbers, parens and commas as
# single tokens, any other run of punctuation as one token (literals and
# comments are already blanked, so they never appear).
_FT = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*|\d+(?:\.\d+)?|[(),]|[^\sA-Za-z0-9_$(),]+")
_JOIN_WORDS = {"JOIN", "INNER", "LEFT", "RIGHT", "FULL", "CROSS", "NATURAL", "OUTER"}
# Keywords that end a FROM list at its own paren depth.
_FROM_END = {
    "WHERE",
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
    "FOR",
    "INTO",
    "WITH",
}
_FROM_LIST_PROBLEM = (
    "the FROM list could not be read to its end ({what}) — the open path refuses "
    "a statement whose table list it cannot be sure of (fail closed); write a "
    "plain FROM / JOIN … ON list of base tables, views and (SELECT …) derived tables"
)


def _scan_from_lists(cleaned: str) -> tuple[list[str], str | None]:
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
    toks = _FT.findall(cleaned)
    n = len(toks)
    found: list[tuple[int, str]] = []  # (position, name)
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
        if tk == "(" and k + 1 < n and toks[k + 1].upper() == "SELECT"
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
                        and toks[i + 1].upper() == "SELECT"
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
                i += 1  # FROM inside a function / expression, not a table list
                continue
            names, prob = parse_list(i + 1, encl[i] == -1)
            found.extend(names)
            if prob and problem is None:
                problem = _FROM_LIST_PROBLEM.format(what=prob)
        i += 1
    found.sort()
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


def check_open_query(sql: str) -> list[str]:
    """Full gate: SELECT-only, no quoted identifiers, every relation in table
    position on the allowlist, no withheld column named anywhere, no
    projection star over a table that has withheld columns. Returns the
    tables referenced; raises GuardError with the reason otherwise."""
    if '"' in sql:
        raise GuardError(
            "quoted identifiers are not supported on the open path — every "
            "Parcel Perfect name is plain uppercase; write it unquoted"
        )
    assert_select_only(sql)
    cleaned = _strip_literals_and_comments(sql)
    if _PLAN_WORD.search(cleaned):
        # Fable re-review R5 (21 Oct 2026): a user PLAN clause beats every
        # index the guard relies on — `… PLAN (R NATURAL)` is a scan on demand.
        raise GuardError(
            "a PLAN clause is not accepted on the open path — the server chooses "
            "the plan; remove it"
        )
    ctes = {m.group(1).upper() for m in _CTE_NAME.finditer(cleaned)}
    names, from_problem = _scan_from_lists(cleaned)
    tables = [t for t in names if t not in ctes]
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

    try:
        tables = check_open_query(sql)
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
                "(EVENT and the other 100M+-row tables are a separate quote)."
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
