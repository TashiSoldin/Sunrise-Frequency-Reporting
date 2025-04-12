@echo off
setlocal enabledelayedexpansion

REM Default values
set "PYTHON_CMD=python"
set "SCRIPT=report_generation\report_generation.py"
set "OUTPUT_DIR=data"
set "REPORT_TYPE=all"

REM Parse command line arguments
:parse_args
if "%~1"=="" goto :run
if /i "%~1"=="--python" (
    set "PYTHON_CMD=%~2"
    shift & shift
    goto :parse_args
)
if /i "%~1"=="--output-dir" (
    set "OUTPUT_DIR=%~2"
    shift & shift
    goto :parse_args
)
if /i "%~1"=="--report-type" (
    set "REPORT_TYPE=%~2"
    shift & shift
    goto :parse_args
)
shift
goto :parse_args

:run
echo Running %REPORT_TYPE% report(s) at %date% %time%...

REM Create output directory if it doesn't exist
if not exist "%OUTPUT_DIR%" mkdir "%OUTPUT_DIR%"

REM Build command
set "CMD=%PYTHON_CMD% %SCRIPT% --output-dir %OUTPUT_DIR% --report-types %REPORT_TYPE%"

echo Executing: %CMD%
%CMD%

if errorlevel 1 (
    echo Error: Report generation failed with exit code %errorlevel%
    exit /b %errorlevel%
) else (
    echo Report generation completed successfully
)

endlocal
exit /b 0
