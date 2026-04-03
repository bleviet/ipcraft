# Toolchain Validation Makefile
# Provides commands for validating generated IP cores with vendor tools

.PHONY: help test-toolchain test-vivado test-quartus

help:
	@echo "ipcraft Toolchain Validation Commands:"
	@echo ""
	@echo "  make test-vivado IP_DIR=... TOP_ENTITY=..."
	@echo "  make test-quartus IP_DIR=... TOP_ENTITY=..."
	@echo "  make test-toolchain IP_DIR=... TOP_ENTITY=..."
	@echo ""
	@echo "Paths should be relative to the tests/toolchain directory, or absolute."

test-toolchain: test-vivado test-quartus

test-vivado:
	@echo "=> Running Vivado validation on generated IP. Usage: make test-vivado IP_DIR=... TOP_ENTITY=..."
	@if [ -z "$(IP_DIR)" ] || [ -z "$(TOP_ENTITY)" ]; then \
		echo "Error: Must provide IP_DIR and TOP_ENTITY. Example: make test-vivado IP_DIR=../generated/pwm_core TOP_ENTITY=pwm_core"; \
		exit 1; \
	fi
	@mkdir -p build
	vivado -mode batch -journal build/xilinx_val_$(TOP_ENTITY).jou -log build/xilinx_val_$(TOP_ENTITY).log -source validate_xilinx.tcl -tclargs $(IP_DIR) $(TOP_ENTITY)

test-quartus:
	@echo "=> Running Quartus validation on generated IP"
	@if [ -z "$(IP_DIR)" ] || [ -z "$(TOP_ENTITY)" ]; then \
		echo "Error: Must provide IP_DIR and TOP_ENTITY."; \
		exit 1; \
	fi
	./validate_intel.sh $(IP_DIR) $(TOP_ENTITY)
