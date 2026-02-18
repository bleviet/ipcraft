# ipcore CLI Tool

Command-line tool for IP core scaffolding and generation.

## Installation

The tool requires `ipcore` to be installed. From the project root:

```bash
uv sync
```

## Commands

### `parse` - VHDL to IP YAML

Parse a VHDL file and generate an IP core YAML file with automatic bus interface detection.

```bash
uv run python scripts/ipcore.py parse <vhdl_file> [options]
```

**Examples:**

```bash
# Basic usage - output to {entity}.ip.yml
uv run python scripts/ipcore.py parse my_core.vhd

# Specify output file
uv run python scripts/ipcore.py parse my_core.vhd -o my_core.ip.yml

# Custom VLNV metadata
uv run python scripts/ipcore.py parse my_core.vhd --vendor mycompany --library lib --version 2.0

# Reference a memory map file
uv run python scripts/ipcore.py parse my_core.vhd --memmap my_core.mm.yml

# Disable bus detection (raw port extraction only)
uv run python scripts/ipcore.py parse my_core.vhd --no-detect-bus

# Force overwrite existing file
uv run python scripts/ipcore.py parse my_core.vhd -f

# JSON output for VS Code integration
uv run python scripts/ipcore.py parse my_core.vhd --json
```

**Options:**

| Option | Description |
|--------|-------------|
| `--output`, `-o` | Output .ip.yml path (default: `{entity}.ip.yml`) |
| `--vendor` | VLNV vendor name (default: `user`) |
| `--library` | VLNV library name (default: `ip`) |
| `--version` | VLNV version (default: `1.0`) |
| `--no-detect-bus` | Disable automatic bus interface detection |
| `--memmap FILE` | Path to memory map file to reference |
| `--force`, `-f` | Overwrite existing output file |
| `--json` | JSON output for VS Code integration |

**What gets detected:**

- **Bus interfaces**: AXI4-Lite, AXI-Stream, Avalon-MM (from port prefixes like `s_axi_*`)
- **Clocks**: Ports matching patterns like `clk`, `i_clk`, `aclk`
- **Resets**: Ports matching patterns like `rst`, `rst_n`, `aresetn` (polarity auto-detected)
- **Generics**: Extracted as parameters with VHDL type in description

---

### `generate` - IP YAML to VHDL

Generate VHDL files from an IP core YAML definition.

```bash
uv run python scripts/ipcore.py generate <ip_yaml_file> [options]
```

**Examples:**

```bash
# Basic usage - output to same directory as input
uv run python scripts/ipcore.py generate my_core.ip.yml

# Specify output directory
uv run python scripts/ipcore.py generate my_core.ip.yml --output ./build

# Generate only Intel integration files
uv run python scripts/ipcore.py generate my_core.ip.yml --vendor intel

# Generate only Xilinx integration files
uv run python scripts/ipcore.py generate my_core.ip.yml --vendor xilinx

# Skip testbench generation
uv run python scripts/ipcore.py generate my_core.ip.yml --no-testbench

# Skip register bank generation
uv run python scripts/ipcore.py generate my_core.ip.yml --no-regs

# Don't update the input YAML with fileSets
uv run python scripts/ipcore.py generate my_core.ip.yml --no-update-yaml

# VS Code integration mode
uv run python scripts/ipcore.py generate my_core.ip.yml --json --progress
```

**Options:**

| Option | Description |
|--------|-------------|
| `--output`, `-o` | Output directory (default: same as input) |
| `--vendor` | Vendor files: `none`, `intel`, `xilinx`, `both` (default: `both`) |
| `--testbench` | Generate cocotb testbench (default: true) |
| `--no-testbench` | Skip testbench generation |
| `--regs` | Include standalone register bank (default: true) |
| `--no-regs` | Skip register bank generation |
| `--update-yaml` | Update IP core YAML with fileSets (default: true) |
| `--no-update-yaml` | Don't modify the input YAML file |
| `--json` | JSON output for VS Code integration |
| `--progress` | Enable progress output |

**Generated files:**

