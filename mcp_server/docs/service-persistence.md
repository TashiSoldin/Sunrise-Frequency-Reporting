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

From an **elevated** PowerShell on the BI server:

```powershell
Register-ScheduledTask -TaskName 'Sunrise MCP Server' `
  -Xml (Get-Content 'C:\Users\AkhaM\Sunrise-Frequency-Reporting\mcp_server\docs\sunrise-mcp-server-task.xml' -Raw)
```

Then delete the interim task:

```powershell
Unregister-ScheduledTask -TaskName 'Sunrise MCP Server (interim logon trigger)' -Confirm:$false
```

Then **reboot the BI server and check** `http://127.0.0.1:8787/mcp` answers
(or run `research\db_query_interface\day5_wiring_check.py`) without anyone
logging in. The reboot test is the difference between "working" and
"permanent" — do not skip it.

The XML runs the task as SYSTEM so no password is stored and no interactive
logon is needed. Firebird access is app-level auth from the gitignored
`.env`, so SYSTEM works; the server does not touch the OneDrive library.

## Failure reporting

- Process death: `service.log` gets the exit code and the restart.
- DB unreachable: tools raise "the Parcel Perfect database is unreachable
  (...) — the query did not run", so an outage is an error the user sees,
  never an empty answer. Every call (including these errors) lands in
  `logs\mcp_server\mcp_server.log`.
