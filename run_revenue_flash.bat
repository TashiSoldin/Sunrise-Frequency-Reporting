@echo off
REM Flash Revenue — 07:00 weekdays, Windows Task Scheduler on the BI server.
REM Builds the Flash Revenue report for the previous trading day and emails it
REM to exco. See run_revenue_pm.bat for the 16:30 run.

set SYNCED=C:\Users\AkhaM\OneDrive - Sunrise Express\Claude General - Documents
cd /d C:\Users\AkhaM\Sunrise-Frequency-Reporting

REM One log per run, named by date. %DATE% is locale-dependent, so ask
REM PowerShell for an ISO date instead — sorts correctly and is unambiguous.
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set TODAY=%%i
set LOGDIR=logs\run_revenue_flash
if not exist "%LOGDIR%" mkdir "%LOGDIR%"

uv run revenue_reports/run_daily.py --only flash ^
    --data-dir "%SYNCED%\Dashboards and Data Analysis\2. Revenue Data" ^
    --report-dir "%SYNCED%\Dashboards and Data Analysis" ^
    >> "%LOGDIR%\run_revenue_flash.log.%TODAY%" 2>&1

REM Capture the pipeline's exit code before anything else overwrites it.
set RC=%ERRORLEVEL%

REM Keep 60 days of logs.
forfiles /p "%LOGDIR%" /m *.log.* /d -60 /c "cmd /c del @path" 2>nul

if not "%RC%"=="0" (
    echo [%DATE% %TIME%] FAILED - exit code %RC% >> "%LOGDIR%\run_revenue_flash.log.%TODAY%"
)

REM Hand the real result to Task Scheduler, so a failed run shows as failed.
exit /b %RC%

REM Add --no-email for a build-only test run, or
REM --to you@sunriselogistics.net to send a test to yourself instead of exco.
