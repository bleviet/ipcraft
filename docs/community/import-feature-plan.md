# Import Feature — Implementation Plan

**Author:** Community / FPGA User  
**Status:** Proposal  
**Target command:** `ipcraft import`

---

## 1. Problem Statement

Engineers working on production FPGA projects often have IP already described in
vendor-native formats:

| Scenario | Source file | Tool |
|----------|-------------|------|
| Single RTL entity | `uart_core.vhd` | Any editor / EDA |
| Intel Platform Designer IP | `uart_core_hw.tcl` | Quartus / Platform Designer |
| Xilinx Vivado IP | `component.xml` (IP-XACT) | Vivado IP Packager |

ipcraft can already _generate_ `_hw.tcl` and `component.xml` from a `.ip.yml`.
The reverse path — **importing** those formats and producing `.ip.yml` + optional
`.mm.yml` — does not yet exist.

This document is a detailed implementation plan for that reverse path.

---

## 2. User Stories

```
As an FPGA engineer migrating a legacy VHDL IP to ipcraft,
I want to run:
  ipcraft import uart_core.vhd
and get uart_core.ip.yml generated automatically,
so that I can start regenerating and managing the IP from a single source of truth.

As an Intel/Altera user who already has a Platform Designer _hw.tcl,
I want to run:
  ipcraft import uart_core_hw.tcl --mm
and get both uart_core.ip.yml and uart_core.mm.yml,
so that I don't have to re-describe a design I've already completed.

As a Xilinx/AMD Vivado user who has packaged an IP with the IP Packager,
I want to run:
  ipcraft import component.xml --mm
and get both .ip.yml and .mm.yml,
so that I can manage the IP with ipcraft going forward.
```

---

## 3. Scope

### In scope
- `ipcraft import <file>` — auto-detect format from extension / content
- Source formats: `.vhd`, `.v`, `_hw.tcl`, `component.xml`
- Output: `.ip.yml` (always) + `.mm.yml` (optional via `--mm` flag)
- VLNV metadata can be supplied on the command line to override discovered values
- `--json` flag for CI / scripting
- `--dry-run` flag to preview what would be written

### Out of scope (future iterations)
- SystemVerilog (`.sv`) parsing
- IP-XACT 2009 / 2014 full schema validation
- Register field semantic inference (e.g., field meaning from comments)
- Automatic testbench generation at import time

---

## 4. Architecture Overview

### 4.1 Existing pieces that will be reused

```
ipcraft/parser/
├── hdl/
│   ├── vhdl_parser.py      ← already parses entity/ports
│   ├── verilog_parser.py   ← already parses module/ports
│   └── bus_detector.py     ← already classifies ports into bus interfaces
└── yaml/
    └── ip_yaml_parser.py   ← parses .ip.yml → IpCore (reused internally)

ipcraft/generator/yaml/
└── ip_yaml_generator.py    ← IpCore → .ip.yml YAML text (already works)
```

`ipcraft parse <vhd>` already covers the VHDL → `.ip.yml` path.
The new `ipcraft import` command will supersede and extend it.

### 4.2 New pieces to build

```
ipcraft/parser/vendor/           ← NEW package
├── __init__.py
├── hw_tcl_parser.py             ← Intel _hw.tcl → IpCore
├── ipxact_parser.py             ← Xilinx component.xml (IP-XACT) → IpCore
└── import_dispatcher.py         ← auto-detect format, dispatch to parser

ipcraft/generator/yaml/
└── mm_yaml_generator.py         ← IpCore + discovered regs → .mm.yml YAML text (NEW)
```

### 4.3 Data-flow diagram

```
 ┌──────────────────────────────────────────────────────────────────────┐
 │  User runs: ipcraft import <file> [--mm] [--vendor v] [--output dir] │
 └──────────────────────────────────────────────────────────────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │  ImportDispatcher        │
                    │  detect_format(file)     │
                    └────────────┬────────────┘
              ┌──────────────────┼──────────────────────┐
              │                  │                       │
       .vhd / .v          _hw.tcl                component.xml
              │                  │                       │
    ┌─────────▼──────┐  ┌────────▼──────┐   ┌──────────▼──────┐
    │ VHDLParser /   │  │ HwTclParser   │   │ IpXactParser    │
    │ VerilogParser  │  │ (new)         │   │ (new)           │
    │ + BusDetector  │  │               │   │                 │
    └─────────┬──────┘  └────────┬──────┘   └──────────┬──────┘
              └──────────────────┴──────────────────────┘
                                 │
                          IpCore  model
                                 │
                    ┌────────────▼────────────┐
                    │  IpYamlGenerator        │
                    │  (already exists)        │
                    └────────────┬────────────┘
                                 │ writes
                        <name>.ip.yml
                                 │
                    (if --mm flag)
                    ┌────────────▼────────────┐
                    │  MmYamlGenerator (new)   │
                    │  scaffold from bus type  │
                    └────────────┬────────────┘
                                 │ writes
                        <name>.mm.yml
```

