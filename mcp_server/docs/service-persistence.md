# Service persistence — how the MCP server survives (Day 5)

The server must start with the BI server, keep running, and report failures
rather than answer around them.

## Pieces

1. **`run_mcp_server.bat`** (repo root) — runs the server in a restart loop:
   if the process dies, it logs the exit code to `logs\mcp_server\service.log`
   and restarts after 15s. This is the "keeps running" half, independent of
   Task Scheduler.
2. **Task Scheduler** — the "starts with the server" half.

## Current state (3 Sep 2026)

- **Boot task registered and Ready**: `Sunrise MCP Server` (AtStartup,
  runs as `sunrise\akham` with a stored password — the recommended pattern
  below, registered from an elevated prompt 31 Aug). The interim at-logon
  task is deleted. **The reboot proof is still outstanding** — other users
  hold disconnected sessions on the server, so the restart sits with Innate
  in their maintenance window.
- **Windows Firewall inbound rule added (3 Sep)**: see "Network exposure"
  below. A rebuilt server needs it re-created or the published endpoint
  dies silently at this host.

## Network exposure (Day 6, 1–3 Sep 2026)

Since Day 6 the bat runs the server with `--host 0.0.0.0` (auth configured
in `.env` is what lifts the loopback-only refusal), so NSN's edge can
forward `mcp-claude.sunriselogistics.net:443` to this host on port 8787.
Windows Firewall blocks new inbound ports by default and **drops them
silently — the service log shows nothing**, which cost an afternoon on
3 Sep. The rule (elevated):

```powershell
New-NetFirewallRule -DisplayName 'Sunrise MCP Server (8787 inbound)' `
  -Direction Inbound -Protocol TCP -LocalPort 8787 -Action Allow
```

Verified 3 Sep: a machine on another office subnet gets the service's 401.
Exposure stays bounded by the bearer-token requirement on every request
(auth.py) and NSN's edge allowlisting Anthropic's 160.79.104.0/21 upstream.

**Superseded 14–17 Sep 2026.** Public 443 was never ours (Parcel Perfect's),
and the MX67 forwards without terminating TLS, so the endpoint is now
`https://mcp-claude.sunriselogistics.net:9443/mcp` with TLS terminated by
this service — see "TLS" below. At the Day 6-final cutover the inbound rule
for 9443 is the same command with `-LocalPort 9443` (display name "Sunrise
MCP Server (9443 inbound)"); the 8787 rule stays for loopback-era
compatibility until then, and can be narrowed afterwards.

## TLS (Day 6-TLS, 17 Sep 2026)

The service serves HTTPS itself: `TLS_CERTFILE` + `TLS_KEYFILE` in the
gitignored `.env` (README "Run" for the rules — all-or-nothing, fail-closed).
Both files live **outside the repo** in `C:\Users\AkhaM\mcp-tls\`:

- `mcp-claude.key.pem` — RSA 2048 private key, **generated on this box on
  16 Sep 2026 and never copied off it** (the CSR went to Innate, not the key).
- `mcp-claude.sunriselogistics.net.fullchain.pem` — the issued certificate,
  Certum DV, leaf + intermediate concatenated (the FULL CHAIN uvicorn
  needs), verified 17 Sep: CN/SAN exactly the hostname, public key
  byte-identical to the CSR's, chain verifies to public roots.
- `mcp-claude.csr.pem` — the request, kept for provenance.

`.gitignore` refuses `*.pem`/`*.key`/`*.crt`/`*.csr` so none of it can be
committed by accident. A copy of the public full-chain file may sit
elsewhere for verification, but the key exists **only** in that folder —
back it up per Innate's practice or accept that a rebuilt server means a
new key + CSR + reissue (the certificate names the host, not the machine).

**Certificate renewal is a managed event.** The certificate is valid
16 Sep 2026 → **3 Apr 2027**; the Coda Decisions page carries the dated
reminder (17 Sep 2026 entry, alongside the client secret's 24 Feb 2027
rotation). Renewal is: new CSR from the existing key on the box (or a fresh
key — then a fresh CSR), Innate reissue, replace the full-chain file in
`mcp-tls\`, bounce the service. No code and no `.env` change unless the
filename changes. An expired certificate is a hard outage for Claude (it
requires a valid chain), not a warning — diarise it.

**Cutover checklist (Day 6-final, with Akha):** bat `--port 9443`; the two
TLS lines in `.env`; `AUTH_AUDIENCE` to the `:9443` URL (Gédry re-points the
Application ID URI first); the 9443 firewall rule above; bounce; connector
URL edit on the Claude side; end-to-end sign-in; then the reboot proof.

## Registration history (18 Aug 2026)

- The interim at-logon task was used while elevation was unavailable:
  `sunrise\akham` is not an administrator on Sunrise-ReportingSvr, and both
  `ONSTART` triggers and `SYSTEM`/S4U principals require elevated
  registration (Access is denied, verified 18 Aug). The two revenue tasks
  got around this with stored-password logon, typed interactively when they
  were created.

## The boot task (registered 31 Aug — commands kept for a rebuild)

A boot trigger requires elevation whichever principal runs it (`ONSTART` and
`SYSTEM`/S4U are both Access-denied to the non-admin session account, verified
18 Aug). So this is one elevated command either way — the choice is only
*which principal* the task runs as. **Choose knowingly; the two are not
equivalent on a client server.**

### Recommended — run as `sunrise\akham` with a stored password (least privilege)

This is the revenue-task pattern (the 07:00/16:30 jobs were registered exactly
this way — password typed at registration, not stored in any file), and the
pattern the live task uses. The server reads `.env` and writes logs under the
repo — it needs no more than the `akham` account, and the interim at-logon
task already proved it runs fine as `akham`.

From an **elevated** PowerShell on the BI server:

```powershell
$action  = New-ScheduledTaskAction -Execute 'C:\Users\AkhaM\Sunrise-Frequency-Reporting\run_mcp_server.bat'
$trigger = New-ScheduledTaskTrigger -AtStartup
$set     = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan)
Register-ScheduledTask -TaskName 'Sunrise MCP Server' `
  -Action $action -Trigger $trigger -Settings $set `
  -User 'sunrise\akham' -Password (Read-Host 'akham password') -RunLevel Limited
