# Bus Library

IPCraft includes a bus library with standard interface definitions. The library
defines port names, directions, widths, and required/optional status for each
bus type.

## Supported Bus Types

| Key | Full Type | Modes |
|-----|-----------|-------|
| `AXI4_LITE` | `ipcraft.busif.axi4_lite.1.0` | slave, master |
| `AXI_STREAM` | `ipcraft.busif.axi_stream.1.0` | source, sink |
| `AVALON_MM` | `ipcraft.busif.avalon_mm.1.0` | slave, master |
| `AVALON_ST` | `ipcraft.busif.avalon_st.1.0` | source, sink |
| `AXI4_FULL` | `ipcraft.busif.axi4_full.1.0` | slave, master |

The `type` field in bus interface definitions uses the fully qualified
`vendor.library.name.version` format (e.g., `ipcraft.busif.axi4_lite.1.0`).

## Type Aliases

IPCraft normalizes bus type names. These aliases are accepted wherever a bus
type is expected:

| Alias | Resolves to |
|-------|-------------|
| `AXIL`, `AXI4L`, `AXI4-LITE`, `AXI4LITE` | `AXI4_LITE` |
| `AVMM`, `AVALON-MM` | `AVALON_MM` |
| `AVST`, `AVALON-ST` | `AVALON_ST` |
| `AXIS`, `AXI-STREAM`, `AXISTREAM` | `AXI_STREAM` |

## Physical Prefix Conventions

Each bus type has suggested prefixes based on mode:

| Bus Type | Slave/Sink Prefix | Master/Source Prefix |
|----------|-------------------|----------------------|
| `AXI4_LITE` | `s_axil_` | `m_axil_` |
| `AXI_STREAM` | `s_axis_` | `m_axis_` |
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
ipcraft list-buses AXI4_LITE --ports
```

### Using Optional Ports

By default, only required ports are included. Add optional signals via
`useOptionalPorts`:

```yaml
busInterfaces:
  - name: S_AXI_LITE
    type: ipcraft.busif.axi4_lite.1.0
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

## Bus Definitions Directory

The bus library is defined in `ipcraft-spec/bus_definitions/`, with one file
per bus type:

| File | Bus Type |
|------|----------|
| `axi4_lite.yml` | AXI4-Lite |
| `axi_stream.yml` | AXI-Stream |
| `avalon_mm.yml` | Avalon Memory-Mapped |
| `avalon_st.yml` | Avalon Streaming |
| `axi4_full.yml` | AXI4 Full |

IPCraft loads the bus definitions bundled with the `ipcraft-spec` package
automatically. No configuration is required in the IP YAML.

## Programmatic Access

```python
from ipcraft.model.bus_library import get_bus_library

lib = get_bus_library()

# List available types
for bus_type in lib.list_bus_types():
    print(bus_type)

# Get definition details
bus_def = lib.get_bus_definition("AXI4_LITE")
print(bus_def.description)
print(bus_def.required_ports)
print(bus_def.optional_ports)
```
