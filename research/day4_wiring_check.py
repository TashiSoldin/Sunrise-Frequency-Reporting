"""Day 4 wiring check: call the revenue tools through a real MCP client
session (in-memory transport against the actual server object), proving the
tools are registered and their answers serialise over the protocol.

Run from the repo root on the BI server (needs the gitignored .env):

    uv run python research\\day4_wiring_check.py

Light on the database on purpose: health, a disambiguation, and one
narrow-window sales report. The heavy workbook paths are exercised by
research/day4_acceptance.py.
"""

import asyncio
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp.client.client import Client

from mcp_server.server import mcp

EXPECTED = {
    "health",
    "waybill_status",
    "sales_report",
    "revenue_summary",
    "unbilled_report",
    "credit_notes",
    "daily_report",
}


async def main() -> None:
    async with Client(mcp) as client:
        tools = await client.list_tools()
        names = {t.name for t in tools.tools}
        missing = EXPECTED - names
        print("tools registered:", sorted(names))
        if missing:
            raise SystemExit(f"MISSING TOOLS: {missing}")

        r = await client.call_tool("health", {})
        print("\nhealth:", r.structured_content or r.content)

        r = await client.call_tool("sales_report", {"customer": "BSC Stationers"})
        body = r.structured_content or json.loads(r.content[0].text)
        assert body.get("needs") == "customer_disambiguation", body
        print(
            "\ndisambiguation (as designed):",
            [c["account"] for c in body["candidates"]],
        )

        week_ago = (date.today() - timedelta(days=7)).isoformat()
        r = await client.call_tool(
            "sales_report", {"customer": "B35", "date_from": week_ago}
        )
        body = r.structured_content or json.loads(r.content[0].text)
        print("\nsales_report B35 last 7 days:")
        print(json.dumps(body, indent=1)[:1200])

        r = await client.call_tool(
            "daily_report", {"report": "flash", "day": date.today().isoformat()}
        )
        body = r.structured_content or json.loads(r.content[0].text)
        assert body.get("refused"), body
        print("\nflash-for-today refusal (as designed):", body["reason"][:80], "...")

    print("\nWIRING CHECK PASSED")


if __name__ == "__main__":
    asyncio.run(main())
