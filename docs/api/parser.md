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
- Bus library loading (`useBusLibrary: path/to/bus_definitions.yml`)

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
source. This is the engine behind the `ipcraft parse` CLI command.