---

## 5. CLI Interface

### 5.1 Command signature

```
ipcraft import <input>
              [--output <dir>]          # default: same directory as input file
              [--mm]                    # also generate .mm.yml skeleton
              [--vendor <v>]            # override discovered vendor
              [--library <lib>]         # override discovered library
              [--version <ver>]         # override discovered version
              [--no-detect-bus]         # skip bus-interface detection
              [--force]                 # overwrite existing files
              [--dry-run]               # print what would be written, write nothing
              [--json]                  # output machine-readable JSON to stdout
              [--debug]                 # show full traceback on errors
              [-v / --verbose]          # verbose per-step output
```

### 5.2 Example sessions

```bash
# From a single VHDL entity
$ ipcraft import my_uart.vhd
✓ Detected format: VHDL
✓ Detected bus:    none (standalone)
✓ Written: my_uart.ip.yml

# Intel Platform Designer
$ ipcraft import my_uart_hw.tcl --mm --vendor acme.com
✓ Detected format: Intel Platform Designer (_hw.tcl)
✓ Detected bus:    Avalon-MM (slave)
✓ Written: my_uart.ip.yml
✓ Written: my_uart.mm.yml

# Xilinx IP-XACT
$ ipcraft import component.xml --mm --output ./imported/
✓ Detected format: Xilinx Vivado (IP-XACT component.xml)
✓ Detected bus:    AXI4-Lite (slave)
✓ Written: imported/my_uart.ip.yml
✓ Written: imported/my_uart.mm.yml

# Dry-run preview
$ ipcraft import component.xml --mm --dry-run
Would write: component_name.ip.yml  (new)
Would write: component_name.mm.yml  (new)

# JSON output for CI
$ ipcraft import component.xml --mm --json
{"success": true, "files": ["my_uart.ip.yml", "my_uart.mm.yml"], "format": "ipxact", "bus": "axil"}
```

---

## 6. Format-by-Format Implementation

### 6.1 VHDL / Verilog (`.vhd`, `.v`)

**Status:** 90% already exists via `ipcraft parse`.

**What already works:**
- `VHDLParser` → extracts entity name, ports (name, direction, type, width)
- `BusInterfaceDetector` → classifies ports into AXI4-Lite / Avalon-MM / etc.
- `IpYamlGenerator` → produces `.ip.yml` YAML text

**Gap to fill:**
- `ipcraft parse` is a separate command; `ipcraft import` will unify it with
  `_hw.tcl` and `component.xml` under one entry point
- Add `--mm` flag path to generate `.mm.yml` skeleton for discovered bus type
- The existing `ipcraft parse` command should be kept as an alias pointing to
  `ipcraft import` to preserve backward compatibility

**Implementation notes:**
- Reuse `VHDLParser`, `VerilogParser`, `BusInterfaceDetector` as-is
- Only new logic: route through `ImportDispatcher` and add `MmYamlGenerator`

---

### 6.2 Intel Platform Designer — `_hw.tcl`

**Status:** Not yet implemented.

#### 6.2.1 What `_hw.tcl` contains

A Platform Designer TCL file is structured as a sequence of `set_module_info`,
`add_interface`, `add_interface_port`, `set_parameter_property`, and similar
Tcl procedure calls. Key structure (simplified):

