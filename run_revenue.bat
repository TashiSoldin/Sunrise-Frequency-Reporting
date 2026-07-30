@echo off
REM Daily revenue pipeline — schedule via Windows Task Scheduler on the BI
REM server (same pattern as run_reports.bat). Adjust SYNCED to the local
REM OneDrive/SharePoint sync root for the "Claude General" library.

REM For a TEST run, point SYNCED at a scratch folder (see TESTING below)
REM instead of the live library, so the staff's files are not overwritten.
set SYNCED=C:\Users\AkhaM\Sunrise Express\Claude General - Documents
cd /d C:\Users\AkhaM\Sunrise-Frequency-Reporting
if not exist logs mkdir logs

uv run revenue_reports/run_daily.py ^
    --data-dir "%SYNCED%\Dashboards and Data Analysis\2. Revenue Data" ^
    --report-dir "%SYNCED%\Dashboards and Data Analysis" ^
    >> logs\run_revenue.log 2>&1

REM TESTING (safe, end to end):
REM   1. mkdir C:\revtest\2rd  and copy these two static inputs into it:
REM        "INV Date - March25 - Feb26..xlsx"  and  "FY26-27_Budget_v30_Sunrise.xlsx"
REM      (from the live "2. Revenue Data" folder)
REM   2. set SYNCED so data-dir resolves to C:\revtest\2rd and report-dir to
REM      C:\revtest  (or just run run_daily.py directly with those paths)
REM   3. run this bat from a cmd window, then:  type logs\run_revenue.log
REM   4. once happy, schedule a one-off Task Scheduler run 2 minutes ahead
REM      ("Run whether user is logged on or not") to prove the scheduler
REM      context works too - THEN point SYNCED back at the live library.
