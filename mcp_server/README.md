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
    uv run python -m mcp_server --host 0.0.0.0 --port 9443   # the published shape (auth + TLS in .env)

`--host`/`--port` pick the bind; auth configured in `.env` is what lifts the
loopback-only refusal ("Auth" below). The live service is started by
`run_mcp_server.bat` (`--host 0.0.0.0`, port 8787 until the Day 6-final
cutover to 9443).

### TLS (Day 6-TLS, 17 Sep 2026) — configuration, not code

NSN's MX67 edge forwards `mcp-claude.sunriselogistics.net:9443` to this host
**without terminating TLS** (14 Sep Decisions entry), so the service serves
HTTPS itself when `.env` sets both of:

- `TLS_CERTFILE` — the **FULL CHAIN** PEM: leaf + intermediates concatenated
  (the issued Certum file is already in that shape).
- `TLS_KEYFILE` — the matching unencrypted PEM private key.

Both live **outside the repo** — `C:\Users\AkhaM\mcp-tls\` on the BI server,
never committed (`.gitignore` refuses `*.pem`/`*.key`/`*.crt`/`*.csr` as a
backstop). Rules, all-or-nothing like auth:

- both unset → plain HTTP, exactly as before (test-pinned: the uvicorn config
  is identical to the one the SDK builds);
- exactly one set, a path that does not exist, a file that will not parse, or
  a key that does not match the certificate → **refuse to start**, with the
  variable and path in the message. A typo can never leave the published
  endpoint answering plain HTTP.

How: `MCPServer.run("streamable-http")` builds its uvicorn config with no ssl
arguments (pinned in `tests/test_tls.py`), so `runner.py` drives uvicorn on
the SDK's own ASGI app (`streamable_http_app`) and adds
`ssl_certfile`/`ssl_keyfile` when configured; `tls.py` loads the pair into an
SSL context at startup so a broken file fails there, clearly. The bearer
layer is untouched — `tests/test_tls.py` mints throwaway certificates in temp
files (self-signed, and a CA-signed chain in the issued-file shape) and
proves the 401 challenge and the protected-resource metadata are served over
HTTPS. **No real certificate or key material in the repo or the tests, ever.**

Cutover to 9443 is **Day 6-final**, run with Akha once the vendor edits land:
bat `--port 9443`, the two TLS lines in `.env`, `AUTH_AUDIENCE` moving to the
`:9443` URL, a Windows Firewall inbound rule for 9443, the connector URL edit
on the Claude side, end-to-end sign-in. Renewal is a managed event —
`docs/service-persistence.md` "TLS".

## Tools

Every tool is registered with MCP tool annotations marking it read-only
(`readOnlyHint=True`, `destructiveHint=False`, `idempotentHint=True`,
`openWorldHint=False` — `READ_ONLY` in `server.py`, Day 7). In claude.ai that
moves the tools out of the "can make changes" group, so once the connector is
reconnected calls run without a per-call approval prompt (Sunrise's org
setting blocks "Always allow" on tools without the hints). The workbook
exports of `daily_report` / `credit_notes` are artefacts written to the BI
server, not database changes, so they carry the same annotations.

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
workbook in the conversation. Every workbook response carries the local
`path` (the archive record) and, when `SHAREPOINT_LIBRARY_URL` is set in
`.env` (the web URL of the Claude General library root), a `link` — the
library URL joined to the file's library-relative path, URL-encoded — which
is what the user should be given: the sync path is a different path on
Larry's laptop and useless on his phone (31 Aug 2026 live test). Unset,
responses carry the path only, unchanged. Guards throughout: future dates refused,
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

### Open path (Day 5)

`open_query(question, sql)` in `open_query.py` — anything the named tools do
not cover, answered from the raw data through a fence:

- **SELECT-only** (`sql_guard`), plus a **table allowlist** checked in table
  position (FROM/JOIN through comma lists, CTE-aware, derived tables
  scanned). 32 relations, each justified from the 6 Aug schema survey in
  `ALLOWLIST`: the sanctioned views (`VIEW_WBANALYSE`, `VIEW_SURCHARGES`,
  `VIEW_USERCODE`, `VIEW_CUSTOMERS`), billing documents (`RECEIPT`,
  `INVOICE`), parties (`CUSTOMER`, `CONTACT`, `AGENT`), operations
  (`MANIFEST`, `AGENTDRIVER`, `ACTROUTE`, `ACTLEG`, `SERVICE`,
  `SERVICEGROUP`, `COLLECT`, `NOTE`), lookups (`HUB`, `PLACE`, `AREA`,
  `BRANCH`, `HOLIDAY`) and, from QT-000007 line 1 (20 Oct 2026), the rate
  tables (`RATE`, `MASSRATE`, `ITEMRATE`, `RATENUM`, `SURCHRATE`, `SURCHNUM`,
  `AGRATE`, `AGRATENUM`) and, from QT-000007 line 4 (21 Oct 2026), the two
  windowed relations `ROUTING` and `VIEW_EVENTSCANS` (next bullet). `EVENT`
  (113M rows) and the other multi-million-row tables refuse with tailored
  messages — a waybill's scan history is on `VIEW_EVENTSCANS`, and scans by
  type over a date range are the event-counts tool Reuven asked for on
  20 Oct 2026, quoted separately. Quoted identifiers refuse outright.
- **Windowed tables** (`WINDOWED`, QT-000007 line 4, 21 Oct 2026): `ROUTING`
  (6.2M rows) and `VIEW_EVENTSCANS` (a UNION over the 113M-row EVENT family
  with eight lookups per row) are queryable only when every occurrence of
  them carries a **key** or a **window**, checked in `check_open_query`
  after the allowlist, identifier and star gates. ROUTING: `WAYBILL = '…'`
  or `IN (up to 100 literals)`, `MANIFEST = n` or `IN (up to 20)` (MBRANCH
  and MTYPE optional — the result note says they pin one trip), or an
  `AGENTDATE` range of at most 31 days. VIEW_EVENTSCANS: `WAYBILL` or
  `TRACKNO` (= or IN, up to 100), `MANIFEST` (= or IN, up to 20), or an
  `EVENTDATE` range of at most 3 days. `BOOKDATE`, `AGENT`, hubs, `MTYPE`,
  `STATUS` on ROUTING and `WAYDATE`, `ACCNUM`, `NAME`, `HUB`, `USERNAME`,
  `AGENTNAME` on the view are filters only — they never satisfy the rule on
  their own (BOOKDATE is populated only on local-delivery rows; the view's
  lookup-side columns make the planner scan TRACK and WAYBILL). Values must
  be literals (no subquery, parameter or `CURRENT_DATE` arithmetic), dates
  as `'YYYY-MM-DD'` (`DATE '…'`, `TIMESTAMP '…'` and `CAST('…' AS DATE)` are
  read), on the windowed table's **own alias** (`ROUTING.WAYBILL = x` does
  not window `VIEW_EVENTSCANS` in a join; a bare column in a multi-table
  query is refused as unqualified), in `WHERE` or a `JOIN … ON` (HAVING and
  the select list run after the scan), not negated, and not inside an `OR`
  (alternatives go in `IN (…)`). Ranges are inclusive: `BETWEEN a AND b` is
  b − a + 1 days, `>= a AND < b` is b − a. Every occurrence needs its own
  predicate: a window inside a CTE does not cover an outer unwindowed read,
  a self-join needs both sides, and a join of the two windowed tables needs
  each keyed or windowed. The refusal states the rule in one sentence and
  names what was missing (no predicate, a subquery or `CURRENT_DATE` range,
  an OR, a filter-only column, an over-long IN-list, reversed or one-sided
  bounds, the wrong alias); an accepted query carries a `Window applied —`
  note. The widths come from live plans and timings, every PLAN line
  recorded in `research/db_query_interface/routing_eventscans_plans_2026-10-21.md`
  (ROUTING 31 days = 48,680 rows in 168 ms cold, the unbounded count 7.9 s;
  the view 1/3/7 days = 1.2/3.5/6.9 s warm). The 15 s cap cannot stop
  Firebird 3 server-side, so this predicate check is the load guard for these
  two. `ROUTING.DELOTP` (the delivery one-time PIN) is withheld, so `SELECT *`
  refuses on ROUTING as on any table with withheld columns; the view's
  `RECIPIENT` and `USERNAME` are names and are served.
- **Column deny list** (`DENIED_COLUMNS`, QT-000007 line 2, 20 Oct 2026):
  per table, the contact (phone/cell/fax/email), banking and
  password/credential columns, built from the survey by name match and then
  read column by column (after-hours numbers, the inter-company login, the
  invoice PDF blobs are in; notification flags whose names contain EMAIL/FAX
  and `RECEIPT.BANK`, a bank code on Sunrise's own receipts, are not — the
  decisions are in the dict's comments; `BRANCH`'s IP / DBPATH / RDBSERVER /
  RTMPATH went in after the Fable review, F2). Enforced three ways: a denied
  name as an identifier **anywhere** in the SQL refuses the query — a
  `WHERE` on `WEBPASSWORD` is an oracle, so hiding the column is not enough;
  a projection star (`SELECT *`, `alias.*`, in any select list — outer
  query, derived table, CTE body, UNION branch, subquery) is refused on any
  statement that touches a table with withheld columns, because a star
  carries them out under whatever names the query gives them (Fable review
  F1, 20 Oct 2026: `SELECT * FROM (SELECT * FROM CONTACT) t (A1, …)` and a
  UNION named by a `WHERE 1=0` first branch defeated name-based dropping;
  `COUNT(*)` and arithmetic `a * b` are untouched, tables with an empty deny
  set keep their star; in `EXISTS` and `IN` subqueries write `SELECT 1`,
  not `SELECT *`); and, behind both, a denied column that somehow
  arrives in a result is dropped by cursor-description name with a note —
  defence in depth, no longer the fence. Matching is by bare name across
  every table in the statement; a coincidental same-named column on another
  table is refused too and the message says so. `describe_schema` omits the
  columns and says per table how many are withheld. Free text (`NOTE.MEMO`,
  `COLLECT.NOTES`/`NOTESINT`, `CUSTOMER.NOTE`/`SPECINSTRUCTION`) and
  person-name columns (`COLLECT.CONTACT`/`BOOKINGCONTACT`,
  `VIEW_WBANALYSE.ORIGPERCONTACT`/`DESTPERCONTACT`) can carry hand-typed
  contact detail that no column guard strips — each table's justification
  and `read_this_first` say so.
- **Row cap 500 — a hit cap refuses**, never truncates (the every-fetcher
  rule). **Time cap 15s** via the driver socket timeout; honest limitation:
  it bounds how long we wait, not what Firebird keeps executing, so the real
  load bound is the allowlist. The driver reports a tripped timeout as
  `OperationalError: Can not recv() packets`.
- **Date plausibility flags** on every date column in the result
  (`day_guards.plausible_window` / `classify_dates`): 1899-12-30 placeholders,
  pre-1990 junk and future dates are counted per column — PP carries all
  three as a matter of course and an unbounded date aggregate is this
  project's recorded failure mode.
- An **empty result** answers "no matching rows", never a verified zero; a
  **revenue-territory read** (RECEIPT/INVOICE/VIEW_SURCHARGES, or billing
  columns on VIEW_WBANALYSE) carries the honest-boundary caveat and points
  at the named tools.
- `describe_schema(table?)` + the `schema://parcel-perfect` resource: real
  column names/types/row counts from the survey (`schema_context.json`,
  regenerated by `research/db_query_interface/build_schema_context.py` after
  a new survey or an allowlist change — it filters on `ALLOWLIST`; the deny
  list is applied at serve time, so the JSON is the whole survey for those
  tables). AGENT's vehicle columns are documented as essentially
  unpopulated (live check 18 Aug).

