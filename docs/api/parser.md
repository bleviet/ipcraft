# Parser API

## Module: `ipcraft.parser`

```python
from ipcraft.parser import YamlIpCoreParser, ParseError
```

---

## `YamlIpCoreParser`

The main parser for loading IP core YAML files into the canonical `IpCore`
model.

```python
from ipcraft.parser import YamlIpCoreParser

parser = YamlIpCoreParser()
ip_core = parser.parse_file("my_core.ip.yml")
```

### `parse_file(file_path: str) -> IpCore`

Loads and parses a `*.ip.yml` file. Resolves:

- Memory map imports (`memoryMaps: {import: file.mm.yml}`)
- FileSet imports (`fileSets: [{import: file.fileset.yml}]`)

Raises `ParseError` on invalid input with file path and line context.

### Parser Mixins

`YamlIpCoreParser` is composed from mixins:

- **`MemoryMapParserMixin`** -- Handles `*.mm.yml` parsing: address blocks,
  registers, bit fields, register arrays, multi-document YAML with templates.
- **`FileSetParserMixin`** -- Handles `*.fileset.yml` parsing and imports.

The mixin architecture keeps memory map and fileset parsing logic separate and
testable.

---

## `ParseError`

```python
from ipcraft.parser import ParseError

try:
    ip_core = parser.parse_file("bad.ip.yml")
except ParseError as e:
    print(e.message)
    print(e.file_path)
    print(e.line)
```

---

## `ParseDispatcher`

Auto-detects the source file format and dispatches to the appropriate parser.
This is the engine behind the multi-format `ipcraft parse` CLI command.

```python
from ipcraft.parser.vendor.parse_dispatcher import ParseDispatcher, ParseFormatError

dispatcher = ParseDispatcher()

# Detect format without parsing
fmt = dispatcher.detect_format(Path("my_core.vhd"))   # "vhdl"
fmt = dispatcher.detect_format(Path("my_core.v"))      # "verilog"
fmt = dispatcher.detect_format(Path("core_hw.tcl"))   # "hw_tcl"
fmt = dispatcher.detect_format(Path("component.xml")) # "ipxact"

# Detect and parse in one step
ip_core = dispatcher.parse(Path("my_core.vhd"), detect_bus=True)
```

### Supported Formats

| Format string | Triggered by | Parser used |
|---------------|-------------|-------------|
| `"vhdl"` | `.vhd`, `.vhdl` | `VHDLParser` + `BusInterfaceDetector` |
| `"verilog"` | `.v`, `.sv` | `VerilogParser` + `BusInterfaceDetector` |
| `"hw_tcl"` | `*_hw.tcl`, `*.tcl` | `HwTclParser` |
| `"ipxact"` | `component.xml` (XML root `<component>`) | `IpXactParser` |

Raises `ParseFormatError` if the format cannot be determined.

---

## VHDL Parser

```python
from ipcraft.parser.hdl.vhdl_parser import VHDLParser

parser = VHDLParser()
result = parser.parse_file("entity.vhd")

# result structure:
# {
#     "entity": IpCore | None,
#     "architecture": {...} | None,
#     "package": {...} | None,
# }

# Parse from string
result = parser.parse_text(vhdl_source_code)
```

Uses pyparsing for grammar-based parsing with regex fallback when pyparsing
fails. Extracts:

- Entity ports -> `Port` objects
- Generics -> `Parameter` objects
- Architecture and package declarations

---

## Verilog Parser

```python
from ipcraft.parser.hdl.verilog_parser import VerilogParser

parser = VerilogParser()
result = parser.parse_file("module.v")

# result structure:
# {
#     "module": IpCore | None,
# }
```

Extracts module ports and parameters. Bus interface detection is applied by
`ParseDispatcher` (same `BusInterfaceDetector` as for VHDL).

---

## Bus Interface Detector

```python
from ipcraft.parser.hdl.bus_detector import BusInterfaceDetector

detector = BusInterfaceDetector()

# From parsed port list
bus_interfaces = detector.detect(ports)

# Classify clock and reset signals
clocks, resets = detector.classify_clocks_resets(ports)
```

### Detection Algorithm

1. Groups ports by common prefix (e.g., `s_axi_awaddr`, `s_axi_wdata`
   -> prefix `s_axi_`)
2. For each group, strips the prefix and matches suffixes against bus library
   port definitions
3. Requires >= 70% of required ports to match
4. Determines mode (master/slave/source/sink) from port directions

### Clock/Reset Classification

Identifies signals by name patterns:

- **Clocks:** `clk`, `i_clk`, `aclk`, `*_clk`
- **Resets:** `rst`, `rst_n`, `aresetn`, `i_rst_n` (polarity auto-detected
  from `_n` suffix)

---

## Intel `_hw.tcl` Parser

```python
from ipcraft.parser.vendor.hw_tcl_parser import HwTclParser

parser = HwTclParser()
ip_core = parser.parse_file(Path("my_core_hw.tcl"))
```

Imports an Intel Platform Designer component description (Tcl script) and
produces an `IpCore` model with:

- VLNV from `set_module_property DISPLAY_NAME` / `VERSION`
- Parameters from `add_parameter` declarations
- Bus interfaces from `add_interface` blocks

---

## Xilinx IP-XACT Parser

```python
from ipcraft.parser.vendor.ipxact_parser import IpXactParser

parser = IpXactParser()
ip_core = parser.parse_file(Path("component.xml"))
```

Imports a Xilinx `component.xml` (IP-XACT 2009/2014 format) and produces an
`IpCore` model with:

- VLNV from the `<spirit:vendor>` / `<ipxact:vendor>` hierarchy
- Parameters from `<spirit:parameter>` / `<ipxact:parameter>` elements
- Bus interfaces from `<spirit:busInterface>` elements

---

## YAML-to-IP Generator (Reverse Parser)

```python
from ipcraft.generator.yaml.ip_yaml_generator import IpYamlGenerator

gen = IpYamlGenerator()
yaml_content = gen.generate(
    vhdl_path="entity.vhd",
    vendor="mycompany",
    library="peripherals",
    version="1.0",
    memmap_path="entity.mm.yml",  # optional
)
```

Combines `VHDLParser` + `BusInterfaceDetector` to produce IP YAML from VHDL
source. This is the engine behind the legacy `ipcraft parse <file.vhd> -o
<file.yml>` path.

For the multi-format path, use `ParseDispatcher` + `IpYamlGenerator.generate_from_model()`:

```python
from ipcraft.parser.vendor.parse_dispatcher import ParseDispatcher
from ipcraft.generator.yaml.ip_yaml_generator import IpYamlGenerator

ip_core = ParseDispatcher().parse(Path("my_core_hw.tcl"))
yaml_str = IpYamlGenerator().generate_from_model(ip_core)
```
