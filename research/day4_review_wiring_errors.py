"""Day 4 adversarial review — the failure surface through a REAL MCP client.

Every failure must cross the protocol as flagged, plain-language error text:
never a stack trace, never anything readable as "no data".

    uv run python research\\day4_review_wiring_errors.py
"""

import asyncio
import io
import json
import os
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp.client.client import Client

from mcp_server.server import mcp


def show(label, r):
    body = r.structured_content
    text = "".join(c.text for c in r.content if hasattr(c, "text"))
    print(f"\n--- {label} ---")
    print(f"isError={r.is_error}")
    if body is not None:
        print("structured:", json.dumps(body, default=str)[:600])
    print("text:", text[:600])
    bad = ("Traceback" in text) or (".py" in text and "line" in text)
    print("stack-trace leak:", "YES <-- FAIL" if bad else "no")


async def main() -> None:
    async with Client(mcp) as client:
        r = await client.call_tool("credit_notes", {"month": "2026-13"})
        show("credit_notes month=2026-13 (bad month)", r)

        r = await client.call_tool("credit_notes", {"month": "garbage"})
        show("credit_notes month=garbage", r)

        r = await client.call_tool("daily_report", {"report": "sales"})
        show("daily_report report=sales (unknown)", r)

        r = await client.call_tool("sales_report", {"customer": "   "})
        show("sales_report customer=blank", r)

        r = await client.call_tool("revenue_summary", {"day": "not-a-date"})
        show("revenue_summary day=not-a-date", r)

        r = await client.call_tool("sales_report", {"customer": "Tommy PDY Limited"})
        show("sales_report unknown name (must say nothing assumed)", r)

    # dead DB: point the connection at a black hole and watch the message
    os.environ["DB_HOST"] = "192.0.2.1"  # TEST-NET, unroutable
    os.environ["DB_CONNECT_TIMEOUT"] = "3"
    async with Client(mcp) as client:
        r = await client.call_tool("revenue_summary", {})
        show("revenue_summary with unreachable DB", r)

    print("\nDONE")


if __name__ == "__main__":
    asyncio.run(main())
