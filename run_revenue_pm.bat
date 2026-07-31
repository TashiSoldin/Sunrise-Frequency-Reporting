@echo off
REM Daily revenue reports — 16:30 weekdays, Windows Task Scheduler on the BI
REM server. Builds the Revenue Dashboard, Billing Detail, Unbilled and Credit
REM Notes one day in arrears and emails all four to exco.
REM See run_revenue_flash.bat for the 07:00 run.

set SYNCED=C:\Users\AkhaM\OneDrive - Sunrise Express\Claude General - Documents
cd /d C:\Users\AkhaM\Sunrise-Frequency-Reporting

REM One log per run, named by date. %DATE% is locale-dependent, so ask
REM PowerShell for an ISO date instead — sorts correctly and is unambiguous.
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set TODAY=%%i
set LOGDIR=logs\run_revenue_pm
if not exist "%LOGDIR%" mkdir "%LOGDIR%"

REM Banner so successive runs on the same day are separable in one log file.
echo.>> "%LOGDIR%\run_revenue_pm.log.%TODAY%"
echo ---------- run_revenue_pm %DATE% %TIME% ---------->> "%LOGDIR%\run_revenue_pm.log.%TODAY%"

uv run revenue_reports/run_daily.py --only pm ^
    --data-dir "%SYNCED%\Dashboards and Data Analysis\2. Revenue Data" ^
    --report-dir "%SYNCED%\Dashboards and Data Analysis" ^
    >> "%LOGDIR%\run_revenue_pm.log.%TODAY%" 2>&1

REM Capture the pipeline's exit code before anything else overwrites it.
set RC=%ERRORLEVEL%

REM Keep 60 days of logs.
forfiles /p "%LOGDIR%" /m *.log.* /d -60 /c "cmd /c del @path" 2>nul

if not "%RC%"=="0" (
    echo [%DATE% %TIME%] FAILED - exit code %RC% >> "%LOGDIR%\run_revenue_pm.log.%TODAY%"
)

REM Hand the real result to Task Scheduler, so a failed run shows as failed.
exit /b %RC%

REM TESTING (safe, end to end):
REM   1. mkdir C:\revtest\2rd  and copy these two static inputs into it:
REM        "INV Date - March25 - Feb26..xlsx"  and  "FY26-27_Budget_v30_Sunrise.xlsx"
REM      (from the live "2. Revenue Data" folder)
REM   2. set SYNCED so data-dir resolves to C:\revtest\2rd and report-dir to
REM      C:\revtest  (or just run run_daily.py directly with those paths)
REM   3. add --no-email (or --to your own address) so exco gets nothing
REM   4. run this bat from a cmd window, then:
REM        type logs\run_revenue_pm\run_revenue_pm.log.<today>
REM   5. once happy, schedule a one-off Task Scheduler run 2 minutes ahead
REM      ("Run whether user is logged on or not") to prove the scheduler
REM      context works too - THEN point SYNCED back at the live library.
