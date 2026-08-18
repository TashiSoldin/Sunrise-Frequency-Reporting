"""Open-ended query path — quote line 4's fence (Day 5).

Anything the named tools do not cover, answered from the database directly.
The 3h bought the fence, not per-question logic; the fence is:

- SELECT-only, enforced here before Firebird (sql_guard, plus the read-only
  transaction and the grant-less role behind it);
- a table allowlist — every relation a query touches must be on it, and every
  entry is justified from the 6 Aug schema survey (Database Reference folder);
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

__all__ = ["ALLOWLIST", "check_open_query", "run_open_query", "schema_context"]

# --- caps ---------------------------------------------------------------------
# An open answer is a read of raw rows, not an extract feeding a report — 500
# rows is presentable; more means the question wants an aggregate or a filter.
ROW_CAP = 500
# Socket-level cap on how long we WAIT. Honest limitation: Firebird may keep
# executing an aborted aggregate server-side after the socket closes — the cap
# bounds the answer, not the production load (the quote's deleted-sentence
# lesson). Load stays bounded by the allowlist keeping the 100M+-row tables
# unreachable in the first place.
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
        "sanctioned way to read waybills; the raw WAYBILL table stays off."
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
    "CUSTOMER": "Customer master (1,959 rows) — accounts, names, contact detail.",
    "CONTACT": "Customer contact people (4,591 rows, 18 cols).",
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
}

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
        "VIEW_EVENTSCANS is off the allowlist — it reads over the EVENT family, "
        "which is a separate quote with a query plan first."
    ),
    "CONTENTS": "CONTENTS (7.3M rows) is off the allowlist.",
    "ROUTING": "ROUTING (6.0M rows) is off the allowlist.",
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

_CTE_NAME = re.compile(
    r"(?:\bWITH\b|,)\s*(?:RECURSIVE\s+)?([A-Za-z_][A-Za-z0-9_$]*)"
    r"(?:\s*\([^)]*\))?\s+AS\s*\(",
    re.IGNORECASE,
)


def _referenced_tables(cleaned: str) -> list[str]:
    """Every identifier in table position (after FROM/JOIN, through comma
    lists), uppercased, in order. Derived tables are skipped here — their
    inner FROM/JOIN is reached by the same scan."""
    toks = _TOKEN.findall(cleaned)
    names: list[str] = []
    i, n = 0, len(toks)
    while i < n:
        if toks[i].upper() not in ("FROM", "JOIN"):
            i += 1
            continue
        i += 1
        expect_name = True
        while i < n:
            tok = toks[i]
            u = tok.upper()
            if expect_name:
                if tok == "(" or u in _STOP:
                    break  # derived table / keyword — outer scan continues
                if not _IDENT.fullmatch(tok):
                    break
                names.append(u)
                expect_name = False
                i += 1
                if i < n and toks[i] == "(":  # selectable procedure args
                    depth = 0
                    while i < n:
                        depth += toks[i] == "("
                        depth -= toks[i] == ")"
                        i += 1
                        if depth == 0:
                            break
                if i < n and _IDENT.fullmatch(toks[i]) and toks[i].upper() not in _STOP:
                    i += 1  # alias
            elif tok == ",":
                expect_name = True
                i += 1
            else:
                break
    return names


def check_open_query(sql: str) -> list[str]:
    """Full gate: SELECT-only, no quoted identifiers, every relation in table
    position on the allowlist. Returns the tables referenced; raises
    GuardError with the reason otherwise."""
    if '"' in sql:
        raise GuardError(
            "quoted identifiers are not supported on the open path — every "
            "Parcel Perfect name is plain uppercase; write it unquoted"
        )
    assert_select_only(sql)
    cleaned = _strip_literals_and_comments(sql)
    ctes = {m.group(1).upper() for m in _CTE_NAME.finditer(cleaned)}
    tables = [t for t in _referenced_tables(cleaned) if t not in ctes]
    if not tables:
        raise GuardError("no table found in the FROM clause")
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
    return sorted(set(tables))


# --- execution ------------------------------------------------------------------


def _value(v):
    """Serialise for the answer: dates/times to ISO, CHAR padding stripped."""
    if isinstance(v, str):
        v = v.strip()
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
        return _refused(f"Firebird refused the query: {e}")
    elapsed_ms = round((time.perf_counter() - started) * 1000)

    if len(rows) > ROW_CAP:
        return _refused(
            f"the query returned more than {ROW_CAP} rows — refusing to "
            "truncate silently. Aggregate in SQL (COUNT/SUM/GROUP BY), add "
            f"WHERE bounds, or SELECT FIRST {ROW_CAP} explicitly if a sample "
            "is genuinely wanted."
        )

    notes = [
        "Open-path answer: a raw read, not a verified report figure.",
    ]
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


def _refused(reason: str) -> dict:
    return {"ok": False, "refused": True, "reason": reason}


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


def schema_context(table: str | None = None) -> dict:
    """The schema resource content: real column names/types from the 6 Aug
    survey for the allowlisted tables, each with its justification, plus the
    caveats a correct Firebird query against PP needs."""
    data = _schema_data()
    tables = {
        name: {
            "why_queryable": ALLOWLIST[name],
            **info,
        }
        for name, info in data["tables"].items()
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
                "Firebird SQL: SELECT FIRST n ... (not LIMIT); string literals "
                "in single quotes; CHAR columns are space-padded — compare with "
                "TRIM() or exact padded values."
            ),
            _DATE_CAVEAT,
            HONEST_BOUNDARY,
        ],
        "tables": tables,
    }
