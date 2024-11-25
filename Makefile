PYTHON = python
SCRIPT = report_generation/report_generation.py
OUTPUT_DIR = data

.PHONY: generate-report
generate-report:
	@echo "Generating reports..."
	@$(PYTHON) $(SCRIPT) --output-dir "$(if $(DATA_DIR),$(DATA_DIR),$(OUTPUT_DIR))"

.PHONY: help
help:
	@echo "Usage:"
	@echo "  make generate-report [DATA_DIR='/path/to/output']"
	@echo ""
	@echo "Arguments:"
	@echo "  DATA_DIR : Path to the directory where the reports will be generated (optional, default: $(OUTPUT_DIR))"
	@echo ""
	@echo "Example:"
	@echo "  make generate-report"
	@echo "  make generate-report DATA_DIR='/custom/path/to/output'"