Harness: `research/db_query_interface/day5_wiring_check.py` (live: manifest
count cross-checked; UPDATE / WAYBILL cross-join / EVENT refused over the
protocol; every call in the audit log).

## Logging (Day 5)

`audit.py` — every tool call: tool, user (26 Aug, Reuven's Asana #8: the
verified subject from the request's validated token, stamped on the tool
line itself so each query is attributed on the line that records it; `-`
while auth is off — there is no identity to attribute), args (the question
and the SQL — they are the audit trail), outcome (ok / refused+reason /
needs / error), row count, duration. **Never response bodies** — they would
copy customer pricing into log files. `logs\mcp_server\mcp_server.log`, rolled at
midnight, kept 30 days (the run_daily conventions); handlers sit on the
`mcp_server` logger directly because the MCP SDK owns root logging.
`logs\mcp_server\service.log` is the bootstrap surface (process starts,
exits, pre-Python failures).

## Service persistence (Day 5)

`run_mcp_server.bat` (repo root) restarts the server 15s after any death and
logs it. Task Scheduler starts the bat at boot — registration state and the
one elevated command still needed are in `docs/service-persistence.md`.
Soak-tested 18 Aug: 25 concurrent sessions opened cleanly; 8 workers x 90s =
5,980 queries, 0 errors, p95 53–74ms (indexed/small) and 446ms (month
aggregate over MANIFEST).

