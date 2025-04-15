@echo off
setlocal enabledelayedexpansion

:: Set default values
set "OUTPUT_DIR=data"
set "PYTHON_CMD=python"
set "SCRIPT=report_generation/report_generation.py"

:: Activate virtual environment
call venv\Scripts\activate.bat

:: Process command line arguments
set "REPORT_TYPE="
:parse
if "%~1"=="" goto :endparse
if /i "%~1"=="--booking" (
    set "REPORT_TYPE=booking"
) else if /i "%~1"=="--frequency" (
    set "REPORT_TYPE=frequency"
) else if /i "%~1"=="--all" (
    set "REPORT_TYPE=all"
) else if /i "%~1"=="--output-dir" (
    if "%~2"=="" (
        echo Error: Missing value for --output-dir
        goto :usage
    )
    set "OUTPUT_DIR=%~2"
    shift
) else if /i "%~1"=="--help" (
    goto :usage
) else (
    echo Error: Unknown option "%~1"
    goto :usage
)
shift
goto :parse
:endparse

:: If no report type specified, show usage
if "%REPORT_TYPE%"=="" goto :usage

:: Run the report generation script
if "%REPORT_TYPE%"=="all" (
    %PYTHON_CMD% %SCRIPT% --output-dir "%OUTPUT_DIR%" --report-types all
) else (
    %PYTHON_CMD% %SCRIPT% --output-dir "%OUTPUT_DIR%" --report-types %REPORT_TYPE%
)
goto :end

:usage
echo Usage:
echo   run_reports.bat [--booking^|--frequency^|--all] [--output-dir OUTPUT_DIR]
echo.
echo Options:
echo   --booking      Generate booking reports
echo   --frequency    Generate frequency reports
echo   --all          Generate all report types
echo   --output-dir   Specify output directory (default: data)
echo   --help         Show this help message
echo.
echo Examples:
echo   run_reports.bat --all
echo   run_reports.bat --booking --output-dir C:\reports
echo   run_reports.bat --frequency

:end
:: Deactivate virtual environment
call deactivate

endlocal
exit /b 0
