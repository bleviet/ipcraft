# Generator API

## Module: `ipcraft.generator`

---

## `IpCoreProjectGenerator`

The main generator for producing VHDL, vendor files, and testbenches from an
`IpCore` model.

```python
from ipcraft.generator.hdl import IpCoreProjectGenerator

gen = IpCoreProjectGenerator()
```

### `generate_all(ip_core, bus_type, ...) -> Dict[str, str]`

Generates all output files and returns a dictionary mapping filenames to
content.

```python
files = gen.generate_all(
    ip_core,
    bus_type="axil",           # "axil" or "avmm"
    include_regs=True,         # generate standalone register bank
    structured=True,           # use rtl/tb/intel/xilinx folder layout
    vendor="both",             # "none", "intel", "xilinx", "both"
    include_testbench=True,    # generate cocotb testbench
)

# files: {"rtl/core_pkg.vhd": "...", "rtl/core.vhd": "...", ...}
```

### `write_files(ip_core, output_dir, bus_type)`

Generates and writes all files to disk.

```python
gen.write_files(ip_core, output_dir="./build", bus_type="axil")
```

### Individual Generation Methods

```python
# VHDL components
pkg_content = gen.generate_package(ip_core, bus_type)
top_content = gen.generate_top(ip_core, bus_type)
core_content = gen.generate_core(ip_core, bus_type)
bus_content = gen.generate_bus_wrapper(ip_core, bus_type)
regs_content = gen.generate_register_file(ip_core, bus_type)
```

### Supported Bus Types

| Code | Protocol |
|------|----------|
| `"axil"` | AXI4-Lite |
| `"avmm"` | Avalon Memory-Mapped |

---

## Vendor Generation Mixin

Included in `IpCoreProjectGenerator` via `VendorGenerationMixin`.

```python
# Intel Platform Designer
tcl = gen.generate_intel_hw_tcl(ip_core, bus_type)

# Xilinx IP-XACT
xml = gen.generate_xilinx_component_xml(ip_core)
tcl = gen.generate_xilinx_xgui(ip_core)

# Both vendors
vendor_files = gen.generate_vendor_files(ip_core, vendor="both", bus_type="axil")
# {"intel/core_hw.tcl": "...", "xilinx/component.xml": "...", ...}
```

---

## Testbench Generation Mixin

Included in `IpCoreProjectGenerator` via `TestbenchGenerationMixin`.

```python
# Cocotb test file
test_py = gen.generate_cocotb_test(ip_core, bus_type)

# Simulation Makefile
makefile = gen.generate_cocotb_makefile(ip_core, bus_type)

# Memory map YAML for Python driver
mm_yaml = gen.generate_memmap_yaml(ip_core)

# All testbench files
tb_files = gen.generate_testbench(ip_core, bus_type)
# {"tb/core_test.py": "...", "tb/Makefile": "..."}
```

---

## Template System

Generators use Jinja2 templates stored in `ipcraft/generator/hdl/templates/`.
The `BaseGenerator` abstract class sets up the Jinja2 environment relative
to the concrete generator's module path.

### Template Context

The generator builds a context dictionary from the `IpCore` model containing:

- Register definitions with expanded fields
- Port lists (user ports, bus ports)
- Generic/parameter definitions
- Bus interface details with direction-flipped ports for slave mode
- VHDL type information (parameterized widths supported)

---

## Backward Compatibility

Deprecated aliases are available with deprecation warnings:

```python
# Deprecated - use IpCoreProjectGenerator instead
from ipcraft.generator.hdl import VHDLGenerator

# Deprecated function
from ipcraft.generator.hdl import generate_vhdl
```
