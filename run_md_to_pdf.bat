@echo off
REM Render a Markdown document to a branded PDF, for sending to someone who is
REM not going to open a .md file (Reuven, Larry, Innate, Parcel Perfect).
REM
REM   run_md_to_pdf.bat "path\to\document.md"
REM   run_md_to_pdf.bat "path\to\document.md" "path\to\output.pdf"
REM   run_md_to_pdf.bat "path\to\document.md" "" --section-pages
REM
REM The PDF lands beside the .md unless a second argument says otherwise, and
REM replaces an existing one. The look (fonts, title block, tables) is
REM assets\md_to_pdf_template.html; the conversion and the print are
REM md_to_pdf.py. Printing is done by the Edge already on this box, driven by
REM Playwright, which uv fetches into its cache on first use (~37 MB, once);
REM mermaid.js loads from jsdelivr, so a render needs the internet.

setlocal
cd /d C:\Users\AkhaM\Sunrise-Frequency-Reporting

if "%~1"=="" (
    echo Usage: run_md_to_pdf.bat "document.md" ["output.pdf"] [--section-pages]
    exit /b 1
)

set OUTARG=
if not "%~2"=="" set OUTARG=--out "%~2"

where uv >nul 2>nul
if not %ERRORLEVEL%==0 (
    echo uv is not on PATH. It is usually at %%USERPROFILE%%\.local\bin\uv.exe
    exit /b 1
)

uv run --with playwright md_to_pdf.py "%~1" %OUTARG% %3 %4
exit /b %ERRORLEVEL%
