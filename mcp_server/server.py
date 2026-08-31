"""The MCP server. Tools: health, waybill_status, the revenue tools
(sales_report, revenue_summary, unbilled_report, credit_notes, daily_report),
and the guarded open path (open_query, describe_schema) with its schema
resource (Day 5).

Every tool is @audited: question/args, outcome, row count and duration land
in logs/mcp_server/ — never response bodies (they would copy customer
pricing into log files).

Auth (Day 6a): create_server() takes an optional (token_verifier,
AuthSettings) pair from mcp_server.auth.provision() — the SDK then enforces
bearer tokens on the HTTP path and serves the RFC 9728 protected-resource
metadata. Built without them (the module-level `mcp`, and the default until
AUTH_ISSUER lands in .env on Day 6) the server carries no auth and __main__
keeps it loopback-only.
"""

import json
from datetime import datetime

from mcp.server import MCPServer

from mcp_server import open_query as oq
from mcp_server import revenue
from mcp_server.audit import audited
from mcp_server.db import run_select
from mcp_server.waybill import lookup_waybill

_INSTRUCTIONS = (
    "Query interface to Sunrise Logistics' Parcel Perfect database. "
    "Read-only: every statement is checked to be a single SELECT before "
    "it reaches the database. Prefer the named tools (waybill_status, "
    "sales_report, revenue_summary, unbilled_report, credit_notes, "
    "daily_report) — they carry the verified export rules. open_query "
    "answers anything they do not cover, from the raw data, within a "
    "table allowlist and row/time caps; read the schema resource or "
    "describe_schema first so the SQL uses real column names."
)


@audited
def health() -> dict:
    """Confirm the server can reach the database and answer a trivial query."""
    started = datetime.now()
    _, rows = run_select(
        "SELECT CURRENT_USER, CURRENT_ROLE, CURRENT_TIMESTAMP FROM RDB$DATABASE"
    )
    user, role, db_now = rows[0]
    return {
        "status": "ok",
        "db_user": user,
        "db_role": role,
        "db_time": str(db_now),
        "elapsed_ms": round((datetime.now() - started).total_seconds() * 1000),
    }


@audited
def sales_report(
    customer: str, date_from: str | None = None, date_to: str | None = None
) -> dict:
    """Billed revenue for one customer — invoice-date basis, financial
    year-to-date by default (FY runs March-February). Monthly breakdown,
    credit notes and net revenue, the same verified rules as the daily
    reports.

    Pass whatever the user said as `customer` — an account code or a name;
    the tool matches exact account first, then fuzzy name. If it returns
    needs=customer_disambiguation, present the candidates and ask — never
    pick one silently. date_from/date_to are ISO dates (YYYY-MM-DD) and
    narrow the period; arbitrary periods are answered inline like this,
    while branded workbooks stay day/month-shaped (see daily_report).

    RELAY THE WARNINGS — they are the difference between a number and the
    right number (e.g. recent days whose invoicing has not finished)."""
    return revenue.sales_report(customer, date_from, date_to)


@audited
def revenue_summary(day: str | None = None) -> dict:
    """One day's revenue on both bases: shipped (waybill date) and billed
    (invoice date, net of credit notes). Defaults to the last completed
    trading day per basis — one day in arrears, like the scheduled reports.
    Future dates are refused; a day still being captured or still being
    invoiced is answered with an explicit warning. RELAY THE WARNINGS."""
    return revenue.revenue_summary(day)


@audited
def unbilled_report(workbook: bool = False) -> dict:
    """Waybills older than the billing frontier that have not been invoiced —
    count, value, by-status and top customers. workbook=True also builds the
    branded Unbilled Waybills workbook (existing format) from the same rows.
    Give the user the workbook's `link` — it opens on any device; the
    folder and local path are mentioned only as the archive."""
    return revenue.unbilled_report(workbook)


@audited
def credit_notes(month: str | None = None, workbook: bool = False) -> dict:
    """Credit notes for one month (YYYY-MM; default = the month of the last
    invoiced trading day). Types Credit Note + Journal Credit only — the
    net-revenue rule. workbook=True also builds the branded Credit Notes
    workbook for that month; give the user the workbook's `link` — it opens
    on any device; the folder and local path are only the archive."""
    return revenue.credit_notes(month, workbook)


