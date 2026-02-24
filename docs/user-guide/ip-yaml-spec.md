# IP YAML Specification

The IP YAML format is the single source of truth for an IP core definition in
IPCraft. This page covers the complete format reference.

## File Conventions

| Extension | Purpose |
|-----------|---------|
| `*.ip.yml` | IP Core definition (contains `apiVersion` + `vlnv`) |
| `*.mm.yml` | Memory Map definition (register/address blocks) |
| `*.fileset.yml` | File Set definition (importable file lists) |

---

## Top-Level Structure

```yaml
apiVersion: '1.0'            # Required
vlnv:                         # Required - unique identifier
  vendor: company.com
  library: peripherals
  name: my_core
  version: 1.0.0

description: Brief description of the IP core

useBusLibrary: path/to/bus_definitions.yml  # Optional

clocks: [...]
resets: [...]
ports: [...]
busInterfaces: [...]
memoryMaps: [...]             # Inline or import
parameters: [...]
fileSets: [...]               # Inline or import
```

---

## VLNV (Required)

Vendor-Library-Name-Version identifier. Every IP core must have one.

```yaml
vlnv:
  vendor: company.com       # Organization identifier
  library: peripherals      # IP category
  name: timer_core          # Core name (underscores preferred)
  version: 1.0.0            # Semantic version
```

All four fields are required and must be non-empty strings.

---

## Clocks

```yaml
clocks:
  - name: i_clk             # Physical HDL port name
    logicalName: CLK         # Logical name for bus associations
    direction: in
    frequency: 100MHz        # Optional, informational
    description: System clock
```

Referenced by `associatedClock` in bus interfaces using the physical `name`.

---

## Resets

```yaml
resets:
  - name: i_rst_n
    logicalName: RESET_N
    direction: in
    polarity: activeLow      # activeLow | activeHigh
    description: System reset
```

Referenced by `associatedReset` in bus interfaces using the physical `name`.

---

## Ports

Non-bus I/O ports:

```yaml
ports:
  - name: o_irq
    direction: out           # in | out | inout
    width: 1                 # Integer or parameter name (e.g., "NUM_LEDS")
    description: Interrupt output
```

The `width` field accepts integers or string references to parameters, enabling
parameterized vector widths in generated VHDL.

---

## Bus Interfaces

```yaml
busInterfaces:
  - name: S_AXI_LITE
    type: AXI4L              # Bus type key from bus library
    mode: slave              # slave | master | source | sink
    physicalPrefix: s_axi_   # HDL signal prefix
    associatedClock: i_clk   # References clock by name
    associatedReset: i_rst_n # References reset by name
    memoryMapRef: CSR_MAP    # Links to memory map (slave only)
    useOptionalPorts:        # Optional bus signals to include
      - AWPROT
      - ARPROT
    portWidthOverrides:      # Override default signal widths
      AWADDR: 12
      ARADDR: 12
```

### Bus Interface Arrays

For repeated interfaces (e.g., multi-channel streaming):

```yaml
busInterfaces:
  - name: M_AXIS_DATA
    type: AXIS
    mode: master
    array:
      count: 4
      indexStart: 0
      namingPattern: M_AXIS_CH{index}_DATA
      physicalPrefixPattern: m_axis_ch{index}_
```

Generates interfaces `M_AXIS_CH0_DATA` through `M_AXIS_CH3_DATA`, each with
its own prefixed port set.

---

## Parameters

```yaml
parameters:
  - name: DATA_WIDTH
    value: 32
    dataType: integer        # integer | natural | positive | real | boolean | string
    description: Data bus width
```

Parameters map to VHDL generics in generated code.

---

## Memory Maps

### Import from External File (Recommended)

```yaml
memoryMaps:
  import: my_core.mm.yml
```

### Inline Definition

```yaml
memoryMaps:
  - name: CSR_MAP
    addressBlocks:
      - name: REGS
        baseAddress: 0
        range: 4096
        usage: register
        registers: [...]
```

See [Memory Maps](memory-maps.md) for the complete memory map format.

---

## File Sets

```yaml
fileSets:
  - name: RTL_Sources
    description: RTL source files
    files:
      - path: rtl/core.vhd
        type: vhdl
      - path: rtl/pkg.vhd
        type: vhdl

  - name: Simulation
    files:
      - path: tb/test.py
        type: python

  # Import external file set
  - import: ../common/base.fileset.yml
```

### Supported File Types

`vhdl`, `verilog`, `systemverilog`, `xdc`, `sdc`, `c_header`, `python`, `tcl`,
`yaml`, `json`, `xml`, `markdown`, `pdf`, and others.

---

## Templates

The `ipcraft-spec` package provides starter templates:

| Template | Description |
|----------|-------------|
| `minimal.ip.yml` | Bare minimum valid IP core |
| `basic.ip.yml` | Clock, reset, and simple ports |
| `axi_slave.ip.yml` | AXI-Lite slave with register map |
| `basic.mm.yml` | Simple memory map |
| `array.mm.yml` | Register arrays with count/stride |
| `multi_block.mm.yml` | Multiple address blocks |

---

## Complete Example

See `ipcraft-spec/examples/led/led_controller.ip.yml` for a full LED
controller IP with AXI-Lite interface, parameterized widths, and external
memory map import.