```

### Alternative — run as SYSTEM from the shipped XML

```powershell
Register-ScheduledTask -TaskName 'Sunrise MCP Server' `
  -Xml (Get-Content 'C:\Users\AkhaM\Sunrise-Frequency-Reporting\mcp_server\docs\sunrise-mcp-server-task.xml' -Raw)
```

**Caveat — why this is NOT the default.** The XML's principal is SYSTEM
(S-1-5-18, `RunLevel HighestAvailable`) executing a `.bat` inside
`C:\Users\AkhaM\…` — a **user-writable** checkout. Anyone who can write that
folder (the non-admin `akham` account itself, or simply a `git pull` that
changes the `.bat`) then controls what runs as SYSTEM at next boot: a textbook
local-privilege-escalation shape Innate may reasonably flag on a client
server, and more privilege than the server needs. SYSTEM does work (no stored
password, no interactive logon; Firebird access is app-level auth from the
gitignored `.env`), so this stays as a documented option — but prefer the
`akham` principal above unless there is a specific reason not to. Akha/Innate's
call.

### Then, for either principal

Delete the interim task (done 31 Aug):

```powershell
Unregister-ScheduledTask -TaskName 'Sunrise MCP Server (interim logon trigger)' -Confirm:$false
```

Then **reboot the BI server and check** `http://127.0.0.1:8787/mcp` answers
(expect **401 Unauthorized** now that auth is on — that IS the healthy
answer) without anyone logging in. The reboot test is the difference between
"working" and "permanent" — do not skip it. As of 3 Sep it has not run:
the restart is with Innate.

## Failure reporting

- Process death: `service.log` gets the exit code and the restart.
- DB unreachable: tools raise "the Parcel Perfect database is unreachable
  (...) — the query did not run", so an outage is an error the user sees,
  never an empty answer. Every call (including these errors) lands in
  `logs\mcp_server\mcp_server.log`.
