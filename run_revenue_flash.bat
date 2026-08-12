@echo off
REM Flash Revenue — 07:00 weekdays, Windows Task Scheduler on the BI server.
REM Builds the Flash Revenue report for the previous trading day and emails it
REM to exco. See run_revenue_pm.bat for the 16:30 run.
REM
REM Logging is handled by run_daily.py (logs\run_revenue\, rolled at midnight,
REM kept 30 days), same as report_generation.py. Only failures that happen
REM before Python starts — uv missing, import errors — land in bootstrap.log.

set SYNCED=C:\Users\AkhaM\OneDrive - Sunrise Express\Claude General - Documents
cd /d C:\Users\AkhaM\Sunrise-Frequency-Reporting
if not exist logs\run_revenue mkdir logs\run_revenue

uv run revenue_reports/run_daily.py --only flash ^
    --data-dir "%SYNCED%\Dashboards and Data Analysis\2. Revenue Data" ^
    --report-dir "%SYNCED%\Dashboards and Data Analysis" ^
    2>> logs\run_revenue\bootstrap.log

REM Hand the real result to Task Scheduler, so a failed run shows as failed.
exit /b %ERRORLEVEL%

REM Add --no-email for a build-only test run, or
REM --to you@sunriselogistics.net to send a test to yourself instead of exco.
