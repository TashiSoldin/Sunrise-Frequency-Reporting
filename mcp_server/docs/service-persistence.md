# Service persistence — how the MCP server survives (Day 5)

The server must start with the BI server, keep running, and report failures
rather than answer around them.

## Pieces

1. **`run_mcp_server.bat`** (repo root) — runs the server in a restart loop:
   if the process dies, it logs the exit code to `logs\mcp_server\service.log`
   and restarts after 15s. This is the "keeps running" half, independent of
   Task Scheduler.
2. **Task Scheduler** — the "starts with the server" half.

## Current state (18 Aug 2026)

- **Registered and verified**: task `Sunrise MCP Server (interim logon
  trigger)` — starts the bat when `sunrise\akham` logs on. Registerable
  without elevation, which is all the session account had.
- **NOT yet registered**: the boot-time task. `sunrise\akham` is not an
  administrator on Sunrise-ReportingSvr, and both `ONSTART` triggers and
  `SYSTEM`/S4U principals require elevated registration (Access is denied,
  verified 18 Aug). The two revenue tasks got around this with stored-password
  logon, typed interactively when they were created.

## To finish (one elevated command — Akha or Innate)

A boot trigger requires elevation whichever principal runs it (`ONSTART` and
`SYSTEM`/S4U are both Access-denied to the non-admin session account, verified
18 Aug). So this is one elevated command either way — the choice is only
*which principal* the task runs as. **Choose knowingly; the two are not
equivalent on a client server.**

### Recommended — run as `sunrise\akham` with a stored password (least privilege)

This is the revenue-task pattern (the 07:00/16:30 jobs were registered exactly
this way — password typed at registration, not stored in any file). The server
only binds loopback, reads `.env` and writes logs under the repo — it needs no
more than the `akham` account, and the interim at-logon task already proved it
runs fine as `akham`.

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

Delete the interim task:

```powershell
Unregister-ScheduledTask -TaskName 'Sunrise MCP Server (interim logon trigger)' -Confirm:$false
```

Then **reboot the BI server and check** `http://127.0.0.1:8787/mcp` answers
(or run `research\db_query_interface\day5_wiring_check.py`) without anyone
logging in. The reboot test is the difference between "working" and
"permanent" — do not skip it.

## Failure reporting

- Process death: `service.log` gets the exit code and the restart.
- DB unreachable: tools raise "the Parcel Perfect database is unreachable
  (...) — the query did not run", so an outage is an error the user sees,
  never an empty answer. Every call (including these errors) lands in
  `logs\mcp_server\mcp_server.log`.
