# Sunrise Frequency Reporting

This system generates booking and frequency reports for the Sunrise application.

## Setup

1. Ensure Python 3.13 is installed on your system, inline with the python version file
2. Install required dependencies using uv package manager
   ```
   uv python install 3.13
   uv venv --python 3.13
   uv sync
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

# Generate only pod agent reports
make generate-pod-agent-report

# Generate only pod ocd reports
make generate-pod-ocd-report
```

You can specify a custom output directory:

```bash
make generate-all-reports DATA_DIR="/custom/path/to/output"
```

### On Windows (using batch file)

Use the provided `run_reports.bat` file:

```cmd
# Generate both booking and frequency reports
./run_reports.bat --all

# Generate only booking reports
./run_reports.bat --booking

# Generate only frequency reports
./run_reports.bat --frequency

# Generate only pod agent reports
./run_reports.bat --pod_agent

# Generate only pod ocd reports
./run_reports.bat --pod_ocd
```

You can specify a custom output directory:

```cmd
./run_reports.bat --booking --output-dir "C:\reports"
```

### Direct Python Execution

You can also run the Python script directly:

```bash
uv run report_generation/report_generation.py --output-dir data --report-types booking frequency
```

## CRON Job Setup (Windows Task Scheduler)

Create two scheduled tasks in Windows Task Scheduler:

1. **Frequency Report (11am on weekdays)**:
   - Program/script: `C:\path\to\run_reports.bat`
   - Arguments: `--frequency --output-dir "C:\path\to\reports"`
   - Schedule: Daily, Monday-Friday at 11:00 AM

2. **All Reports (4pm on weekdays)**:
   - Program/script: `C:\path\to\run_reports.bat`
   - Arguments: `--all --output-dir "C:\path\to\reports"`
   - Schedule: Daily, Monday-Friday at 4:00 PM

## Logging and Error Handling

The system logs all activities to the `logs` directory with automatic rotation:
- Logs are kept for 30 days
- Daily rotation at midnight
- Detailed information about execution time and errors

## Troubleshooting

If reports fail to generate:

1. Check the log file `report_generation.log` for error details
2. Verify database connection settings
3. Ensure the output directory exists and is writable