```tcl
# Module metadata
set_module_info -name          "my_uart"
set_module_info -version       "1.0"
set_module_info -display_name  "My UART Core"

# Bus interface declaration
add_interface s0 avalon end
set_interface_property s0 associatedClock clk
set_interface_property s0 associatedReset reset

# Bus interface ports
add_interface_port s0 avs_s0_address    address    Input  4
add_interface_port s0 avs_s0_write      write      Input  1
add_interface_port s0 avs_s0_writedata  writedata  Input  32
add_interface_port s0 avs_s0_read       read       Input  1
add_interface_port s0 avs_s0_readdata   readdata   Output 32

# Clock and reset interfaces
add_interface clk clock end
add_interface_port clk clk clk Input 1

add_interface reset reset end
add_interface_port reset reset reset Input 1

# Non-bus ports
add_interface_port "" txd "" Output 1
add_interface_port "" rxd "" Input  1

# Parameters / generics
add_parameter DATA_WIDTH INTEGER 8
set_parameter_property DATA_WIDTH DISPLAY_NAME "Data Width"

# Registers (from set_module_info elaboration callback or embedded comments)
# (not always present)
```

#### 6.2.2 Parser implementation plan

**File:** `ipcraft/parser/vendor/hw_tcl_parser.py`

The parser uses Python's built-in `re` module and a line-by-line state machine
(no Tcl interpreter required — we only need to read data, not execute Tcl).

```python
class HwTclParser:
    """Parse an Intel Platform Designer _hw.tcl file into an IpCore."""

    def parse_file(self, path: Path) -> IpCore: ...
    def parse_string(self, content: str) -> IpCore: ...

    # Internal extraction methods:
    def _extract_module_info(self, lines) -> dict: ...
    def _extract_interfaces(self, lines) -> List[dict]: ...
    def _extract_interface_ports(self, lines) -> List[dict]: ...
    def _extract_parameters(self, lines) -> List[dict]: ...
    def _map_to_ipcore(self, raw: dict) -> IpCore: ...
```

**Regex patterns needed:**

```python
# Module metadata
RE_MODULE_INFO = re.compile(
    r'set_module_info\s+-(\w+)\s+"([^"]+)"'
)

# Interface declarations
# add_interface <name> <type> <direction>
RE_ADD_INTERFACE = re.compile(
    r'add_interface\s+(\S+)\s+(\S+)\s+(\S+)'
)

# Interface properties
# set_interface_property <ifname> associatedClock <clk>
RE_IF_PROPERTY = re.compile(
    r'set_interface_property\s+(\S+)\s+(\S+)\s+(\S+)'
)

# Interface ports
# add_interface_port <ifname> <port> <logical> <dir> <width>
RE_ADD_IF_PORT = re.compile(
    r'add_interface_port\s+(\S+)\s+(\S+)\s+(\S+)\s+(Input|Output|Bidir)\s+(\d+)',
    re.IGNORECASE
)

# Parameters
# add_parameter <name> <type> <default>
RE_ADD_PARAM = re.compile(
    r'add_parameter\s+(\S+)\s+(\S+)\s+(\S+)'
)
```

**Bus type mapping (`_hw.tcl` → ipcraft canonical):**

| `_hw.tcl` interface type | ipcraft bus key |
|--------------------------|-----------------|
| `avalon`                 | `AVALON_MM`     |
| `avalon_streaming`       | `AVALON_ST`     |
| `axi4lite`               | `AXI4_LITE`     |
| `axi4`                   | `AXI4_FULL`     |
| `axi4stream`             | `AXI_STREAM`    |
| `clock`                  | clock (not bus) |
| `reset`                  | reset (not bus) |
| `conduit`                | plain port      |

**Interface direction mapping:**

| `_hw.tcl` direction | ipcraft mode |
|---------------------|--------------|
| `end` / `slave`     | `slave`      |
| `start` / `master`  | `master`     |

#### 6.2.3 Known challenges

1. **Register map not always in `_hw.tcl`** — Register definitions may live in a
   separate `<name>_regs.tcl` or in HDL comments. If found, map to `.mm.yml`; if
   not, generate an empty skeleton.
2. **Elaboration callbacks** — Some `_hw.tcl` files compute parameters via
   `set_module_info -elaborate` Tcl callbacks. These contain executable Tcl and
   cannot be parsed without a Tcl interpreter. Skip and log a warning.
3. **Custom interface types** — Proprietary interface types (e.g., `conduit_end`)
   should be treated as plain ports.

---

### 6.3 Xilinx Vivado — `component.xml` (IP-XACT)

**Status:** Not yet implemented.

#### 6.3.1 What `component.xml` contains

Vivado's IP Packager writes IP-XACT 2009 XML. Relevant structure (simplified):

