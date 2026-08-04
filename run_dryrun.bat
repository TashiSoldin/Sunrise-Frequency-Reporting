@echo off
REM Full dry run — build EVERY report without sending anything.
REM
REM Use after pulling a change that touches the reports, before letting a
REM scheduled run reach exco. Covers both windows: the 07:00 flash and the
REM 16:30 set (dashboard, billing detail, unbilled, credit notes).
REM
REM   run_dryrun.bat
REM
REM --no-email is the whole point: nothing is sent, to anyone. Everything lands
REM in the synced _diagnostics folder, so it can be checked off the share and
REM cannot be mistaken for a real report or overwrite one.
REM
REM Why the copy below. run_daily looks for the previous morning's FROZEN flash
REM in --report-dir, to build the billing detail's Flash Comparison tab. Point
REM --report-dir at _diagnostics and it looks there, finds nothing, warns, and
REM builds four tabs instead of five. That is not a failure, but it looks
REM exactly like one — so the existing flashes are copied across first and the
REM tab builds as it would in production. Copy, not move: the reports folder is
REM left untouched.
REM
REM What to check afterwards, in _diagnostics:
REM
REM   Flash Revenue - <day>.xlsx
REM     Two sheets: the front page, and "All Customers".
REM     BY REP on page one should have Rep, Revenue, Chg kg, R/kg, Waybills.
REM     The All Customers total must equal the REVENUE figure in the KPI band.
REM
REM   Unbilled Waybills Report FY27 - <today>.xlsx
REM     Tens of waybills and tens of thousands of rand. Four figures and
REM     millions means the billing frontier is wrong again.
REM
REM   Billing Detail - <day>.xlsx
REM     Five tabs, including "Flash Comparison". Its BY REP block must compare
REM     revenue against revenue — if the flash column suddenly looks like
REM     kilograms, the flash's column order has moved and that is serious.
REM
REM   Revenue Dashboard.xlsx
REM     A tab per completed month plus MTD, and figures that are not all zero
REM     when opened in the browser.
REM
REM Re-extracts from Parcel Perfect by default, which is what you want when an
REM extraction change is part of what is being verified. Add --skip-extract to
REM rebuild from the files already on disk.

setlocal
set SYNCED=C:\Users\AkhaM\OneDrive - Sunrise Express\Claude General - Documents
set REPORTS=%SYNCED%\Dashboards and Data Analysis
set DATA=%REPORTS%\2. Revenue Data
set DIAG=%DATA%\_diagnostics
cd /d C:\Users\AkhaM\Sunrise-Frequency-Reporting

if not exist "%DIAG%" mkdir "%DIAG%"

REM Frozen flashes, so the Flash Comparison tab builds as it does in production.
copy /y "%REPORTS%\Flash Revenue - *.xlsx" "%DIAG%\" >nul 2>nul

where uv >nul 2>nul
if %ERRORLEVEL%==0 goto :use_uv
if exist .venv\Scripts\python.exe goto :use_venv

echo.
echo Found neither uv on PATH nor .venv\Scripts\python.exe in the repo.
echo   - uv is usually at %%USERPROFILE%%\.local\bin\uv.exe
echo   - or rebuild the environment: uv venv --python 3.13, then uv sync
echo.
exit /b 1

:use_uv
uv run revenue_reports/run_daily.py --only all --no-email ^
    --data-dir "%DATA%" --report-dir "%DIAG%"
goto :done

:use_venv
echo uv not on PATH — using the project venv instead.
.venv\Scripts\python.exe revenue_reports\run_daily.py --only all --no-email ^
    --data-dir "%DATA%" --report-dir "%DIAG%"
goto :done

:done
echo.
echo All reports written to:
echo   %DIAG%
echo Nothing was emailed. The reports folder was not modified.
exit /b %ERRORLEVEL%