@audited
def daily_report(report: str, day: str | None = None) -> dict:
    """Build one of the branded daily workbooks in the existing formats:
    'flash' (shipped, waybill basis), 'billing_detail' (billed, invoice
    basis) or 'dashboard' (as-of, multi-tab). day is ISO YYYY-MM-DD; the
    default is the last completed trading day for that basis. Refusals are
    deliberate guards, not errors: future days, today's flash (still being
    captured), and a billing detail for a day whose invoicing has not
    finished (a not-yet-invoiced day gets a flash, never a billing detail).
    Workbooks build from the full FY extract and can take a minute or two.
    Give the user the workbook's `link` — it opens on any device; the
    folder and local path are only the archive."""
    return revenue.daily_report(report, day)


@audited
def waybill_status(waybill_no: str) -> dict:
    """Latest delivery status for one waybill number: current status, last
    recorded movement (event, depot/hub, date, time), POD details (recipient,
    date/time, capture date/time, discrepancy, image present), delivery
    agent, service and origin→destination route.

    Scope is the LAST recorded movement — one row per waybill, not the full
    event history. Amended (~) copies of the number are returned alongside
    the base waybill; when several records match, present all of them.
    "found": false means the number is not in Parcel Perfect at all — relay
    that as "not found", never as "no activity yet".
    """
    return lookup_waybill(waybill_no)


@audited
def open_query(question: str, sql: str) -> dict:
    """Ask the database a question none of the named tools cover, with one
    Firebird SELECT. Guarded: SELECT-only, a table allowlist (describe_schema
    lists it — EVENT and the other 100M+-row tables are off it), a row cap
    that REFUSES rather than truncates, and a time cap.

    Call describe_schema (or read the schema resource) FIRST and write the
    SQL against real column names — never guess them. `question` is the
    user's question in plain language; it is audit-logged with the SQL.

    Answers are correct reads of the RAW data and do not carry the export
    rules or verification of the named tools — where a named tool covers the
    question, use it instead. RELAY THE WARNINGS AND NOTES: implausible-date
    flags and the honest-boundary caveat are the difference between a number
    and the right number."""
    return oq.run_open_query(question, sql)


@audited
def describe_schema(table: str | None = None) -> dict:
    """The open path's schema context: which tables open_query may touch and
    why, their real column names and types (6 Aug 2026 survey), row counts,
    and the Firebird/Parcel Perfect caveats — including the 1899-12-30
    null-date placeholders that make unbounded date aggregates wrong. Pass
    `table` for one table's columns, omit it for the full map. Same content
    as the schema://parcel-perfect resource."""
    return oq.schema_context(table)


def schema_resource() -> str:
    return json.dumps(oq.schema_context(), indent=1)


_TOOLS = (
    health,
    sales_report,
    revenue_summary,
    unbilled_report,
    credit_notes,
    daily_report,
    waybill_status,
    open_query,
    describe_schema,
)


def create_server(token_verifier=None, auth_settings=None) -> MCPServer:
    """Build the server with every tool and resource registered. Pass the
    pair from mcp_server.auth.provision() to put bearer-token validation on
    the HTTP path (Day 6a); pass neither for the unauthenticated
    loopback/stdio server — the default until Day 6 sets AUTH_ISSUER."""
    server = MCPServer(
        name="Sunrise Parcel Perfect",
        instructions=_INSTRUCTIONS,
        token_verifier=token_verifier,
        auth=auth_settings,
    )
    for tool in _TOOLS:
        server.tool()(tool)
    server.resource(
        "schema://parcel-perfect",
        name="Parcel Perfect schema for open_query",
        description=(
            "Queryable tables (the open-path allowlist) with real column names, "
            "types and row counts from the 6 Aug 2026 schema survey, plus the "
            "caveats valid Firebird SQL against Parcel Perfect needs — read this "
            "before writing open_query SQL."
        ),
        mime_type="application/json",
    )(schema_resource)
    return server


# The unauthenticated server, for stdio/local use and existing imports
# (__main__ builds its own when .env configures an issuer).
mcp = create_server()
