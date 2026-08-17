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
- `waybill_status(waybill_no)` — latest delivery status for one waybill from
  `VIEW_WBANALYSE` (the view Alex's production POD reports query): status,
  last event/hub/date/time, POD recipient + date/time + capture date/time +
  discrepancy + image present, delivery agent, service, origin→destination.
  One row per waybill — the **last** recorded movement; full EVENT-table
  history is a separate future quote. Indexed lookup only (exact match +
  `STARTING WITH '<no>~'` for tilde variants, ~25 ms live). Not-found is
  explicit, tilde copies are flagged, multiple matches are all returned.

### Revenue tools (Day 4)

All in `revenue.py`, on top of Day 3's verified seam: ONE set of query logic
(`extraction_sql` → `export_shaped`) serves both the inline answer and the
workbook, which is built by injecting the same rows into the existing
builders. Business rules are imported from the modules that own them, never
re-derived. Workbooks always build from the **unfiltered FY extract**
(filtered extracts answer inline only) and land in
`…\Dashboards and Data Analysis\On Demand` — the archive; Larry receives the
workbook in the conversation. Guards throughout: future dates refused,
still-being-captured/invoiced days warned or refused, date bases from
`day_guards.last_trading_day`, row caps that refuse rather than truncate.

- `sales_report(customer, date_from?, date_to?)` — billed revenue for one
  customer, invoice-date basis, FY-to-date default; monthly breakdown,
  credit notes, net. Customer matching: exact account, then fuzzy name
  returning **candidates** — never a silent best guess.
- `revenue_summary(day?)` — one day on both bases (shipped vs billed, with
  the two-dates explanation), branch split, top customers, net of credits.
- `unbilled_report(workbook?)` — frontier, count, value, by-status, top
  customers; optionally the branded workbook from the same rows.
- `credit_notes(month?, workbook?)` — Credit Note + Journal Credit only;
  month defaults to the last invoiced trading day's month.
- `daily_report(report, day?)` — the branded day-keyed workbooks: `flash`,
  `billing_detail`, `dashboard`. A not-yet-invoiced day gets a flash, never
  a billing detail.

Acceptance harnesses: `research/day4_wiring_check.py` (tools through a real
MCP client session) and `research/day4_acceptance.py` (answers vs the
existing pull, to the cent).

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
