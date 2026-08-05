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

# Generate only pod summary reports
make generate-pod-summary-report

# Generate only champion reports
make generate-champion-report
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

# Generate only pod summary reports
./run_reports.bat --pod_summary

# Generate only champion reports
./run_reports.bat --champion
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

## Revenue Reports

A second pipeline (`revenue_reports/`) extracts from Parcel Perfect and builds the
five daily revenue workbooks — Flash Revenue, Revenue Dashboard, Billing Detail,
Unbilled and Credit Notes — then emails them to `exco@sunriselogistics.net`.

Everything is one day in arrears: today's waybills and invoices are still being
captured while the reports run, so a same-day report is always a partial. The
flash uses the latest waybill date *before* today, which rolls back over
weekends and public holidays rather than reporting a day with no trading.

### Schedule

| Time  | Command | Reports | Email |
|-------|---------|---------|-------|
| 07:00 | `run_revenue_flash.bat` | Flash Revenue | 1 attachment |
| 16:30 | `run_revenue_pm.bat` | Dashboard, Billing Detail, Unbilled, Credit Notes | 4 attachments |

Register both as Windows Task Scheduler jobs on the BI server, weekdays, "Run
whether user is logged on or not". Edit `SYNCED` in each .bat to match the local
OneDrive/SharePoint sync root for the "Claude General" library.

### Running by hand

```cmd
uv run revenue_reports/run_daily.py --only flash ^
    --data-dir  "<synced>\Dashboards and Data Analysis\2. Revenue Data" ^
    --report-dir "<synced>\Dashboards and Data Analysis"
```

| Flag | Effect |
|------|--------|
| `--only {all,flash,pm}` | Which set of reports to build |
| `--skip-extract` | Rebuild from the existing export files, no DB hit |
| `--no-email` | Build and save only — nothing is sent |
| `--dry-run-email` | Print what would be sent, send nothing |
| `--to a@b.com` | Send to someone else instead of exco (test runs) |

Use `--no-email` or `--to` for any test run. Without them, exco gets the mail.

### Email configuration

Recipients are in code (`revenue_reports/mailer.py`), matching the convention in
`report_generation/enums/email_enums.py` — they are config, not secrets. Sending
reuses the existing SMTP client but not its mailbox, so the server `.env` needs
two pairs, with no fallback between them:

```
DASHBOARDS_EMAIL_ADDRESS=...   # dashboarding reports (revenue_reports/)
DASHBOARDS_EMAIL_PASSWORD=...  # app password
SENDER_EMAIL_ADDRESS=...       # frequency, booking, POD (report_generation/)
SENDER_EMAIL_PASSWORD=...      # app password
```

If either is missing the run fails after the workbooks are written, so the files
still land in SharePoint even when mail is misconfigured.

## CRON Job Setup (Windows Task Scheduler)

Create two scheduled tasks in Windows Task Scheduler:

1. **Booking, POD agent, POD ocd and POD summary report (6am on weekdays)**
2. **Frequency Report (11am on weekdays)**:
3. **Frequency Reports (4pm on weekdays)**:

## Logging and Error Handling

The system logs all activities to the `logs` directory with automatic rotation:
- Logs are kept for 30 days
- Daily rotation at midnight
- Detailed information about execution time and errors

The revenue pipeline logs the same way, via `run_daily.py` — one rotating file
covering both scheduled runs, rolled at midnight and kept for 30 days:

```
logs\run_revenue\run_revenue.log
logs\run_revenue\run_revenue.log.2026-07-30
```

The batch files do no log management of their own. They redirect only stderr to
`logs\run_revenue\bootstrap.log`, which catches failures that happen before
logging is configured (uv missing, import errors), and return the pipeline's
exit code so a failed run shows as failed in Task Scheduler.

## Troubleshooting

If reports fail to generate:

1. Check the log file `report_generation.log` for error details
2. Verify database connection settings
3. Ensure the output directory exists and is writable