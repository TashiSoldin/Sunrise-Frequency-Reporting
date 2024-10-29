PYTHON = python
SCRIPT_DIR = report_generation
SCRIPT = $(SCRIPT_DIR)/report_generation.py
DEFAULT_DATA_DIR = data

.PHONY: generate-report
generate-report:
	@if [ -z "$(FILE)" ]; then \
		echo "Error: FILE is not set. Usage: make generate-report FILE='your_file_name.xlsx' [DATA_DIR='/path/to/data']"; \
		exit 1; \
	fi
	@echo "Generating reports..."
	@cd $(SCRIPT_DIR) && $(PYTHON) report_generation.py --file "$(FILE)" $(if $(DATA_DIR),--path "$(DATA_DIR)",--path "$(DEFAULT_DATA_DIR)")

.PHONY: help
help:
	@echo "Usage:"
	@echo "  make generate-report FILE='your_file_name.xlsx' [DATA_DIR='/path/to/data']"
	@echo ""
	@echo "Arguments:"
	@echo "  FILE     : Name of the Excel file to process (required)"
	@echo "  DATA_DIR : Path to the directory containing the Excel file (optional, default: $(DEFAULT_DATA_DIR))"
	@echo ""
	@echo "Example:"
	@echo "  make generate-report FILE='FR Report 23 Oct 16h00.xlsx'"
	@echo "  make generate-report FILE='FR Report 23 Oct 16h00.xlsx' DATA_DIR='/custom/path/to/data'"