```
output/
├── rtl/
│   ├── {name}_pkg.vhd       # Package (types, records)
│   ├── {name}.vhd           # Top-level entity
│   ├── {name}_core.vhd      # Core logic
│   ├── {name}_axil.vhd      # AXI-Lite bus wrapper
│   └── {name}_regs.vhd      # Register bank
├── tb/
│   ├── {name}_test.py       # Cocotb testbench
│   └── Makefile             # Simulation makefile
├── intel/
│   └── {name}_hw.tcl        # Platform Designer
└── xilinx/
    ├── component.xml        # IP-XACT
    └── xgui/{name}_v*.tcl   # Vivado GUI
```

---

### `list-buses` - Available Bus Types

List available bus types from the bus library with their port definitions.

```bash
uv run python scripts/ipcore.py list-buses [bus_type] [options]
```

**Examples:**

```bash
# List all available bus types
uv run python scripts/ipcore.py list-buses

# Show details for specific bus type
uv run python scripts/ipcore.py list-buses AXI4L

# Show port list for a bus type
uv run python scripts/ipcore.py list-buses AXI4L --ports

# JSON output for VS Code integration
uv run python scripts/ipcore.py list-buses --json
```

**Options:**

| Option | Description |
|--------|-------------|
| `bus_type` | Optional bus type to show details for |
| `--ports` | Show port details when viewing a specific bus |
| `--json` | JSON output for VS Code integration |

**Example output:**

```
Available bus types:
  AXI4L        - arm.com/amba/axi4l/r0p0_0
  AXIS         - arm.com/amba/axis/1.0
  AVALON_MM    - intel.com/avalon/avalon_mm/1.0
  AVALON_ST    - intel.com/avalon/avalon_st/1.0

Use 'list-buses <TYPE>' for details, add --ports for port list
```

**Suggested prefixes:**

| Bus Type | Slave/Sink | Master/Source |
|----------|------------|---------------|
| AXI4L | `s_axil_` | `m_axil_` |
| AXIS | `s_axis_` | `m_axis_` |
| AVALON_MM | `avs_` | `avm_` |
| AVALON_ST | `asi_` | `aso_` |

---

## Workflow Examples

### 1. Create IP from existing VHDL

```bash
# Parse VHDL to create initial IP YAML
uv run python scripts/ipcore.py parse my_design.vhd -o my_design.ip.yml

# Edit my_design.ip.yml to add memory maps, adjust ports, etc.

# Generate all outputs
uv run python scripts/ipcore.py generate my_design.ip.yml --output ./build
```

### 2. Round-trip workflow

```bash
# Start with VHDL
uv run python scripts/ipcore.py parse original.vhd -o design.ip.yml

# Customize the YAML (add memory maps, bus interfaces, etc.)
# Then regenerate VHDL
uv run python scripts/ipcore.py generate design.ip.yml --output ./build

# Run cocotb simulation
cd build/tb && make
```

### 3. VS Code Extension Integration

```bash
# JSON mode for programmatic use
uv run python scripts/ipcore.py parse my_core.vhd --json
# Output: {"success": true, "output": "/path/to/my_core.ip.yml"}

uv run python scripts/ipcore.py generate my_core.ip.yml --json --progress
# Output: {"success": true, "files": {...}, "count": 10, "busType": "axil"}

uv run python scripts/ipcore.py list-buses --json
# Output: {"success": true, "buses": [...]}
```

---

## Bus Interface Detection

The `parse` command automatically detects bus interfaces from port naming patterns:

| Bus Type | Prefix Pattern | Example |
|----------|----------------|---------|
| AXI4-Lite Slave | `s_axi_*`, `s_axil_*` | `s_axi_awaddr`, `s_axi_rdata` |
| AXI4-Lite Master | `m_axi_*`, `m_axil_*` | `m_axi_awaddr`, `m_axi_rdata` |
| AXI-Stream Source | `m_axis_*` | `m_axis_tdata`, `m_axis_tvalid` |
| AXI-Stream Sink | `s_axis_*` | `s_axis_tdata`, `s_axis_tready` |
| Avalon-MM Slave | `avs_*` | `avs_address`, `avs_readdata` |

Bus definitions are loaded from `ipcraft-spec/common/bus_definitions.yml`.
