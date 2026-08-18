"""The MCP server. Tools: health, waybill_status, the revenue tools
(sales_report, revenue_summary, unbilled_report, credit_notes, daily_report),
and the guarded open path (open_query, describe_schema) with its schema
resource (Day 5).

Every tool is @audited: question/args, outcome, row count and duration land
in logs/mcp_server/ — never response bodies (they would copy customer
pricing into log files). OAuth / Entra ID token verification is wired in on
Day 6, once Innate publish the endpoint — until then this binds to localhost
and carries no auth.
"""

import json
from datetime import datetime

from mcp.server import MCPServer

from mcp_server import open_query as oq
from mcp_server import revenue
from mcp_server.audit import audited
from mcp_server.db import run_select
from mcp_server.waybill import lookup_waybill

mcp = MCPServer(
    name="Sunrise Parcel Perfect",
    instructions=(
        "Query interface to Sunrise Logistics' Parcel Perfect database. "
        "Read-only: every statement is checked to be a single SELECT before "
        "it reaches the database. Prefer the named tools (waybill_status, "
        "sales_report, revenue_summary, unbilled_report, credit_notes, "
        "daily_report) — they carry the verified export rules. open_query "
        "answers anything they do not cover, from the raw data, within a "
        "table allowlist and row/time caps; read the schema resource or "
        "describe_schema first so the SQL uses real column names."
    ),
)


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
@audited
def revenue_summary(day: str | None = None) -> dict:
    """One day's revenue on both bases: shipped (waybill date) and billed
    (invoice date, net of credit notes). Defaults to the last completed
    trading day per basis — one day in arrears, like the scheduled reports.
    Future dates are refused; a day still being captured or still being
    invoiced is answered with an explicit warning. RELAY THE WARNINGS."""
    return revenue.revenue_summary(day)


@mcp.tool()
@audited
def unbilled_report(workbook: bool = False) -> dict:
    """Waybills older than the billing frontier that have not been invoiced —
    count, value, by-status and top customers. workbook=True also builds the
    branded Unbilled Waybills workbook (existing format) from the same rows
    and returns its path; give the user the workbook in the conversation —
    the library folder is only the archive."""
    return revenue.unbilled_report(workbook)


@mcp.tool()
@audited
def credit_notes(month: str | None = None, workbook: bool = False) -> dict:
    """Credit notes for one month (YYYY-MM; default = the month of the last
    invoiced trading day). Types Credit Note + Journal Credit only — the
    net-revenue rule. workbook=True also builds the branded Credit Notes
    workbook for that month and returns its path."""
    return revenue.credit_notes(month, workbook)


@mcp.tool()
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
    Deliver the workbook in the conversation; the folder is the archive."""
    return revenue.daily_report(report, day)


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
@audited
def describe_schema(table: str | None = None) -> dict:
    """The open path's schema context: which tables open_query may touch and
    why, their real column names and types (6 Aug 2026 survey), row counts,
    and the Firebird/Parcel Perfect caveats — including the 1899-12-30
    null-date placeholders that make unbounded date aggregates wrong. Pass
    `table` for one table's columns, omit it for the full map. Same content
    as the schema://parcel-perfect resource."""
    return oq.schema_context(table)


@mcp.resource(
    "schema://parcel-perfect",
    name="Parcel Perfect schema for open_query",
    description=(
        "Queryable tables (the open-path allowlist) with real column names, "
        "types and row counts from the 6 Aug 2026 schema survey, plus the "
        "caveats valid Firebird SQL against Parcel Perfect needs — read this "
        "before writing open_query SQL."
    ),
    mime_type="application/json",
)
def schema_resource() -> str:
    return json.dumps(oq.schema_context(), indent=1)
