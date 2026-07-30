@echo off
REM Daily revenue pipeline — schedule via Windows Task Scheduler on the BI
REM server (same pattern as run_reports.bat). Adjust SYNCED to the local
REM OneDrive/SharePoint sync root for the "Claude General" library.

set SYNCED=C:\Users\AkhaM\Sunrise Express\Claude General - Documents
cd /d C:\Users\AkhaM\Sunrise-Frequency-Reporting

uv run revenue_reports/run_daily.py ^
    --data-dir "%SYNCED%\Dashboards and Data Analysis\2. Revenue Data" ^
    --report-dir "%SYNCED%\Dashboards and Data Analysis" ^
    >> logs\run_revenue.log 2>&1