```xml
<spirit:component xmlns:spirit="http://www.spiritconsortium.org/XMLSchema/SPIRIT/1685-2009-06">

  <!-- VLNV -->
  <spirit:vendor>xilinx.com</spirit:vendor>
  <spirit:library>user</spirit:library>
  <spirit:name>my_uart</spirit:name>
  <spirit:version>1.0</spirit:version>
  <spirit:description>My UART core</spirit:description>

  <!-- Bus interfaces -->
  <spirit:busInterfaces>
    <spirit:busInterface>
      <spirit:name>S_AXI</spirit:name>
      <spirit:busType spirit:vendor="xilinx.com" spirit:library="interface"
                      spirit:name="aximm" spirit:version="1.0"/>
      <spirit:slave/>
      <spirit:portMaps>
        <spirit:portMap>
          <spirit:logicalPort><spirit:name>AWADDR</spirit:name></spirit:logicalPort>
          <spirit:physicalPort><spirit:name>s_axi_awaddr</spirit:name></spirit:physicalPort>
        </spirit:portMap>
        <!-- ... more port maps -->
      </spirit:portMaps>
    </spirit:busInterface>
  </spirit:busInterfaces>

  <!-- Physical ports -->
  <spirit:model>
    <spirit:ports>
      <spirit:port>
        <spirit:name>s_axi_awaddr</spirit:name>
        <spirit:wire>
          <spirit:direction>in</spirit:direction>
          <spirit:vector>
            <spirit:left>11</spirit:left>
            <spirit:right>0</spirit:right>
          </spirit:vector>
        </spirit:wire>
      </spirit:port>
    </spirit:ports>
  </spirit:model>

  <!-- Parameters / generics -->
  <spirit:parameters>
    <spirit:parameter>
      <spirit:name>C_S_AXI_DATA_WIDTH</spirit:name>
      <spirit:value>32</spirit:value>
    </spirit:parameter>
  </spirit:parameters>

  <!-- Memory maps (register definitions) -->
  <spirit:memoryMaps>
    <spirit:memoryMap>
      <spirit:name>S_AXI_reg</spirit:name>
      <spirit:addressBlock>
        <spirit:name>reg0</spirit:name>
        <spirit:baseAddress>0</spirit:baseAddress>
        <spirit:range>65536</spirit:range>
        <spirit:width>32</spirit:width>
        <spirit:register>
          <spirit:name>slv_reg0</spirit:name>
          <spirit:addressOffset>0x0</spirit:addressOffset>
          <spirit:size>32</spirit:size>
          <spirit:field>
            <spirit:name>CTRL_BIT</spirit:name>
            <spirit:bitOffset>0</spirit:bitOffset>
            <spirit:bitWidth>1</spirit:bitWidth>
            <spirit:access>read-write</spirit:access>
          </spirit:field>
        </spirit:register>
      </spirit:addressBlock>
    </spirit:memoryMap>
  </spirit:memoryMaps>

</spirit:component>
```

#### 6.3.2 Parser implementation plan

**File:** `ipcraft/parser/vendor/ipxact_parser.py`

Use Python's standard library `xml.etree.ElementTree` — no additional dependency.
Support both IP-XACT 2009 (`spirit:`) and 2014 (`ipxact:`) namespace prefixes.

```python
# Supported IP-XACT namespace prefixes
_NS_MAP = {
    "spirit": "http://www.spiritconsortium.org/XMLSchema/SPIRIT/1685-2009-06",
    "ipxact":  "http://www.accellera.org/XMLSchema/IPXACT/1685-2014",
}

class IpXactParser:
    """Parse a Xilinx Vivado component.xml (IP-XACT) file into an IpCore."""

    def parse_file(self, path: Path) -> IpCore: ...
    def parse_string(self, content: str) -> IpCore: ...

    # Internal extraction methods:
    def _detect_namespace(self, root) -> str: ...    # 'spirit' or 'ipxact'
    def _extract_vlnv(self, root, ns) -> VLNV: ...
    def _extract_ports(self, root, ns) -> List[Port]: ...
    def _extract_bus_interfaces(self, root, ns) -> List[BusInterface]: ...
    def _extract_memory_maps(self, root, ns) -> List[MemoryMap]: ...
    def _extract_parameters(self, root, ns) -> List[Parameter]: ...
    def _map_bus_type(self, spirit_name: str, spirit_vendor: str) -> str: ...
```

**Bus type mapping (IP-XACT → ipcraft canonical):**

