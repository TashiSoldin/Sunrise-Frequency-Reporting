"""The MCP server. Tools: health, waybill_status.

Remaining tools land per the execution plan: the revenue tools (Days 3-4),
the guarded open query path and hardening (Day 5). OAuth / Entra ID token
verification is wired in on Day 6, once Innate publish the endpoint — until
then this binds to localhost and carries no auth.
"""

from datetime import datetime

from mcp.server import MCPServer

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
