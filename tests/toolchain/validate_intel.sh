#!/bin/bash
# Intel Quartus validation script for generated IP
# Usage: ./validate_intel.sh <ip_dir> <top_entity>

set -e

if [ "$#" -ne 2 ]; then
    echo "Error: Expected 2 arguments: <ip_dir> <top_entity>"
    exit 1
fi

if [[ "$1" != /* ]]; then
    # Convert to absolute path if relative
    IP_DIR="$(pwd)/$1"
else
    IP_DIR="$1"
fi
TOP_ENTITY=$2

BUILD_DIR="build/intel_val_${TOP_ENTITY}"
mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"

echo "================================================="
echo " Validating IP in Quartus/Platform Designer: $TOP_ENTITY"
echo " Directory: $IP_DIR"
echo " Sandbox: $BUILD_DIR"
echo "================================================="

HW_TCL="$IP_DIR/intel/${TOP_ENTITY}_hw.tcl"

# 1. Validate the Platform Designer (Qsys) component
if [ -f "$HW_TCL" ]; then
    echo "Running qsys-script validation on $HW_TCL..."
    # The --cmd option uses search-path to find the component and attempts to instantiate it
    qsys-script --search-path="$(dirname "$HW_TCL"),$" --cmd="package require -exact qsys 16.0; create_system test_sys; add_instance ip1 $TOP_ENTITY; save_system test_sys.qsys"
else
    echo "Warning: No Platform Designer script found at $HW_TCL"
fi

# 2. Run Quartus Analysis & Elaboration
echo "Running Quartus Analysis & Elaboration..."
# Clean up previous dummy projects if any
rm -rf dummy_project* test_sys*

# Create a dummy project
quartus_sh --prepare -f "Cyclone V" dummy_project

# Map the VHDL files into the project
echo "" >> dummy_project.qsf
for vhdl_file in $IP_DIR/rtl/*.vhd; do
    echo "set_global_assignment -name VHDL_FILE $vhdl_file" >> dummy_project.qsf
done
echo "set_global_assignment -name TOP_LEVEL_ENTITY $TOP_ENTITY" >> dummy_project.qsf

# Run Analysis & Synthesis (map)
quartus_map dummy_project

echo "================================================="
echo " Intel validation completed successfully."
echo "================================================="