| `spirit:busType name` | `spirit:vendor`  | ipcraft bus key |
|-----------------------|------------------|-----------------|
| `aximm`               | `xilinx.com`     | `AXI4_LITE`*    |
| `axis`                | `xilinx.com`     | `AXI_STREAM`    |
| `AXI4`                | `xilinx.com`     | `AXI4_FULL`     |
| `AXI4Lite`            | `xilinx.com`     | `AXI4_LITE`     |
| `AXI4Stream`          | `xilinx.com`     | `AXI_STREAM`    |
| `AXI4_Lite`           | `arm.com`        | `AXI4_LITE`     |

\* Width of `AWADDR`/`ARADDR` determines AXI4-Full vs AXI4-Lite heuristic.

**Port width extraction:**

```python
# IP-XACT encodes vector ports as [left downto right]
# width = abs(left - right) + 1
left  = int(port.find(f"{ns}:vector/{ns}:left").text)
right = int(port.find(f"{ns}:vector/{ns}:left").text)
width = abs(left - right) + 1
```

**Memory map → `.mm.yml` mapping:**

| IP-XACT element | `.mm.yml` field |
|-----------------|-----------------|
| `memoryMap/name` | address block container name |
| `addressBlock/baseAddress` | `baseAddress` |
| `register/name` | register `name` |
| `register/addressOffset` | computed address |
| `register/size` | register width |
| `register/field/name` | field `name` |
| `register/field/bitOffset` + `bitWidth` | `bits: '[msb:lsb]'` |
| `register/field/access` | `access` (read-write / read-only / write-only) |
| `register/field/description` | `description` |

This is the most complete mapping — IP-XACT `component.xml` from Vivado often
contains a full register map, which translates directly to `.mm.yml`.

#### 6.3.3 Known challenges

1. **`aximm` can be AXI4-Full or AXI4-Lite** — Distinguish using the address
   width parameter `C_S_AXI_ADDR_WIDTH`: ≤ 16 → AXI4-Lite, > 16 → AXI4-Full.
   Also check `spirit:busType name` for `AXI4Lite` vs `AXI4`.
2. **Namespace variance** — Some Vivado versions emit `spirit:`, others `ipxact:`.
   Detect by inspecting the root element's namespace attribute.
3. **`portMaps` linkage** — Logical port names in `portMaps` map to physical
   port names in `model/ports`. The parser must resolve these cross-references.
4. **Vendor IP annotations** — Some fields (e.g., Xilinx XGUI parameters)
   live under custom `xilinx:` namespace extensions. Skip gracefully.

---

## 7. New Module: `MmYamlGenerator`

When `--mm` is requested but no register information was discovered (e.g.,
importing from a VHDL file or a `_hw.tcl` without register elaboration),
a skeleton `.mm.yml` must be generated from the bus type alone.

**File:** `ipcraft/generator/yaml/mm_yaml_generator.py`

```python
class MmYamlGenerator:
    """Generate a .mm.yml skeleton from an IpCore and/or parsed register data."""

    def generate(
        self,
        ip_core: IpCore,
        discovered_regs: Optional[List[dict]] = None,
    ) -> str:
        """
        If discovered_regs is provided (from IP-XACT), produce a populated .mm.yml.
        Otherwise, produce a skeleton with placeholder CTRL / STATUS registers
        appropriate for the detected bus type.
        """
```

**Skeleton output (no registers discovered):**

```yaml
# Register map for <name>
# Generated by ipcraft import — populate with your register definitions
- name: CSR_MAP
  description: Control/Status Register Map
  addressBlocks:
  - name: REGS
    baseAddress: 0
    usage: register
    defaultRegWidth: 32
    registers:
    - name: CTRL
      description: "TODO: Control register"
      addressOffset: 0x0
      fields:
      - name: ENABLE
        bits: '[0:0]'
        access: read-write
        description: Global enable (placeholder)
    - name: STATUS
      description: "TODO: Status register"
      addressOffset: 0x4
      fields:
      - name: READY
        bits: '[0:0]'
        access: read-only
        description: Ready flag (placeholder)
```

---

## 8. New Module: `ImportDispatcher`

**File:** `ipcraft/parser/vendor/import_dispatcher.py`

