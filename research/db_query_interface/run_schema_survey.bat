@echo off
REM Schema survey — what is in the Parcel Perfect database, and what we can read.
REM
REM Run by hand on the BI server, not scheduled. First job of the QT-000004
REM build (accepted 6 Aug 2026), and the thing to re-run whenever a question
REM starts "is that even in the database".
REM
REM   run_schema_survey.bat                  full survey, with row counts
REM   run_schema_survey.bat --no-counts      metadata only, fastest and lightest
REM   run_schema_survey.bat --probe-write    also settle write access definitively
REM   run_schema_survey.bat --like *VEH*     narrow a follow-up run
REM
REM Any flags you pass are handed straight to the script. Note the wildcard is
REM * and not SQL's percent sign: cmd.exe would strip a bare one off the line
REM before Python ever saw it. The script translates it.
REM
REM SAFETY. Read-only against Parcel Perfect. Almost all of it reads system
REM metadata (RDB$RELATIONS, RDB$RELATION_FIELDS, RDB$USER_PRIVILEGES) rather
REM than data pages. The one exception is the per-table SELECT COUNT(*), which
REM does read data — it is the slow part, and --no-counts skips it if you would
REM rather not add load during working hours. Views are never counted.
REM
REM --probe-write is the only thing here that is not a SELECT. It runs
REM UPDATE <smallest table> SET <col> = <col> WHERE 1 = 0 inside a transaction
REM that is rolled back either way. Firebird checks privileges before it checks
REM the WHERE clause, so a permission error IS the answer and no row is ever
REM touched. It is off unless you ask for it, because the privilege metadata
REM usually answers the question on its own.
REM
REM WHAT IT ANSWERS, and why it is worth the run:
REM
REM   1. The schema-context resource quote line 4 sells — real table and column
REM      names, so the interface writes valid SQL instead of guessing.
REM   2. Whether the BI role can already only SELECT, which quote line 1 needs
REM      before the read-only-user ask goes to Innate.
REM   3. Where the vehicle utilisation tables are. Larry asked for those on the
REM      acceptance call and nobody has looked; the run ends with relations
REM      grouped by domain, vehicles first.
REM
REM It is a FULL inventory, deliberately, not a keyword scan. The credits pool
REM was invisible for a week in July because the smoke test scanned only for
REM CREDIT, INVOICE and DEBTOR in the name, and the data sat on the receipts
REM side under RECEIPT.
REM
REM Output:
REM   Dashboards and Data Analysis\Database Reference\
REM     schema_relations_<date>.csv    one row per table/view: kind, columns, rows
REM     schema_columns_<date>.csv      one row per column: type, length, nullable
REM     schema_privileges_<date>.csv   what this login is actually granted
REM     schema_survey_<date>.txt       the console log, incl. domain groupings
REM
REM Its own folder, not _diagnostics: that folder's README says nothing in it is
REM a source of truth and is safe to delete once read, and this is the opposite —
REM it is reference material the build works from. Filenames carry the run date
REM and nothing is wiped, because the schema changes when Parcel Perfect is
REM upgraded and an older survey is evidence of what was true then. Newest wins.
REM
REM Nothing here contains customer data — table names, column names, row counts
REM and grants only. No rows are exported.
REM
REM Plain "python" will NOT work: the system interpreter does not have
REM firebirdsql or python-dotenv. Those live in the venv that "uv sync" created,
REM hence the fallback below.

setlocal
set SYNCED=C:\Users\AkhaM\OneDrive - Sunrise Express\Claude General - Documents
set REPORTS=%SYNCED%\Dashboards and Data Analysis
set OUT=%REPORTS%\Database Reference
cd /d C:\Users\AkhaM\Sunrise-Frequency-Reporting

if not exist "%OUT%" mkdir "%OUT%"

REM A note for anyone who finds this folder without context.
> "%OUT%\README.txt" echo This folder is a MAP OF THE DATABASE, not a report.
>>"%OUT%\README.txt" echo.
>>"%OUT%\README.txt" echo   schema_relations_*.csv   every table and view in Parcel Perfect, with
>>"%OUT%\README.txt" echo                            its column count and row count.
>>"%OUT%\README.txt" echo   schema_columns_*.csv     every column, with its type and whether it
>>"%OUT%\README.txt" echo                            can be empty.
>>"%OUT%\README.txt" echo   schema_privileges_*.csv  what the reporting login is allowed to do.
>>"%OUT%\README.txt" echo   schema_survey_*.txt      the full log of the run that produced them.
>>"%OUT%\README.txt" echo.
>>"%OUT%\README.txt" echo Produced by run_schema_survey.bat. Names and counts only - no customer
>>"%OUT%\README.txt" echo data, no waybills, no figures. Files are dated; the newest set is the
>>"%OUT%\README.txt" echo current one, and older sets are kept as a record of what the database
>>"%OUT%\README.txt" echo looked like before a Parcel Perfect upgrade.

where uv >nul 2>nul
if %ERRORLEVEL%==0 goto :use_uv
if exist .venv\Scripts\python.exe goto :use_venv

echo.
echo Found neither uv on PATH nor .venv\Scripts\python.exe in the repo.
echo.
echo   - uv is usually at %%USERPROFILE%%\.local\bin\uv.exe, so try:
echo       "%USERPROFILE%\.local\bin\uv.exe" run research/schema_survey.py --out-dir "%OUT%"
echo   - or rebuild the environment from the repo:
echo       uv venv --python 3.13
echo       uv sync
echo.
exit /b 1

:use_uv
uv run research/schema_survey.py --out-dir "%OUT%" %*
goto :done

:use_venv
echo uv not on PATH — using the project venv instead.
.venv\Scripts\python.exe research\schema_survey.py --out-dir "%OUT%" %*
goto :done

:done
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo FAILED with exit code %ERRORLEVEL%.
    echo The message above says why.
    exit /b %ERRORLEVEL%
)
echo.
echo Output written to:
echo   %OUT%
exit /b 0
