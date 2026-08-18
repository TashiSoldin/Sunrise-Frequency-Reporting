"""Day 5 wiring check: the open path through a real MCP client session
(in-memory transport against the actual server object).

Proves: the @audited decorator did not break tool schema introspection; the
schema resource serves; open_query answers a real question none of the named
tools cover; hostile queries are refused over the protocol; and every one of
these calls lands in the audit log.

Run from the repo root on the BI server (needs the gitignored .env):

    uv run python research\\db_query_interface\\day5_wiring_check.py

Light on the database on purpose: the live queries are two indexed/aggregate
reads over small allowlisted tables. The hostile probes never reach Firebird.
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mcp.client.client import Client

from mcp_server.audit import LOGS_DIR, configure_logging
from mcp_server.server import mcp

EXPECTED = {
    "health",
    "waybill_status",
    "sales_report",
    "revenue_summary",
    "unbilled_report",
    "credit_notes",
    "daily_report",
    "open_query",
    "describe_schema",
}


def body_of(r):
    return r.structured_content or json.loads(r.content[0].text)


async def main() -> None:
    configure_logging()  # so this check also proves calls land in the log
    log_file = LOGS_DIR / "mcp_server.log"
    log_before = log_file.read_text().count("\n") if log_file.exists() else 0

    async with Client(mcp) as client:
        tools = await client.list_tools()
        names = {t.name for t in tools.tools}
        missing = EXPECTED - names
        print("tools registered:", sorted(names))
        if missing:
            raise SystemExit(f"MISSING TOOLS: {missing}")

        # @audited must not have eaten the parameter schemas.
        oq_tool = next(t for t in tools.tools if t.name == "open_query")
        params = set(oq_tool.input_schema.get("properties", {}))
        assert params == {"question", "sql"}, params
        print("open_query schema params:", sorted(params))

        res = await client.list_resources()
        uris = [str(r.uri) for r in res.resources]
        print("resources:", uris)
        assert "schema://parcel-perfect" in uris, uris
        read = await client.read_resource("schema://parcel-perfect")
        schema = json.loads(read.contents[0].text)
        assert "AGENT" in schema["tables"], "schema resource missing tables"
        print("schema resource serves", len(schema["tables"]), "tables")

        # A question none of the named tools cover: manifest activity for a
        # month (operational, not revenue — no named tool reads MANIFEST).
        r = await client.call_tool(
            "open_query",
            {
                "question": "How many manifests started in July 2026?",
                "sql": "SELECT COUNT(*) AS N FROM MANIFEST WHERE STARTDATE "
                "BETWEEN DATE '2026-07-01' AND DATE '2026-07-31'",
            },
        )
        body = body_of(r)
        assert body.get("ok"), body
        n_july = body["rows"][0][0]
        # Correctness cross-check, independent of the open-path shaping: the
        # same count straight through run_select must agree, and the figure
        # must be a sane share of the survey's 307,955 lifetime manifests.
        from mcp_server.db import run_select

        _, direct = run_select(
            "SELECT COUNT(*) FROM MANIFEST WHERE STARTDATE "
            "BETWEEN DATE '2026-07-01' AND DATE '2026-07-31'",
            timeout=15,
        )
        assert n_july == direct[0][0], (n_july, direct)
        assert 0 < n_july < 307_955, n_july
        print("\nmanifests started in July 2026:", n_july, "(cross-checked)")

        # Hostile: an UPDATE.
        r = await client.call_tool(
            "open_query", {"question": "attack", "sql": "UPDATE AGENT SET CAPACITY=0"}
        )
        body = body_of(r)
        assert body.get("refused"), body
        print("\nUPDATE refused:", body["reason"])

        # Hostile: a cross-join over the waybill table.
        r = await client.call_tool(
            "open_query",
            {
                "question": "attack",
                "sql": "SELECT COUNT(*) FROM WAYBILL A, WAYBILL B",
            },
        )
        body = body_of(r)
        assert body.get("refused"), body
        print("cross-join over WAYBILL refused:", body["reason"][:90], "...")

        # EVENT stays off.
        r = await client.call_tool(
            "open_query",
            {"question": "history", "sql": "SELECT COUNT(*) FROM EVENT"},
        )
        body = body_of(r)
        assert body.get("refused") and "separate quote" in body["reason"], body
        print("EVENT refused:", body["reason"][:90], "...")

        # describe_schema for one table.
        r = await client.call_tool("describe_schema", {"table": "MANIFEST"})
        body = body_of(r)
        cols = {c["name"] for c in body["tables"]["MANIFEST"]["columns"]}
        assert {"STARTKM", "ENDKM", "CHARGEMASS"} <= cols, sorted(cols)[:10]
        print("describe_schema(MANIFEST):", len(cols), "columns")

    log_after = log_file.read_text().count("\n") if log_file.exists() else 0
    new_lines = log_after - log_before
    print(f"\naudit log grew by {new_lines} lines ({log_file})")
    assert new_lines == 5, "all 5 audited calls must appear in the log"

    print("\nWIRING CHECK PASSED")


if __name__ == "__main__":
    asyncio.run(main())
