# Sunrise Frequency Reporting

This system generates booking and frequency reports for the Sunrise application.

## Setup

1. Ensure Python 3.x is installed on your system
2. Install required dependencies:
   ```
   pip install -r requirements.txt
   ```

## Running Reports

### On macOS/Linux (using Makefile)

The system provides three main targets in the Makefile:

```bash
# Generate both booking and frequency reports
make generate-all-reports

# Generate only booking reports
make generate-booking-report

# Generate only frequency reports
make generate-frequency-report
```

You can specify a custom output directory:

```bash
make generate-all-reports DATA_DIR="/custom/path/to/output"
```

### On Windows (using batch file)

Use the provided `run_reports.bat` file:

```cmd
# Generate both booking and frequency reports
run_reports.bat

# Generate only booking reports
run_reports.bat --report-type booking

# Generate only frequency reports
run_reports.bat --report-type frequency
```

You can specify a custom output directory and Python interpreter:

```cmd
run_reports.bat --report-type booking --output-dir "C:\reports" --python "C:\path\to\python.exe"
```

### Direct Python Execution

You can also run the Python script directly:

```bash
python report_generation/report_generation.py --output-dir data --report-types booking frequency
```

## CRON Job Setup (Windows Task Scheduler)

Create two scheduled tasks in Windows Task Scheduler:

1. **Frequency Report (11am on weekdays)**:
   - Program/script: `C:\path\to\run_reports.bat`
   - Arguments: `--report-type frequency --output-dir "C:\path\to\reports"`
   - Schedule: Daily, Monday-Friday at 11:00 AM

2. **All Reports (4pm on weekdays)**:
   - Program/script: `C:\path\to\run_reports.bat`
   - Arguments: `--report-type all --output-dir "C:\path\to\reports"`
   - Schedule: Daily, Monday-Friday at 4:00 PM

## Logging and Error Handling

The system logs all activities to `report_generation.log` in the execution directory.

The data extraction and manipulation operations have built-in retry logic:
- 3 retry attempts with exponential backoff
- Detailed error logs to help with troubleshooting

## Troubleshooting

If reports fail to generate:

1. Check the log file `report_generation.log` for error details
2. Verify database connection settings
3. Ensure the output directory exists and is writable