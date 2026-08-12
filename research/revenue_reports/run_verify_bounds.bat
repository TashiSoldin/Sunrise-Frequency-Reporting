@echo off
REM Date-bounds check — run by hand on the BI server, not scheduled.
REM
REM Verifies the FY ceiling added to extract_revenue.extraction_sql. Read-only
REM against Parcel Perfect: SELECTs only, sends nothing, and does not touch the
REM production exports. Safe between the 07:00 and 16:30 jobs.
REM
REM Writes a dated .txt log and a dropped-rows .csv into the synced
REM _diagnostics folder, so the results can be read off the share afterwards
REM instead of only existing inside the RDP session.
REM
REM   research\run_verify_bounds.bat
REM
REM The other two bats assume uv is on PATH, which it is for the Task Scheduler
REM user but often is not in an interactive shell — hence the fallback below to
REM the project venv. Plain "python" will NOT work: the system interpreter does
REM not have firebirdsql, python-calamine or python-dotenv. Those live in the
REM venv that "uv sync" created.

setlocal
set SYNCED=C:\Users\AkhaM\OneDrive - Sunrise Express\Claude General - Documents
set DIAG=%SYNCED%\Dashboards and Data Analysis\2. Revenue Data\_diagnostics
cd /d C:\Users\AkhaM\Sunrise-Frequency-Reporting

where uv >nul 2>nul
if %ERRORLEVEL%==0 goto :use_uv
if exist .venv\Scripts\python.exe goto :use_venv

echo.
echo Found neither uv on PATH nor .venv\Scripts\python.exe in the repo.
echo.
echo   - uv is usually at %%USERPROFILE%%\.local\bin\uv.exe, so try:
echo       "%USERPROFILE%\.local\bin\uv.exe" run research/verify_date_bounds.py --out-dir "%DIAG%"
echo   - or rebuild the environment from the repo:
echo       uv venv --python 3.13
echo       uv sync
echo.
exit /b 1

:use_uv
uv run research/verify_date_bounds.py --out-dir "%DIAG%"
goto :done

:use_venv
echo uv not on PATH — using the project venv instead.
.venv\Scripts\python.exe research\verify_date_bounds.py --out-dir "%DIAG%"
goto :done

:done
echo.
echo Output written to:
echo   %DIAG%
exit /b %ERRORLEVEL%
