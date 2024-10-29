# Sunrise-Frequency-Reporting

This script generates booking and frequency reports from an Excel file.

## Usage

You can run the report generation script using either the provided Makefile or directly with Python.

### Using the Makefile

To generate reports using the Makefile:

```
make generate-report FILE="your_file_name.xlsx" [DATA_DIR="/path/to/data"]
```

Arguments:
- `FILE`: (Required) Name of the Excel file to process. If the filename contains spaces, enclose it in quotes.
- `DATA_DIR`: (Optional) Path to the directory containing the Excel file. Default is "../data".

Examples:
1. Using default data directory:
   ```
   make generate-report FILE="FR Report 23 Oct 16h00.xlsx"
   ```

2. Specifying a custom data directory:
   ```
   make generate-report FILE="FR Report 23 Oct 16h00.xlsx" DATA_DIR="/custom/path/to/data"
   ```

### Using Python Directly

To run the script directly with Python, use the following command:

```
python report_generation/report_generation.py --file "your_file_name.xlsx" [--path "/path/to/data"]
```

Arguments:
- `--file` or `-f`: (Required) Name of the Excel file to process. If the filename contains spaces, enclose it in quotes.
- `--path` or `-p`: (Optional) Path to the directory containing the Excel file. Default is "../data".

Examples:
1. Using default data directory:
   ```
   python report_generation/report_generation.py --file "FR Report 23 Oct 16h00.xlsx"
   ```

2. Specifying a custom data directory:
   ```
   python report_generation/report_generation.py --file "FR Report 23 Oct 16h00.xlsx" --path "/custom/path/to/data"
   ```

3. Using short flags:
   ```
   python report_generation/report_generation.py -f "FR Report 23 Oct 16h00.xlsx" -p "/custom/path/to/data"
   ```

## Notes

- Ensure that the Excel file exists in the specified directory before running the script.
- The script will automatically create output directories for booking and frequency reports.
- Make sure you have the required dependencies installed before running the script.