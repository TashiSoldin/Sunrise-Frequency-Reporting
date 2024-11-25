# Sunrise-Frequency-Reporting

This script generates frequency reports using a database connection.

## Usage

You can run the report generation script using either the provided Makefile or directly with Python.

### Using the Makefile

To generate reports using the Makefile:

Arguments:
- `DATA_DIR`: (Optional) Path to the directory where the reports will be generated. Default is "data".

Examples:
1. Using default output directory:
   ```
   make generate-report
   ```

2. Specifying a custom output directory:
   ```
   make generate-report DATA_DIR="/custom/path/to/output"
   ```

### Using Python Directly

To run the script directly with Python, use the following command:

Arguments:
- `--output-dir` or `-out-dir`: Path to the directory where the reports will be generated. Default is "data".

Examples:
1. Using default output directory:
   ```
   python report_generation/report_generation.py
   ```

2. Specifying a custom output directory:
   ```
   python report_generation/report_generation.py --output-dir "/custom/path/to/output"
   ```

3. Using short flag:
   ```
   python report_generation/report_generation.py -out-dir "/custom/path/to/output"
   ```

## Notes

- The script will automatically create output directories for booking and frequency reports within the specified output directory.
- Make sure you have the required dependencies installed before running the script.