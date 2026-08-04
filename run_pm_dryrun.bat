@echo off
REM PM dry run — build the 16:30 reports without sending anything.
REM
REM Use before letting a scheduled run reach exco, after pulling a change that
REM touches the reports. Builds dashboard, billing detail, unbilled and credit
REM notes into the synced _diagnostics folder, so the output can be checked off
REM the share rather than only on the server.
REM
REM   run_pm_dryrun.bat
REM
REM --no-email is the whole point: nothing is sent, to anyone. --report-dir
REM keeps the workbooks out of the reports folder so nobody mistakes a dry run
REM for the real thing, and so the 07:00 flash is not overwritten.
REM
REM NOTE this re-extracts from Parcel Perfect by default, which is what you
REM want when verifying an extraction change. Add --skip-extract to rebuild
REM from the files already on disk instead.
REM
REM What to look at afterwards, in _diagnostics:
REM   Unbilled Waybills Report FY27 - <today>.xlsx
REM     Headline should read tens of waybills and tens of thousands of rand.
REM     Four figures and millions means the billing frontier is wrong again.
REM   Billing Detail - <day>.xlsx
REM     Should carry a "Flash Comparison" tab. If it is missing, the frozen
REM     flash for that day was not found — check the reports folder.

setlocal
set SYNCED=C:\Users\AkhaM\OneDrive - Sunrise Express\Claude General - Documents
set DATA=%SYNCED%\Dashboards and Data Analysis\2. Revenue Data
set DIAG=%DATA%\_diagnostics
cd /d C:\Users\AkhaM\Sunrise-Frequency-Reporting

where uv >nul 2>nul
if %ERRORLEVEL%==0 goto :use_uv
if exist .venv\Scripts\python.exe goto :use_venv

echo.
echo Found neither uv on PATH nor .venv\Scripts\python.exe in the repo.
echo   - uv is usually at %%USERPROFILE%%\.local\bin\uv.exe
echo   - or rebuild the environment: uv venv --python 3.13 ^&^& uv sync
echo.
exit /b 1

:use_uv
uv run revenue_reports/run_daily.py --only pm --no-email ^
    --data-dir "%DATA%" --report-dir "%DIAG%"
goto :done

:use_venv
echo uv not on PATH — using the project venv instead.
.venv\Scripts\python.exe revenue_reports\run_daily.py --only pm --no-email ^
    --data-dir "%DATA%" --report-dir "%DIAG%"
goto :done

:done
echo.
echo Reports written to:
echo   %DIAG%
echo Nothing was emailed.
exit /b %ERRORLEVEL%