```python
class ImportDispatcher:
    """Detect input format and dispatch to the appropriate parser."""

    def detect_format(self, path: Path) -> str:
        """
        Returns one of: 'vhdl', 'verilog', 'hw_tcl', 'ipxact'
        Detection order:
          1. File extension: .vhd / .vhdl → vhdl, .v → verilog
          2. Filename pattern: *_hw.tcl → hw_tcl
          3. XML root element inspection: <spirit:component> → ipxact
          4. Raise ImportFormatError if unrecognised
        """

    def parse(self, path: Path, **kwargs) -> IpCore:
        """Detect format and return parsed IpCore."""
        fmt = self.detect_format(path)
        if fmt == 'vhdl':
            return self._parse_vhdl(path, **kwargs)
        elif fmt == 'verilog':
            return self._parse_verilog(path, **kwargs)
        elif fmt == 'hw_tcl':
            return HwTclParser().parse_file(path)
        elif fmt == 'ipxact':
            return IpXactParser().parse_file(path)
```

---

## 9. CLI Integration

### 9.1 New subcommand `ipcraft import`

Add `cmd_import` function to `ipcraft/cli.py`:

```python
def cmd_import(args):
    """Import an existing IP description and generate .ip.yml."""
    dispatcher = ImportDispatcher()
    
    # Detect and parse
    fmt = dispatcher.detect_format(Path(args.input))
    log(f"Detected format: {fmt}", args)
    
    ip_core = dispatcher.parse(
        Path(args.input),
        detect_bus=not args.no_detect_bus,
    )
    
    # Apply CLI overrides to VLNV
    if args.vendor:  ip_core.vlnv.vendor  = args.vendor
    if args.library: ip_core.vlnv.library = args.library
    if args.version: ip_core.vlnv.version = args.version
    
    output_base = Path(args.output) if args.output else Path(args.input).parent
    ip_out = output_base / f"{ip_core.vlnv.name.lower()}.ip.yml"
    mm_out = output_base / f"{ip_core.vlnv.name.lower()}.mm.yml"
    
    # Dry-run
    if args.dry_run:
        _import_dry_run_report(ip_out, mm_out, args.mm, ip_core)
        return
    
    # Write .ip.yml
    ip_yaml = IpYamlGenerator().generate_from_model(ip_core)
    _safe_write(ip_out, ip_yaml, args.force, args)
    
    # Write .mm.yml if requested
    if args.mm:
        discovered = getattr(ip_core, '_discovered_registers', None)
        mm_yaml = MmYamlGenerator().generate(ip_core, discovered_regs=discovered)
        _safe_write(mm_out, mm_yaml, args.force, args)
    
    # Output
    if args.json:
        files = [str(ip_out)] + ([str(mm_out)] if args.mm else [])
        print(json.dumps({"success": True, "format": fmt, "files": files}))
    else:
        print(f"✓ Written: {ip_out}")
        if args.mm:
            print(f"✓ Written: {mm_out}")
```

### 9.2 `ipcraft parse` backward compatibility

The existing `ipcraft parse` subcommand should remain unchanged. Internally it
can delegate to `ImportDispatcher` for `.vhd` files, or simply continue using
`IpYamlGenerator` directly — both paths produce the same result.

---

## 10. Implementation Phases

### Phase 1 — Foundation & VHDL unification  
_Estimated scope: small (mostly wiring existing code)_

- [ ] Create `ipcraft/parser/vendor/__init__.py`
- [ ] Create `ImportDispatcher` with VHDL / Verilog dispatch only
- [ ] Create `MmYamlGenerator` (skeleton output only — no discovered regs yet)
- [ ] Add `cmd_import` to `cli.py` with VHDL / Verilog support
- [ ] Add `ipcraft import` to argparse with all flags
- [ ] Tests: import `.vhd` file, verify `.ip.yml` matches `ipcraft parse` output
- [ ] Tests: import `.vhd` with `--mm`, verify skeleton `.mm.yml` is valid

### Phase 2 — Intel `_hw.tcl` parser  
_Estimated scope: medium_

- [ ] Create `HwTclParser` with regex-based extraction
- [ ] Map Tcl interface types → ipcraft bus keys
- [ ] Map Tcl port directions → ipcraft `PortDirection`
- [ ] Handle `clock` / `reset` interfaces → `Clock` / `Reset` model objects
- [ ] Handle `conduit` ports → plain `Port` objects
- [ ] Wire into `ImportDispatcher`
- [ ] Tests: parse a real `_hw.tcl` from `ipcraft-spec/examples/` or a synthetic fixture
- [ ] Tests: import with `--mm`, verify skeleton .mm.yml

