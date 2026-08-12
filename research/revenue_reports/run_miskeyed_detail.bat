@echo off
REM Mis-keyed waybills, line detail — Larry's request of 4 Aug 2026.
REM
REM Pulls the full line detail for the 340 mis-keyed waybills straight from
REM Parcel Perfect and writes a workbook in the daily Billing Detail layout:
REM shipper, consignee, pieces, masses, charge components, sub-total.
REM
REM   research\run_miskeyed_detail.bat
REM
REM Read-only against the database: one SELECT keyed on the waybill numbers,
REM no writes, no email. Safe to run at any time.
REM
REM WHY IT HAS TO HIT THE DATABASE. The waybill NUMBERS survive in the
REM dropped-rows CSV, but nothing else does. That CSV carries nine columns and
REM this needs about twenty-two, and the rows are no longer in the FY27 export
REM because the bounded extract correctly excludes them. So the detail can only
REM come from Parcel Perfect.
REM
REM The raw pull is saved to _diagnostics, so the layout can be reworked
REM later with --from-export instead of querying again.
REM
REM Two steps: pull from the database, then rebuild the workbook with the line
REM detail as a sixth tab. ONE workbook, not two files - "Mis-keyed Waybill
REM Dates" and "Mis-keyed Waybills - line detail" side by side in the folder
REM Larry was pointed at is the filename ambiguity that already cost this
REM project a reference workbook.
REM
REM Output:
REM   Dashboards and Data Analysis\Data Quality\
REM     Mis-keyed Waybill Dates - 04 Aug 2026.xlsx   <- 6 tabs, the deliverable
REM   2. Revenue Data\_diagnostics\
REM     miskeyed pull 2026-08-05.csv                 <- the raw pull, reusable
REM
REM The raw pull goes to _diagnostics, not next to the deliverable: Data Quality
REM is the folder Larry has been pointed at, and a loose CSV beside the workbook
REM invites the wrong file being opened.

setlocal
set SYNCED=C:\Users\AkhaM\OneDrive - Sunrise Express\Claude General - Documents
set REPORTS=%SYNCED%\Dashboards and Data Analysis
set DIAG=%REPORTS%\2. Revenue Data\_diagnostics
set OUT=%REPORTS%\Data Quality
set PULL=%DIAG%\miskeyed pull 2026-08-05.csv
cd /d C:\Users\AkhaM\Sunrise-Frequency-Reporting

if not exist "%OUT%" mkdir "%OUT%"

set SRC=%DIAG%\dropped rows 2026-08-04.csv
if not exist "%SRC%" (
    echo.
    echo Cannot find the dropped-rows CSV:
    echo   %SRC%
    echo.
    echo That file supplies the waybill numbers and is the only surviving record
    echo of them. If it has been deleted, re-run research\run_verify_bounds.bat first —
    echo but note the bounded extract no longer produces those rows, so it will
    echo come back empty. Recover the CSV from the SharePoint version history.
    echo.
    exit /b 1
)

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
uv run research/build_miskeyed_detail.py --csv "%SRC%" --save-pull "%PULL%"
if %ERRORLEVEL% NEQ 0 goto :done
uv run research/build_miskeyed_waybills.py --csv "%SRC%" --out-dir "%OUT%" --detail "%PULL%"
goto :done

:use_venv
echo uv not on PATH — using the project venv instead.
.venv\Scripts\python.exe research\build_miskeyed_detail.py --csv "%SRC%" --save-pull "%PULL%"
if %ERRORLEVEL% NEQ 0 goto :done
.venv\Scripts\python.exe research\build_miskeyed_waybills.py --csv "%SRC%" --out-dir "%OUT%" --detail "%PULL%"
goto :done

:done
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo FAILED with exit code %ERRORLEVEL% — nothing was written.
    echo The message above says why.
    exit /b %ERRORLEVEL%
)
echo.
echo Written to:
echo   %OUT%\Mis-keyed Waybill Dates - 04 Aug 2026.xlsx   (6 tabs)
echo   %PULL%
exit /b 0
