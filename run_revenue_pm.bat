@echo off
REM Daily revenue reports — 16:30 weekdays, Windows Task Scheduler on the BI
REM server. Builds the Revenue Dashboard, Billing Detail, Unbilled and Credit
REM Notes one day in arrears and emails all four to exco.
REM See run_revenue_flash.bat for the 07:00 run.
REM
REM Logging is handled by run_daily.py (logs\run_revenue\, rolled at midnight,
REM kept 30 days), same as report_generation.py. Only failures that happen
REM before Python starts — uv missing, import errors — land in bootstrap.log.

set SYNCED=C:\Users\AkhaM\OneDrive - Sunrise Express\Claude General - Documents
cd /d C:\Users\AkhaM\Sunrise-Frequency-Reporting
if not exist logs\run_revenue mkdir logs\run_revenue

uv run revenue_reports/run_daily.py --only pm ^
    --data-dir "%SYNCED%\Dashboards and Data Analysis\2. Revenue Data" ^
    --report-dir "%SYNCED%\Dashboards and Data Analysis" ^
    2>> logs\run_revenue\bootstrap.log

REM Hand the real result to Task Scheduler, so a failed run shows as failed.
exit /b %ERRORLEVEL%

REM TESTING (safe, end to end):
REM   1. mkdir C:\revtest\2rd  and copy these two static inputs into it:
REM        "INV Date - March25 - Feb26..xlsx"  and  "FY26-27_Budget_v30_Sunrise.xlsx"
REM      (from the live "2. Revenue Data" folder)
REM   2. set SYNCED so data-dir resolves to C:\revtest\2rd and report-dir to
REM      C:\revtest  (or just run run_daily.py directly with those paths)
REM   3. add --no-email (or --to your own address) so exco gets nothing
REM   4. run this bat from a cmd window, then:
REM        type logs\run_revenue\run_revenue.log
REM   5. once happy, schedule a one-off Task Scheduler run 2 minutes ahead
REM      ("Run whether user is logged on or not") to prove the scheduler
REM      context works too - THEN point SYNCED back at the live library.