## Auth (Day 6a — built; Day 6 = values)

`auth.py` — bearer-token validation on the HTTP path, **issuer-agnostic**:
Innate have not confirmed the auth method (Entra proposed 10 Aug, pending),
so the issuer is configuration in the gitignored `.env`, never code. Spec
requirements re-verified against the live MCP spec (rev **2026-07-28**) and
Anthropic's connector docs on 19 Aug 2026 — the resource-server half is
unchanged from the 12 Aug reading.

Config (all-or-nothing; a **partial** set refuses to start — a typo must
never silently run the server open):

- `AUTH_ISSUER` — the token issuer, exactly as it appears in `iss`. Entra is
  confirmed and mints **v1 tokens** (proven 31 Aug 2026 by decoding a minted
  token): `https://sts.windows.net/<tenant-id>/` — trailing slash included.
- `AUTH_JWKS_URL` — the issuer's signing keys
  (Entra v1: `https://login.microsoftonline.com/<tenant-id>/discovery/keys`).
- `AUTH_AUDIENCE` — the `aud` the tokens carry: the Application ID URI,
  which is the connector URL (`https://mcp-claude.sunriselogistics.net/mcp`
  today; **`https://mcp-claude.sunriselogistics.net:9443/mcp` after the Day
  6-final cutover** — the port is part of the string, Gédry is re-pointing
  the Application ID URI (17 Sep), and `.env` changes in the same step).
