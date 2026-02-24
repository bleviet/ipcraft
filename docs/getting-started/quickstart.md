# Quick Start

This guide walks through the two main workflows: generating VHDL from a YAML
specification, and parsing existing VHDL into a YAML specification.

## Workflow 1: YAML to VHDL

### 1. Define your IP core

Create `my_core.ip.yml`:

```yaml
apiVersion: '1.0'
vlnv:
  vendor: my-company.com
  library: peripherals
  name: my_core
  version: 1.0.0

description: A simple IP core with AXI-Lite registers

clocks:
  - name: i_clk
    direction: in
    frequency: 100MHz

resets:
  - name: i_rst_n
    direction: in
    polarity: activeLow

ports:
  - name: o_irq
    direction: out
    width: 1

busInterfaces:
  - name: S_AXI_LITE
    type: AXI4L
    mode: slave
    physicalPrefix: s_axi_
    associatedClock: i_clk
    associatedReset: i_rst_n
    memoryMapRef: CSR_MAP
    portWidthOverrides:
      AWADDR: 12
      ARADDR: 12

memoryMaps:
  import: my_core.mm.yml
```

### 2. Define the memory map

Create `my_core.mm.yml`:

```yaml
- name: CSR_MAP
  description: Control and status registers
  addressBlocks:
    - name: REGS
      baseAddress: 0
      range: 4096
      usage: register
      defaultRegWidth: 32
      registers:
        - name: CTRL
          fields:
            - name: ENABLE
              bits: "[0:0]"
              access: read-write
            - name: MODE
              bits: "[2:1]"
              access: read-write

        - name: STATUS
          access: read-only
          fields:
            - name: BUSY
              bits: "[0:0]"
```

### 3. Generate VHDL

```bash
ipcraft generate my_core.ip.yml --output ./build
```

Generated output:

```
build/
  rtl/
    my_core_pkg.vhd
    my_core.vhd
    my_core_core.vhd
    my_core_axil.vhd
    my_core_regs.vhd
  tb/
    my_core_test.py
    Makefile
  intel/
    my_core_hw.tcl
  xilinx/
    component.xml
    xgui/my_core_v1_0_0.tcl
```

## Workflow 2: VHDL to YAML

### 1. Parse an existing VHDL entity

```bash
ipcraft parse my_core.vhd
```

The parser automatically detects:

- **Bus interfaces** from port prefixes (`s_axi_*`, `m_axis_*`, `avs_*`)
- **Clocks** from name patterns (`clk`, `i_clk`, `aclk`)
- **Resets** from name patterns (`rst`, `rst_n`, `aresetn`) with polarity detection
- **Generics** extracted as parameters

### 2. Customize the output

```bash
ipcraft parse my_core.vhd \
  --vendor mycompany \
  --library peripherals \
  --version 2.0 \
  --memmap my_core.mm.yml
```

## Using the Python API

```python
from ipcraft.parser import YamlIpCoreParser
from ipcraft.generator.hdl import IpCoreProjectGenerator

# Parse YAML specification
parser = YamlIpCoreParser()
ip_core = parser.parse_file("my_core.ip.yml")

# Access model
print(ip_core.vlnv.name)           # "my_core"
print(ip_core.total_registers)     # number of registers
print(ip_core.slave_bus_interfaces) # list of slave bus interfaces

# Generate VHDL
generator = IpCoreProjectGenerator()
files = generator.generate_all(ip_core, bus_type="axil")
generator.write_files(ip_core, output_dir="./build", bus_type="axil")
```

## Using the Runtime Driver

```python
from ipcraft.driver import load_driver, CocotbBus

# In a cocotb testbench
bus = CocotbBus(dut, "s_axi", dut.clk)
driver = load_driver("my_core.mm.yml", bus)

# Read/write registers
val = await driver.REGS.CTRL.read()
await driver.REGS.CTRL.write_field("ENABLE", 1)
ready = await driver.REGS.STATUS.read_field("BUSY")
```

## Next Steps

- [CLI Reference](../user-guide/cli.md) -- All command options
- [IP YAML Specification](../user-guide/ip-yaml-spec.md) -- Full YAML format
- [Memory Maps](../user-guide/memory-maps.md) -- Register definitions
- [Architecture Overview](../architecture/overview.md) -- How it all fits together
