# Vendor Toolchain Validation Environment Plan

## 1. Overview & Objectives

The goal is to provide a robust, automated methodology for verifying that the outputs of `ipcraft` (VHDL/Verilog, Vendor XML/Tcl) are syntactically correct and synthesisable using vendor toolchains. 

Specifically, this environment will prove **Toolchain Acceptance**: Xilinx Vivado and Intel Quartus can parse, package, and structure the IP core without manual intervention.

*Note: QEMU co-simulation and C/C++ generation testing are consciously deferred to a later point. The current scope focuses exclusively on establishing the RTL and vendor test harness using local Developer and Docker sandbox setups.*

## 2. Phase 1: Local Docker & Vendor CLI Validation

To guarantee that generated IP works seamlessly, we will integrate Headless/Batch vendor tools running in a local Developer/Docker sandbox.

### Xilinx Vivado Validation
- **Action:** Run Vivado in batch mode to package the IP and run Out-Of-Context (OOC) synthesis.
- **Implementation:**
  Provide a generic Tcl script (`tests/toolchain/validate_xilinx.tcl`) that:
  ```tcl
  create_project -in_memory ip_val_proj
  # Target a generic part, e.g. xc7z020
  set_property part xc7z020clg400-1 [current_project]
  read_vhdl [glob rtl/*.vhd]
  read_ipxact xilinx/component.xml
  ipxact::load_core xilinx/component.xml
  synth_design -top <target_entity> -mode out_of_context
  ```
- **Success Criteria:** Zero synthesis/elaboration errors.

### Intel Quartus / Platform Designer Validation
- **Action:** Validate `_hw.tcl` properties and run Quartus Analysis & Elaboration.
- **Implementation:**
  Use Intel's CLI tools via a wrapper script (`tests/toolchain/validate_intel.sh`):
  ```bash
  # Check Platform Designer Tcl
  qsys-script --script=intel/mycore_hw.tcl --cmd="validate_component mycore"
  
  # Run Analysis & Elaboration mapped to a common device
  quartus_map mycore_project --family="Cyclone V" 
  ```
- **Success Criteria:** Zero synthesis/elaboration errors. Active automated tests currently confirm 100% success mapping the 5 native bus protocols directly in Quartus:
  - **AXI4-Lite** (`ipcraft.busif.axi4_lite.1.0`)
  - **AXI4-Full** (`ipcraft.busif.axi4_full.1.0`)
  - **AXI-Stream** (`ipcraft.busif.axi_stream.1.0`)
  - **Avalon-MM** (`ipcraft.busif.avalon_mm.1.0`)
  - **Avalon-ST** (`ipcraft.busif.avalon_st.1.0`)

## 3. Infrastructure: Developer Sandbox Setup

The core deliverables for this test environment will be:
- **Dockerfile:** A `tests/toolchain/Dockerfile` that configures environment variables so developers can mount their local Vivado/Quartus installations into the standard test sandbox (since redistributing exact vendor toolchain blobs isn't feasible).
- **Test Harness Scripts:** A dedicated `tests/toolchain/Makefile` with entry points like `make test-vivado` or `make test-quartus` that are run locally in the `tests/toolchain` directory.
- **Example IP Core:** Generated IP cores built strictly to pass these tests inside the CI sandbox, executed via driver scripts like `tests/supported_buses/test_all.sh`.
