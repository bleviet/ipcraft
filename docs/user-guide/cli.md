# CLI Reference

IPCraft provides five commands: `new`, `generate`, `parse`, `list-buses`, and `validate`.

```bash
ipcraft <command> [options]
```

---

## `new` -- Scaffold IP Projects

Create a new IP core from template, generating boilerplate `ip.yml` and `mm.yml` files.

```bash
ipcraft new <name> [options]
```

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--vendor` | `ipcraft` | VLNV vendor name |
| `--library` | `examples` | VLNV library name |
| `--version` | `1.0.0` | VLNV version |
| `--bus` | None | Include a default bus interface (e.g., `AXI4_LITE`) |
| `--output`, `-o` | `.` | Output directory |

### Examples

```bash
# Basic IP core
ipcraft new my_core

# Custom VLNV and output directory
ipcraft new my_core --vendor mycompany --library peripherals --version 2.0 -o ./my-project

# Scaffold with AXI4-Lite bus interface
ipcraft new my_core --bus AXI4_LITE
```

### Output

The command generates `<name>.ip.yml` and optionally `<name>.mm.yml` files. It also prints an ASCII diagram of the resulting IP core symbol:

```text
✓ Generated ./my_core.ip.yml
✓ Generated ./my_core.mm.yml

IP Core Symbol:
    +--------------------------+
    |         my_core          |
    |--------------------------|
--> | s_axi_aclk               |
--> | s_axi_aresetn            |
--> | [AXI4_LITE] S_AXI_LITE     |
    +--------------------------+
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
| `--template-dir`, `--methodology` | None | Path to custom Jinja2 template directory (can be used multiple times) |
| `--dump-context` | Off | Dump template context to `template_context.json` for template development |
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

# Dump template context to explore available Jinja2 variables
ipcraft generate my_core.ip.yml --dump-context

# Use a custom template methodology
ipcraft generate my_core.ip.yml --template-dir ./my-methodology
```

### Generated File Structure

```
output/
  rtl/
    {name}_pkg.vhd        # Package with types and records
    {name}.vhd            # Top-level entity
    {name}_core.vhd       # Core logic (bus-agnostic) — UNMANAGED
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

### Managed vs. unmanaged files

By default, every generated file is **managed** — it will be overwritten on the
next `generate` run.  The exception is `{name}_core.vhd`, which is marked
`managed: false` in the `fileSets` section of the IP YAML so your core logic is
never lost.

You can protect any other file you have customised by adding `managed: false` to
its entry in `fileSets`:

```yaml
fileSets:
  - name: RTL_Sources
    files:
      - path: rtl/my_core_axil.vhd
        type: vhdl
        managed: false   # I've hand-edited the AXI wrapper — preserve it
```

Files marked `managed: false` are only created on the first `generate` run (when
they do not yet exist).  Subsequent runs leave them untouched.  All other files
are regenerated as normal.

See [File Sets in the IP YAML spec](ip-yaml-spec.md#file-sets) for the full
`managed` flag reference.

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
ipcraft list-buses AXI4_LITE

# Show AXI4-Lite port definitions
ipcraft list-buses AXI4_LITE --ports
```

### Available Bus Types

| Key | Full Type | Description |
|-----|-----------|-------------|
| `AXI4_LITE` | `ipcraft.busif.axi4_lite.1.0` | AXI4-Lite memory-mapped |
| `AXI_STREAM` | `ipcraft.busif.axi_stream.1.0` | AXI-Stream data flow |
| `AVALON_MM` | `ipcraft.busif.avalon_mm.1.0` | Avalon Memory-Mapped |
| `AVALON_ST` | `ipcraft.busif.avalon_st.1.0` | Avalon Streaming |
| `AXI4_FULL` | `ipcraft.busif.axi4_full.1.0` | AXI4 Full memory-mapped |

---

## JSON Output Mode

All commands support `--json` for structured output, intended for IDE/tool
integration (e.g., VS Code extension). When enabled:

- Output is formatted as JSON objects
- Progress messages use structured format
- Errors include machine-readable context

---

## `validate` -- Validate IP Core YAML

Validates the structural and semantic correctness of an IP core YAML file and any referenced memory maps.

```bash
ipcraft validate <input.yml> [options]
```

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--json` | Off | Output in JSON format (for VS Code integration) |

### Validation Checks

- Address alignment.
- Memory map overlap.
- Missing register references.
- Valid bus interface references.

### Examples

```bash
# Validate my_core.ip.yml
ipcraft validate my_core.ip.yml
```

