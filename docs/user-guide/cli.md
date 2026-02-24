# CLI Reference

IPCraft provides three commands: `generate`, `parse`, and `list-buses`.

```bash
ipcraft <command> [options]
```

---

## `generate` -- IP YAML to VHDL

Generate VHDL, vendor integration files, and testbenches from an IP core YAML
definition.

```bash
ipcraft generate <ip_yaml_file> [options]
```

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--output`, `-o` | Same dir as input | Output directory |
| `--vendor` | `both` | Vendor files: `none`, `intel`, `xilinx`, `both` |
| `--testbench` / `--no-testbench` | `--testbench` | Generate cocotb testbench |
| `--regs` / `--no-regs` | `--regs` | Generate standalone register bank |
| `--update-yaml` / `--no-update-yaml` | `--update-yaml` | Update IP YAML with fileSets |
| `--json` | Off | JSON output for tool integration |
| `--progress` | Off | Enable progress reporting |

### Examples

```bash
# Basic generation
ipcraft generate my_core.ip.yml

# Custom output directory
ipcraft generate my_core.ip.yml --output ./build

# Intel-only vendor files, no testbench
ipcraft generate my_core.ip.yml --vendor intel --no-testbench

# VS Code integration mode
ipcraft generate my_core.ip.yml --json --progress
```

### Generated File Structure

```
output/
  rtl/
    {name}_pkg.vhd        # Package with types and records
    {name}.vhd            # Top-level entity
    {name}_core.vhd       # Core logic (bus-agnostic)
    {name}_axil.vhd       # AXI-Lite bus wrapper
    {name}_regs.vhd       # Standalone register bank
  tb/
    {name}_test.py         # Cocotb testbench
    Makefile               # Simulation makefile
  intel/
    {name}_hw.tcl          # Platform Designer component
  xilinx/
    component.xml          # IP-XACT component descriptor
    xgui/{name}_v*.tcl     # Vivado GUI definition
```

---

## `parse` -- VHDL to IP YAML

Parse a VHDL file and generate an IP core YAML definition with automatic bus
interface detection.

```bash
ipcraft parse <vhdl_file> [options]
```

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--output`, `-o` | `{entity}.ip.yml` | Output file path |
| `--vendor` | `user` | VLNV vendor name |
| `--library` | `ip` | VLNV library name |
| `--version` | `1.0` | VLNV version |
| `--no-detect-bus` | Off | Disable bus interface detection |
| `--memmap FILE` | None | Memory map file to reference |
| `--force`, `-f` | Off | Overwrite existing output file |
| `--json` | Off | JSON output for tool integration |

### Auto-Detection

The parser recognizes:

| Category | Pattern Examples |
|----------|-----------------|
| Bus interfaces | `s_axi_*`, `m_axi_*`, `m_axis_*`, `s_axis_*`, `avs_*`, `avm_*` |
| Clocks | `clk`, `i_clk`, `aclk`, `*_clk` |
| Resets | `rst`, `rst_n`, `aresetn`, `i_rst_n` (polarity auto-detected) |
| Generics | Extracted as parameters with VHDL type preserved |

### Examples

```bash
# Basic parse
ipcraft parse my_core.vhd

# Custom VLNV and memory map reference
ipcraft parse my_core.vhd \
  --vendor mycompany --library peripherals --version 2.0 \
  --memmap my_core.mm.yml

# Force overwrite
ipcraft parse my_core.vhd -f
```

---

## `list-buses` -- Bus Library Query

List available bus types and their port definitions.

```bash
ipcraft list-buses [bus_type] [options]
```

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `bus_type` | None | Specific bus type to inspect |
| `--ports` | Off | Show port-level details |
| `--json` | Off | JSON output for tool integration |

### Examples

```bash
# List all bus types
ipcraft list-buses

# Show AXI4-Lite details
ipcraft list-buses AXI4L

# Show AXI4-Lite port definitions
ipcraft list-buses AXI4L --ports
```

### Available Bus Types

| Key | VLNV | Description |
|-----|------|-------------|
| `AXI4L` | `arm.com/amba/axi4l/r0p0_0` | AXI4-Lite memory-mapped |
| `AXIS` | `arm.com/amba/axis/1.0` | AXI-Stream data flow |
| `AVALON_MM` | `intel.com/avalon/avalon_mm/1.0` | Avalon Memory-Mapped |
| `AVALON_ST` | `intel.com/avalon/avalon_st/1.0` | Avalon Streaming |

---

## JSON Output Mode

All commands support `--json` for structured output, intended for IDE/tool
integration (e.g., VS Code extension). When enabled:

- Output is formatted as JSON objects
- Progress messages use structured format
- Errors include machine-readable context
