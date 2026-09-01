@echo off
REM MCP query interface — starts at boot via Windows Task Scheduler task
REM "Sunrise MCP Server" (ONSTART, run as SYSTEM) and keeps itself running:
REM if the server process dies for any reason, the loop below restarts it
REM after 15 seconds and records that it did. Failures are REPORTED in
REM logs\mcp_server\service.log, never answered around.
REM
REM Tool-call audit logging is handled by mcp_server/audit.py
REM (logs\mcp_server\mcp_server.log, rolled at midnight, kept 30 days, same
REM conventions as report_generation.py / run_daily.py). service.log below is
REM the bootstrap surface: process starts, exits, and failures that happen
REM before Python logging exists (uv missing, import errors).
REM
REM uv by absolute path: the task runs as SYSTEM, whose PATH does not carry
REM AkhaM's per-user install.

set UV=C:\Users\AkhaM\.local\bin\uv.exe
cd /d C:\Users\AkhaM\Sunrise-Frequency-Reporting
if not exist logs\mcp_server mkdir logs\mcp_server

:loop
echo [%date% %time%] starting mcp_server >> logs\mcp_server\service.log
"%UV%" run python -m mcp_server --host 0.0.0.0 >> logs\mcp_server\service.log 2>&1
echo [%date% %time%] mcp_server exited with code %ERRORLEVEL% - restarting in 15s >> logs\mcp_server\service.log
timeout /t 15 /nobreak > NUL
goto loop

REM TESTING:
REM   1. run this bat from a cmd window; check logs\mcp_server\service.log
REM      shows a start line and http://127.0.0.1:8787/mcp answers.
REM   2. kill the python process; the loop must log the exit and restart it.
REM   3. schtasks /Run /TN "Sunrise MCP Server"  - proves the scheduled task
REM      context (SYSTEM) works; then reboot the BI server and check the
REM      server answers without anyone logging in. The reboot test is the
REM      difference between "working" and "permanent".
