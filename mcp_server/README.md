# mcp_server — Claude query interface to Parcel Perfect (QT-000004)

MCP server running on the BI server next to the extractions, exposed to
Claude as a custom connector (streamable HTTP). Same repo as the report
builders by decision of 11 Aug 2026 — the revenue tools import them directly.

## Read-only, three layers

1. `sql_guard.assert_select_only()` — every statement must be a single
   SELECT; write/DDL/transaction keywords are refused before Firebird.
   Enforced from the first commit.
2. The connection opens a **read-only** READ COMMITTED transaction.
3. The database role holds SELECT grants only (verified 6 Aug 2026).

## Credentials — INTERIM

`connect()` reads the gitignored `.env` (same keys as the extractions:
`DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_ROLE`). These are the
**BI-role credentials shared with the scheduled reports** — interim only.
A dedicated second login is with Innate (needs SYSDBA); swap it into `.env`
when provisioned. **Must be replaced before handover.**

## Run

    uv run python -m mcp_server                 # streamable HTTP, 127.0.0.1:8787/mcp
    uv run python -m mcp_server --transport stdio

Localhost-only until Innate publish the HTTPS endpoint; auth (OAuth /
Entra ID — see `docs/entra-app-registration.md`) is wired in at that point
(Day 6 of the execution plan).

## Tools

- `health` — trivial guarded query (`SELECT CURRENT_USER, CURRENT_ROLE,
  CURRENT_TIMESTAMP FROM RDB$DATABASE`); proves DB reachability.

Waybill tracking, revenue tools, and the guarded open query path arrive per
the execution plan (Coda → Database Query Interface → Execution Plan).
