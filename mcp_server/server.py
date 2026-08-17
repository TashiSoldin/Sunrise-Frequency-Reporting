"""The MCP server. Tools: health, waybill_status, and the revenue tools
(sales_report, revenue_summary, unbilled_report, credit_notes, daily_report).

Remaining per the execution plan: the guarded open query path and hardening
(Day 5). OAuth / Entra ID token verification is wired in on Day 6, once
Innate publish the endpoint — until then this binds to localhost and carries
no auth.
"""

from datetime import datetime

from mcp.server import MCPServer

from mcp_server import revenue
from mcp_server.db import run_select
from mcp_server.waybill import lookup_waybill

mcp = MCPServer(
    name="Sunrise Parcel Perfect",
    instructions=(
        "Query interface to Sunrise Logistics' Parcel Perfect database. "
        "Read-only: every statement is checked to be a single SELECT before "
        "it reaches the database."
    ),
)


@mcp.tool()
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
def revenue_summary(day: str | None = None) -> dict:
    """One day's revenue on both bases: shipped (waybill date) and billed
    (invoice date, net of credit notes). Defaults to the last completed
    trading day per basis — one day in arrears, like the scheduled reports.
    Future dates are refused; a day still being captured or still being
    invoiced is answered with an explicit warning. RELAY THE WARNINGS."""
    return revenue.revenue_summary(day)


@mcp.tool()
def unbilled_report(workbook: bool = False) -> dict:
    """Waybills older than the billing frontier that have not been invoiced —
    count, value, by-status and top customers. workbook=True also builds the
    branded Unbilled Waybills workbook (existing format) from the same rows
    and returns its path; give the user the workbook in the conversation —
    the library folder is only the archive."""
    return revenue.unbilled_report(workbook)


@mcp.tool()
def credit_notes(month: str | None = None, workbook: bool = False) -> dict:
    """Credit notes for one month (YYYY-MM; default = the month of the last
    invoiced trading day). Types Credit Note + Journal Credit only — the
    net-revenue rule. workbook=True also builds the branded Credit Notes
    workbook for that month and returns its path."""
    return revenue.credit_notes(month, workbook)


@mcp.tool()
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
