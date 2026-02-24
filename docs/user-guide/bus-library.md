# Bus Library

IPCraft includes a bus library with standard interface definitions. The library
defines port names, directions, widths, and required/optional status for each
bus type.

## Supported Bus Types

| Key | VLNV | Modes |
|-----|------|-------|
| `AXI4L` | `arm.com/amba/axi4l/r0p0_0` | slave, master |
| `AXIS` | `arm.com/amba/axis/1.0` | source, sink |
| `AVALON_MM` | `intel.com/avalon/avalon_mm/1.0` | slave, master |
| `AVALON_ST` | `intel.com/avalon/avalon_st/1.0` | source, sink |

## Type Aliases

IPCraft normalizes bus type names. These aliases are accepted wherever a bus
type is expected:

| Alias | Resolves to |
|-------|-------------|
| `AXIL`, `AXI4-LITE`, `AXI4LITE` | `AXI4L` |
| `AVMM`, `AVALON-MM` | `AVALON_MM` |
| `AVST`, `AVALON-ST` | `AVALON_ST` |
| `AXI-STREAM`, `AXISTREAM` | `AXIS` |

## Physical Prefix Conventions

Each bus type has suggested prefixes based on mode:

| Bus Type | Slave/Sink Prefix | Master/Source Prefix |
|----------|-------------------|----------------------|
| `AXI4L` | `s_axil_` | `m_axil_` |
| `AXIS` | `s_axis_` | `m_axis_` |
| `AVALON_MM` | `avs_` | `avm_` |
| `AVALON_ST` | `asi_` | `aso_` |

The parser uses these prefixes for automatic bus interface detection from VHDL
port names.

## Port Definitions

Each bus type defines required and optional ports with default widths and
directions. Use the CLI to inspect:

```bash
# List all bus types
ipcraft list-buses

# Show AXI4-Lite ports
ipcraft list-buses AXI4L --ports
```

### Using Optional Ports

By default, only required ports are included. Add optional signals via
`useOptionalPorts`:

```yaml
busInterfaces:
  - name: S_AXI_LITE
    type: AXI4L
    mode: slave
    useOptionalPorts:
      - AWPROT
      - ARPROT
```

### Overriding Port Widths

Default widths (e.g., 32-bit address) can be overridden:

```yaml
portWidthOverrides:
  AWADDR: 12
  ARADDR: 12
  WDATA: 32
  RDATA: 32
```

## Bus Definitions File

The bus library is defined in `ipcraft-spec/common/bus_definitions.yml`. The
`useBusLibrary` field in the IP YAML points to this file:

```yaml
useBusLibrary: ../common/bus_definitions.yml
```

If omitted, IPCraft loads the default bus definitions bundled with the
`ipcraft-spec` package.

## Programmatic Access

```python
from ipcraft.model.bus_library import get_bus_library

lib = get_bus_library()

# List available types
for bus_type in lib.list_bus_types():
    print(bus_type)

# Get definition details
bus_def = lib.get_bus_definition("AXI4L")
print(bus_def.description)
print(bus_def.required_ports)
print(bus_def.optional_ports)
```
