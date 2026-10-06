# CLI Reference

IPCraft provides these commands: `init`, `new`, `generate`, `parse`, `list-buses`, `validate`, `verify`, `migrate`,
`import`, `instance`, `pack`, and `preview-template`.

`generate`, `verify`, `migrate`, `import`, `instance`, `pack` and `preview-template` share their behaviour, flags
and output with the `ipcraft` CLI of the [ipcraft-vscode](https://github.com/bleviet/ipcraft-vscode) extension, so a
project can be driven from VS Code and from Python/CI interchangeably.

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


---

## `verify` -- Detect Stale Generated Output

Regenerates an IP core in memory and compares it with a generated directory.
Exits `1` if any file differs, is missing, or is orphaned (present in a generated
top-level directory such as `rtl/` but no longer produced). Files marked
`managed: false` are exempt. Use it in CI to catch drift between an edited
`.ip.yml` and committed output.

```bash
ipcraft verify <ip_yaml_file> <generated_dir> [--vendor none|intel|xilinx|both]
               [--no-testbench] [--no-regs] [--template-dir DIR] [--json]
```

Pass the same `--vendor` / `--no-testbench` / `--no-regs` flags you used for `generate`.

---

## `migrate` -- Convert Legacy Keys

Renames legacy snake_case keys (`address_offset`, `reset_value`, `bit_offset`,
`memory_maps`, `file_sets`, ...) in `.ip.yml` and `.mm.yml` files to their
camelCase spelling. Comments and layout are preserved.

```bash
ipcraft migrate <file>... [--check] [--json]
```

`--check` reports files that need conversion without writing and exits `1` if any do.

---

## Scaffold engine (`generate` / `verify` options)

Giving `generate` or `verify` any of the options below selects the **pack-driven scaffold engine** — the same
engine, templates and file layout (`rtl/`, `tb/`, `altera/`, `xilinx/`) as the ipcraft-vscode extension. Output is
byte-identical to the extension's. Without these options the classic Python generator is used.

| Option | Description |
|--------|-------------|
| `--lang vhdl\|systemverilog` | HDL language (default `vhdl`) |
| `--target quartus\|vivado` | Also scaffold vendor packaging **and** a project (`*_hw.tcl`, `component.xml`, project TCL, SDC/XDC). Repeat or comma-separate |
| `--pack NAME_OR_DIR` | Scaffold pack: a built-in name (`builtin-minimal` — the default —, `builtin-ipcraft`, `example-*`), a pack directory, or `scaffold_pack:` in the `.ip.yml` |
| `--quartus-device PART` | Quartus device (default `5CSEBA6U23I7`) |
| `--vivado-part PART` | Vivado part (default `xc7z020clg484-1`) |
| `--indent-style spaces\|tab`, `--indent-size N` | Indentation of generated HDL / TCL / XDC / SDC (also works with the classic generator) |
| `--framework cocotb\|vunit`, `--engine-sim ghdl\|icarus\|verilator\|questa` | Testbench framework / simulator (the `simulation:` block of the `.ip.yml` wins) |
| `--docs` | Also write the Markdown datasheet `docs/<name>_datasheet.md` |
| `--out DIR` | Output directory (alias of `--output`/`-o`) |
| `--no-testbench`, `--dry-run`, `--json` | As for the classic generator |

```bash
ipcraft generate my_core.ip.yml --lang systemverilog --pack builtin-ipcraft \
        --target quartus,vivado --out gen/
ipcraft verify   my_core.ip.yml gen/ --lang systemverilog --pack builtin-ipcraft --target quartus,vivado
```

`verify` regenerates in memory and exits `1` when `gen/` has stale, missing or orphaned files (files declared
`managed: false` are exempt). Pass the same flags that produced the directory.

Files that the `.ip.yml` lists with `managed: false` — and files a pack marks `managed: false` — are written only
when they do not exist yet.

### Scaffold packs

```bash
ipcraft pack list                         # built-in packs (add --pack-dir DIR for your own)
ipcraft pack export builtin-ipcraft my-pack/   # copy a built-in pack + the templates it uses for editing
ipcraft generate core.ip.yml --pack my-pack/ --lang vhdl
ipcraft preview-template my-pack/top.vhdl.j2 core.ip.yml   # render one template against a core's context
```

Pack manifests (`scaffold.yml`), the template context contract (v1.4.0) and the Nunjucks-flavoured template syntax are
identical to the extension's; see the extension documentation on scaffold packs. Templates run on Jinja2 with
Nunjucks semantics (empty lists are truthy, `null` renders as nothing, `array.push(x)`, `~` concatenates like JavaScript).

---

## `import` -- HDL, `_hw.tcl` and `component.xml` to IP YAML

```bash
ipcraft import path/to/core.vhd            # VHDL entity -> core.ip.yml (bus interfaces detected from port names)
ipcraft import path/to/core.sv             # Verilog / SystemVerilog module
ipcraft import path/to/core_hw.tcl         # Platform Designer component (conditionals, loops, procs and sourced files are resolved)
ipcraft import path/to/xilinx/component.xml  # Vivado IP-XACT: .ip.yml and .mm.yml are written one level above xilinx/
```

Options: `--output/--out DIR`, `--vendor`, `--library`, `--version`, `--no-detect-bus`, `--dry-run`, `--force`, `--json`.
An existing file is never overwritten without `--force`; an import that violates a bus protocol is refused, while
warnings (values Tcl computes at elaboration time, unresolved widths, ...) are printed. Review the result before generating code.

`ipcraft parse` remains the classic Python importer.

## `instance` -- component instantiation snippet

```bash
ipcraft instance rtl/fifo.vhd     # u_fifo : entity work.fifo generic map (...) port map (...);
ipcraft instance rtl/fifo.sv      # fifo #(.DEPTH (DEPTH)) u_fifo (...);
```

## `migrate` -- upgrade and convert

`ipcraft migrate FILE...` upgrades `.ip.yml` files to the latest format version (`apiVersion: '1.1'`: bus interface
contracts, e.g. Avalon-MM `read_n` becomes `read` + `portPolarityOverrides`) and converts legacy snake_case keys in
`.ip.yml` / `.mm.yml` files, preserving comments and hex literals. `--check` only reports (exit 1 if anything would
change); `--vendor-targets` also rewrites the legacy `vendor:` field to `targets:`.
