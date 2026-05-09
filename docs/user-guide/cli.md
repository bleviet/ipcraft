# CLI Reference

IPCraft provides six commands: `init`, `new`, `generate`, `parse`, `list-buses`, and `validate`.

```bash
ipcraft [--debug] [-v] <command> [options]
```

## Global Flags

These flags work on every subcommand:

| Flag | Description |
|------|-------------|
| `--debug` | Show the full Python traceback on errors instead of a one-line summary |
| `-v`, `--verbose` | Enable per-step progress output |
| `--version` | Print the installed version and exit |

---

## `init` -- Interactive Wizard

Launch a guided TUI wizard that collects project details interactively, then
scaffolds the YAML files and runs generation automatically. This is the
recommended starting point for new users.

```bash
ipcraft init [TEMPLATE.ip.yml]
```

### Startup Modes

| Mode | How to trigger | Description |
|------|---------------|-------------|
| **Fresh** | Run `ipcraft init` with no arguments | Answer a short sequence of questions (name, bus type, vendor, etc.) and generate from scratch |
| **Template** | Pass an existing `.ip.yml` as the argument | Clone an existing core under a new name without touching the original |

### Fresh Mode — Wizard Steps

1. **Mode selection** — choose *fresh* or pick an example from the built-in catalog
2. **Bus type** — select from AXI4-Lite, AXI4-Full, AXI-Stream, Avalon-MM, Avalon-ST, or None
3. **Core name** — used as the filename prefix and VHDL entity name
4. **Vendor / library / version** — VLNV metadata (defaults provided)
5. **Output directory** — where to write files (defaults to `.`)
6. The wizard scaffolds `<name>.ip.yml` and `<name>.mm.yml`, then immediately runs `generate`

### Template Mode

```bash
# Clone an existing IP core under a new name
ipcraft init path/to/existing_core.ip.yml
```

The wizard asks only for the new core name and output directory. All other
settings are inherited from the source file.

### Examples

```bash
# Start the interactive wizard (recommended for new users)
ipcraft init

# Clone an existing IP core as a starting point
ipcraft init examples/led_controller.ip.yml
```

!!! note
    For non-interactive use (CI scripts, Makefiles), use `ipcraft new` +
    `ipcraft generate` instead.

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
| `--template-dir`, `--methodology` | None | Path to custom Jinja2 template directory (can be used multiple times). See [Custom Templates](templates.md). |
| `--dump-context` | Off | Dump template context to `template_context.json` for template development |
| `--dry-run` | Off | Preview which files would be written or skipped without touching the filesystem |
| `--watch` | Off | Watch input YAML files and re-generate automatically on change (Ctrl+C to stop) |
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

# Preview what would be written without touching the filesystem
ipcraft generate my_core.ip.yml --dry-run

# Watch YAML files and re-generate on every save
ipcraft generate my_core.ip.yml --watch

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
  docs/
    {name}_regmap.md       # Markdown register map (summary + bit-field tables)
  intel/
    {name}_hw.tcl          # Platform Designer component
  xilinx/
    component.xml          # IP-XACT component descriptor
    package_ip.tcl         # Vivado IP packaging script
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

## `parse` -- Source File to IP YAML

Parse a hardware description file and generate an IP core YAML definition.
Supports multiple source formats with automatic detection.

```bash
ipcraft parse <source_file> [options]
```

### Supported Input Formats

| Extension / Pattern | Format | Parser |
|--------------------|--------|--------|
| `.vhd`, `.vhdl` | VHDL | `VHDLParser` + `BusInterfaceDetector` |
| `.v`, `.sv` | Verilog / SystemVerilog | `VerilogParser` + `BusInterfaceDetector` |
| `*_hw.tcl`, `*.tcl` | Intel Platform Designer | `HwTclParser` |
| `component.xml` | Xilinx IP-XACT | `IpXactParser` |

The format is detected automatically from the file extension and content.

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--output`, `-o` | Same dir as input | Output directory (or `.yml` path for VHDL legacy mode) |
| `--mm` | Off | Also generate a `.mm.yml` register-map skeleton alongside the `.ip.yml` |
| `--dry-run` | Off | Print which files would be written without writing anything |
| `--vendor` | `user` | VLNV vendor name |
| `--library` | `ip` | VLNV library name |
| `--version` | `1.0` | VLNV version |
| `--no-detect-bus` | Off | Disable bus interface detection from port name prefixes |
| `--memmap FILE` | None | Memory map file to reference (VHDL legacy mode only) |
| `--force`, `-f` | Off | Overwrite existing output files |
| `--json` | Off | JSON output for tool integration |

### Auto-Detection (HDL Files)

For VHDL and Verilog inputs, the parser recognizes:

| Category | Pattern Examples |
|----------|-----------------|
| Bus interfaces | `s_axi_*`, `m_axi_*`, `m_axis_*`, `s_axis_*`, `avs_*`, `avm_*` |
| Clocks | `clk`, `i_clk`, `aclk`, `*_clk` |
| Resets | `rst`, `rst_n`, `aresetn`, `i_rst_n` (polarity auto-detected) |
| Generics | Extracted as parameters with VHDL type preserved |

### Examples

```bash
# Parse a VHDL file
ipcraft parse my_core.vhd

# Parse a Verilog file
ipcraft parse my_core.v

# Import from Intel Platform Designer component
ipcraft parse my_core_hw.tcl

# Import from Xilinx IP-XACT
ipcraft parse component.xml

# Parse and also generate a memory map skeleton
ipcraft parse my_core.vhd --mm

# Preview what would be written
ipcraft parse my_core.vhd --dry-run

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