### Phase 3 — Xilinx `component.xml` (IP-XACT) parser  
_Estimated scope: medium-large_

- [ ] Create `IpXactParser` using `xml.etree.ElementTree`
- [ ] Detect and handle `spirit:` vs `ipxact:` namespaces
- [ ] Implement VLNV extraction
- [ ] Implement port model extraction (including vector width calculation)
- [ ] Implement bus interface extraction + `portMaps` resolution
- [ ] Implement memory map extraction → `MemoryMap` + `Register` + `Field` objects
- [ ] Wire into `ImportDispatcher`
- [ ] Wire discovered registers into `MmYamlGenerator.generate()`
- [ ] Tests: round-trip — generate `component.xml` from a known `.ip.yml`, then
      import it back, verify the resulting `.ip.yml` matches the original
- [ ] Tests: import a `component.xml` with registers, verify `.mm.yml` content

### Phase 4 — Polish & integration tests  
_Estimated scope: small_

- [ ] `--dry-run` output (list of files that would be written)
- [ ] `--json` output format documented and tested
- [ ] End-to-end test: `ipcraft import component.xml --mm && ipcraft generate *.ip.yml`
- [ ] Update `docs/user-guide/cli.md` with `import` command documentation
- [ ] Update `README.md` workflow diagram to include import path

---

## 11. Dependencies

| Library | Purpose | Already a dependency? |
|---------|---------|----------------------|
| `pyparsing` | VHDL / Verilog entity parsing | ✅ Yes |
| `pyyaml` | YAML generation | ✅ Yes |
| `xml.etree.ElementTree` | IP-XACT XML parsing | ✅ stdlib |
| `re` | `_hw.tcl` regex extraction | ✅ stdlib |

**No new runtime dependencies are required.**

---

## 12. Test Strategy

### Unit tests
Each parser should have a dedicated test file:
- `tests/test_hw_tcl_parser.py` — fixture `_hw.tcl` files in `tests/fixtures/`
- `tests/test_ipxact_parser.py` — fixture `component.xml` files in `tests/fixtures/`
- `tests/test_import_dispatcher.py` — format detection, dispatch routing

### Round-trip integration tests
The most valuable tests confirm that the import → generate cycle produces
consistent output:
```
.ip.yml  →  generate_xilinx()  →  component.xml
                                        ↓
                               IpXactParser.parse_file()
                                        ↓
                               IpYamlGenerator.generate()
                                        ↓
               result.ip.yml  ≈  original .ip.yml  (structural equivalence)
```

### Fixtures
Store sample vendor files in `tests/fixtures/vendor/`:
```
tests/fixtures/vendor/
├── simple_uart_hw.tcl
├── simple_uart_component.xml
├── axilite_slave_hw.tcl
└── axilite_slave_component.xml
```

---

## 13. Open Questions

1. **`_hw.tcl` with register elaboration callbacks** — If a `_hw.tcl` includes
   Tcl procedures that compute parameters, should we skip with a warning, or
   consider optionally invoking `tclsh` if available on PATH?

2. **IP-XACT strict mode** — Should the importer validate against the full
   IP-XACT XSD schema, or parse leniently (best-effort)? Recommendation: lenient
   by default, add `--strict` flag later.

3. **Clock domain crossing** — `_hw.tcl` and `component.xml` can declare multiple
   clock domains. The current `IpCore` model supports multiple clocks. Ensure the
   mapping preserves this.

4. **`ipcraft parse` deprecation timeline** — Once `ipcraft import` exists and
   covers `.vhd` files, should `ipcraft parse` be deprecated? Recommendation:
   keep it as an alias for at least two minor versions.

---

## 14. Acceptance Criteria

The feature is complete when all of the following are true:

1. `ipcraft import my_uart.vhd` produces the same output as `ipcraft parse my_uart.vhd`
2. `ipcraft import my_uart_hw.tcl` produces a valid `.ip.yml` with correct bus
   interface, clocks, and ports
3. `ipcraft import component.xml --mm` produces both `.ip.yml` and a `.mm.yml`
   populated with registers discovered from the IP-XACT file
4. A Vivado-generated `component.xml` can be round-tripped: import → generate →
   the resulting `component.xml` is structurally equivalent to the original
5. All four import paths are covered by automated tests
6. `ipcraft import --help` describes all flags
7. `--json` and `--dry-run` flags work for all formats
