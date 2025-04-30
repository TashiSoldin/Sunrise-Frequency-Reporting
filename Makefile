PYTHON = python # This is executed within the uv venv
SCRIPT = report_generation/report_generation.py
OUTPUT_DIR = data

.PHONY: generate-all-reports generate-booking-report generate-frequency-report help

generate-all-reports:
	@$(PYTHON) $(SCRIPT) --output-dir "$(if $(DATA_DIR),$(DATA_DIR),$(OUTPUT_DIR))" --report-types all

generate-booking-report:
	@$(PYTHON) $(SCRIPT) --output-dir "$(if $(DATA_DIR),$(DATA_DIR),$(OUTPUT_DIR))" --report-types booking

generate-frequency-report:
	@$(PYTHON) $(SCRIPT) --output-dir "$(if $(DATA_DIR),$(DATA_DIR),$(OUTPUT_DIR))" --report-types frequency

generate-pod-agent-report:
	@$(PYTHON) $(SCRIPT) --output-dir "$(if $(DATA_DIR),$(DATA_DIR),$(OUTPUT_DIR))" --report-types pod_agent

help:
	@echo "Usage:"
	@echo "  make generate-all-reports [DATA_DIR='/path/to/output']"
	@echo "  make generate-booking-report [DATA_DIR='/path/to/output']"
	@echo "  make generate-frequency-report [DATA_DIR='/path/to/output']"
	@echo "  make generate-pod-agent-report [DATA_DIR='/path/to/output']"
	@echo ""
	@echo "Arguments:"
	@echo "  DATA_DIR : Path to the directory where the reports will be generated (optional, default: $(OUTPUT_DIR))"
	@echo ""
	@echo "Examples:"
	@echo "  make generate-all-reports"
	@echo "  make generate-booking-report DATA_DIR='/custom/path/to/output'"
	@echo "  make generate-frequency-report"