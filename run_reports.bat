@echo off
setlocal enabledelayedexpansion

:: Set default values
set "OUTPUT_DIR=data"
set "PYTHON_CMD=uv run"
set "SCRIPT=report_generation/report_generation.py"
set "REPORT_TYPES="

:parse
if "%~1"=="" goto :endparse
if /i "%~1"=="--booking" (
    set "REPORT_TYPES=!REPORT_TYPES! booking"
) else if /i "%~1"=="--frequency" (
    set "REPORT_TYPES=!REPORT_TYPES! frequency"
) else if /i "%~1"=="--pod_agent" (
    set "REPORT_TYPES=!REPORT_TYPES! pod_agent"
) else if /i "%~1"=="--pod_ocd" (
    set "REPORT_TYPES=!REPORT_TYPES! pod_ocd"
) else if /i "%~1"=="--all" (
    set "REPORT_TYPES=all"
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
if "%REPORT_TYPES%"=="" goto :usage

:: Run the report generation script
%PYTHON_CMD% %SCRIPT% --output-dir "%OUTPUT_DIR%" --report-types %REPORT_TYPES%
goto :end

:usage
echo Usage:
echo   run_reports.bat [--booking^|--frequency^|--pod_agent^|--pod_ocd^|--all] [--output-dir OUTPUT_DIR]
echo.
echo Options:
echo   --booking      Generate booking reports
echo   --frequency    Generate frequency reports
echo   --pod_agent    Generate pod agent reports
echo   --pod_ocd      Generate pod ocd reports
echo   --all          Generate all report types
echo   --output-dir   Specify output directory (default: data)
echo   --help         Show this help message
echo.
echo Examples:
echo   run_reports.bat --all
echo   run_reports.bat --booking --output-dir C:\reports
echo   run_reports.bat --frequency
echo   run_reports.bat --booking --frequency
:end

endlocal
exit /b 0
