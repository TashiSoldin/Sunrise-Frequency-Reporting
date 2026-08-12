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

## OAuth behaviour (Day 6)

What the server implements when the endpoint goes public. Moved from
`docs/entra-app-registration.md`, which is now the send-to-Innate
requirements only. `<hostname>` = the published hostname Innate choose.

- Unauthenticated requests are answered with
  `401 WWW-Authenticate: Bearer resource_metadata="https://<hostname>/.well-known/oauth-protected-resource/mcp"`.
- That RFC 9728 document carries `resource` = the exact MCP URL and
  `authorization_servers` = the Entra issuer
  (`https://login.microsoftonline.com/<tenant-id>/v2.0`).
- Every request: validate token signature, issuer and audience. With
  Entra's default v1-format tokens the audience is the Application ID URI
  (`https://<hostname>/mcp`), accepted in canonical URL form. If Innate use
  the v2-token fallback (`requestedAccessTokenVersion = 2`), the audience
  becomes the application (client) ID — configure validation to whichever
  they report back.
- Claude-side, no server action: PKCE `S256` on every authorization
  request; `offline_access` appended for refresh tokens; Claude's
  token-endpoint timeout is 10 s.
- Design note: the MCP spec's default OAuth flow uses Dynamic Client
  Registration; Entra does not support DCR, so Claude uses a pre-registered
  client ID/secret instead (supported on custom connectors per Anthropic's
  docs, 12 Aug 2026).
