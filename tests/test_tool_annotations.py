"""Day 7 — every tool is served with read-only MCP tool annotations.

Without them claude.ai lists each tool as one that "can make changes", and
Sunrise's org setting then blocks "Always allow" on it (a manual click per
call). The server only reads Parcel Perfect; the workbook exports are
artefacts on the BI server, not database changes, so every tool — the nine
of them, unchanged in name — carries the same hints.
"""

import asyncio

from mcp_server import server as server_mod

EXPECTED_TOOLS = {
    "health",
    "sales_report",
    "revenue_summary",
    "unbilled_report",
    "credit_notes",
    "daily_report",
    "waybill_status",
    "open_query",
    "describe_schema",
}


def _list_tools():
    return asyncio.run(server_mod.create_server().list_tools())


def test_same_nine_tools():
    assert {t.name for t in _list_tools()} == EXPECTED_TOOLS


def test_every_tool_annotated_read_only():
    # Assert on the wire form (camelCase, what claude.ai receives); the SDK's
    # Python attributes are snake_case (read_only_hint) behind the aliases.
    for tool in _list_tools():
        assert tool.annotations is not None, tool.name
        wire = tool.annotations.model_dump(by_alias=True, exclude_none=True)
        assert wire == {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        }, tool.name
        assert tool.annotations.read_only_hint is True, tool.name
        assert tool.annotations.destructive_hint is False, tool.name
