"""MCP server exposing the Parcel Perfect database to Claude (QT-000004).

Runs on the BI server next to the extractions. Read-only by construction:
every statement passes sql_guard.assert_select_only() before it reaches
Firebird, the transaction is opened read-only, and the login's role holds
SELECT grants only (verified 6 Aug 2026 — 227 SELECT grants, no DML).
"""