- `AUTH_RESOURCE_URL` — the canonical public MCP URL for the RFC 9728
  metadata; only needed when `AUTH_AUDIENCE` is not itself that URL (it is,
  so unset).
- Optional: `AUTH_REQUIRED_SCOPES` (space-separated), `AUTH_CLOCK_SKEW_S`
  (default 60), `AUTH_ALLOWED_ALGS` (space-separated JWT algorithms, default
  `RS256` — Entra signs RS256 only; asymmetric only, anything else refuses
  to start).

Unset (the current state): behaviour unchanged, and `__main__` refuses any
non-loopback bind. Set: the SDK enforces bearer tokens on `/mcp` (401 +
`WWW-Authenticate` carrying `resource_metadata=`), serves
`/.well-known/oauth-protected-resource/mcp`, and `auth.py` validates
signature (against the JWKS, asymmetric algorithms only), issuer, audience,
expiry/not-before with bounded clock skew. Every refusal writes an audit
line with the reason class — never token material. Tests mint against a
mock issuer in `tests/test_auth.py` (local JWKS, never a running service).
The bearer layer sits on the same ASGI app whether it is served over plain
HTTP or, with `TLS_CERTFILE`/`TLS_KEYFILE` set, over HTTPS — `tests/test_tls.py`
proves the same 401 challenge and metadata document over TLS ("Run" above).

Claude-side, no server action: PKCE `S256` on every authorization request;
`offline_access` appended for refresh tokens; Claude's token-endpoint
timeout is 10 s. Design note: the MCP spec's default OAuth flow uses Dynamic
Client Registration; Entra does not support DCR, so Claude uses a
pre-registered client ID/secret instead (supported on custom connectors per
Anthropic's docs, 12 Aug 2026). Innate-facing requirements stay in
`docs/entra-app-registration.md`.
