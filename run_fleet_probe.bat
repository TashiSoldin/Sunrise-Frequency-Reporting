@echo off
REM Fleet probe — can a vehicle utilisation figure be built, and from what.
REM
REM Run by hand on the BI server, not scheduled. Follow-up to
REM run_schema_survey.bat, and worth running in the same sitting.
REM
REM   run_fleet_probe.bat              last 90 days
REM   run_fleet_probe.bat --days 365   a full year, if 90 days looks thin
REM
REM Any flags you pass are handed straight to the script.
REM
REM WHY. Larry asked on the 6 Aug acceptance call for the vehicle utilisation
REM tables. There are none — the schema survey settled that. Utilisation would
REM be a figure computed from what a vehicle carried against what it can carry,
REM and before agreeing a definition with him we need to know which definitions
REM the data can actually support. A definition resting on a column that is
REM empty in practice is exactly the plausible-looking wrong number this
REM project has produced three times already.
REM
REM It also tests two structural guesses, both of which are guesses until this
REM runs:
REM   1. MANIFEST.MTYPE separates line-haul manifests from delivery tripsheets.
REM   2. AGENT.OWNRESOURCE separates Sunrise's own vehicles from third-party
REM      agents — AGENT holds both, so its 1 220 rows are not 1 220 vehicles.
REM
REM And it checks the waybill-to-trip join. VIEW_WBANALYSE carries no manifest
REM number and neither does WAYBILL; ROUTING does, one row per waybill per leg.
REM That matters to line haul (QT-000005) too, where the July trial could only
REM recover last-touch manifests from the staff export.
REM
REM SAFETY. Read-only, and bounded. Every query over a large table is either
REM grouped or filtered to the date window, so nothing scans ROUTING's 6 million
REM rows or EVENT's 113 million. It reads data pages rather than metadata, so
REM prefer to run it outside the 07:00 and 16:30 windows.
REM
REM Output:
REM   Dashboards and Data Analysis\Database Reference\
REM     fleet_probe_<date>.txt        the full log
REM     fleet_population_<date>.csv   per MTYPE, how populated each candidate
REM                                   utilisation column actually is
REM
REM READ THE POPULATION TABLE FIRST. Any column below about 80% populated
REM cannot carry a definition Larry would rely on, and should be ruled out
REM before it is offered to him rather than after.
REM
REM Plain "python" will NOT work: the system interpreter does not have
REM firebirdsql or python-dotenv. Those live in the venv "uv sync" created.

setlocal
set SYNCED=C:\Users\AkhaM\OneDrive - Sunrise Express\Claude General - Documents
set REPORTS=%SYNCED%\Dashboards and Data Analysis
set OUT=%REPORTS%\Database Reference
cd /d C:\Users\AkhaM\Sunrise-Frequency-Reporting

if not exist "%OUT%" mkdir "%OUT%"

where uv >nul 2>nul
if %ERRORLEVEL%==0 goto :use_uv
if exist .venv\Scripts\python.exe goto :use_venv

echo.
echo Found neither uv on PATH nor .venv\Scripts\python.exe in the repo.
echo.
echo   - uv is usually at %%USERPROFILE%%\.local\bin\uv.exe, so try:
echo       "%USERPROFILE%\.local\bin\uv.exe" run research/fleet_probe.py --out-dir "%OUT%"
echo   - or rebuild the environment from the repo:
echo       uv venv --python 3.13
echo       uv sync
echo.
exit /b 1

:use_uv
uv run research/fleet_probe.py --out-dir "%OUT%" %*
goto :done

:use_venv
echo uv not on PATH — using the project venv instead.
.venv\Scripts\python.exe research\fleet_probe.py --out-dir "%OUT%" %*
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
