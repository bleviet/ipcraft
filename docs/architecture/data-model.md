# Data Model

The data model is built on Pydantic v2 and defines the canonical
representation of an IP core. All modules (parsers, generators, validators,
drivers) operate on these shared types.

## Base Classes

### `IpCoreBaseModel`

Shared Pydantic configuration for all models:

- `validate_assignment = True` -- validates on attribute set
- `alias_generator = to_camel` -- Python snake_case maps to YAML camelCase
- `populate_by_name = True` -- accepts both alias and field name

### `StrictModel(IpCoreBaseModel)`

`extra = "forbid"` -- rejects unknown fields. Used for top-level schema objects
where unexpected fields indicate user error.

**Used by:** `IpCore`, `BusInterface`, `Port`, `FileSet`, `Clock`, `Reset`,
`Parameter`, `VLNV`, `MemoryMap`, `ArrayConfig`

### `FlexibleModel(IpCoreBaseModel)`

`extra = "ignore"` -- silently ignores unknown fields. Used for memory map
objects to support vendor extensions.

**Used by:** `RegisterDef`, `BitFieldDef`, `RegisterArrayDef`, `AddressBlock`

---

## Core Types

### `VLNV`

Immutable (frozen) identifier: vendor, library, name, version.

```python
vlnv = VLNV(vendor="company.com", library="ip", name="core", version="1.0")
vlnv.full_name  # "company.com:ip:core:1.0"

# Parse from string
vlnv = VLNV.from_string("company.com:ip:core:1.0")
```

### `IpCore`

The canonical IP core representation. Central to all operations.

**Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `api_version` | `str` | Specification version (required) |
| `vlnv` | `VLNV` | Unique identifier (required) |
| `description` | `str` | Human-readable description |
| `clocks` | `List[Clock]` | Clock definitions |
| `resets` | `List[Reset]` | Reset definitions |
| `ports` | `List[Port]` | Non-bus I/O ports |
| `bus_interfaces` | `List[BusInterface]` | Bus interface definitions |
| `memory_maps` | `List[MemoryMap]` | Register maps |
| `file_sets` | `List[FileSet]` | Source file groups |
| `parameters` | `List[Parameter]` | VHDL generics |
| `use_bus_library` | `Optional[str]` | Path to bus definitions file |

**Key properties:**

- `master_bus_interfaces` / `slave_bus_interfaces` -- filtered lists
- `total_registers` -- count across all memory maps
- `has_memory_maps` / `has_bus_interfaces` -- boolean checks
- `hdl_file_sets` -- filesets containing HDL files

**Lookup methods:** `get_clock(name)`, `get_reset(name)`, `get_port(name)`,
`get_bus_interface(name)`, `get_memory_map(name)`, `get_parameter(name)`,
`get_file_set(name)`

**Validation:** `validate_references()` checks that bus interface associations
(clock, reset, memory map) point to existing objects.

---

## Port Types

### `Port`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `str` | -- | Physical HDL port name |
| `logical_name` | `Optional[str]` | `None` | Logical name for documentation |
| `direction` | `PortDirection` | -- | `IN`, `OUT`, `INOUT` |
| `width` | `Union[int, str]` | `1` | Integer or parameter reference |
| `type` | `str` | `"std_logic"` | VHDL type |

**Properties:** `is_input`, `is_output`, `is_vector`, `range_string`
(VHDL-style range like `(7 downto 0)`)

### `Clock(Port)`

Extends `Port` with `frequency: Optional[str]`. The `frequency_hz` property
parses strings like `"100MHz"` to float Hz values.

### `Reset(Port)`

Extends `Port` with `polarity: Polarity` (`ACTIVE_HIGH` / `ACTIVE_LOW`).
Properties: `is_active_low`, `is_active_high`.

### `PortDirection`

Enum: `IN`, `OUT`, `INOUT`. The `from_string()` class method normalizes
aliases: `"input"` -> `IN`, `"output"` -> `OUT`, `"buffer"` -> `OUT`.

---

## Bus Types

### `BusType(VLNV)`

Inherits from VLNV. Identifies a bus protocol.

### `BusInterface`

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Interface name |
| `type` | `str` | Bus type key (e.g., `"AXI4L"`) |
| `mode` | `BusInterfaceMode` | `MASTER`, `SLAVE`, `SOURCE`, `SINK` |
| `physical_prefix` | `str` | HDL signal prefix |
| `associated_clock` | `Optional[str]` | Clock reference |
| `associated_reset` | `Optional[str]` | Reset reference |
| `memory_map_ref` | `Optional[str]` | Memory map reference (slave only) |
| `use_optional_ports` | `List[str]` | Optional bus signals to include |
| `port_width_overrides` | `Dict[str, int]` | Override default port widths |
| `array` | `Optional[ArrayConfig]` | Array configuration |

**Properties:** `is_master`, `is_slave`, `is_array`, `instance_count`

### `ArrayConfig`

Defines multi-instance bus interfaces:

| Field | Type | Description |
|-------|------|-------------|
| `count` | `int` | Number of instances |
| `index_start` | `int` | Starting index (default 0) |
| `naming_pattern` | `str` | Name template with `{index}` |
| `physical_prefix_pattern` | `str` | Prefix template with `{index}` |

---

## Memory Map Types

### `MemoryMap`

Contains `name`, `description`, and `address_blocks: List[AddressBlock]`.
Post-init validation checks for overlapping blocks.

**Methods:** `get_block_at_address(addr)`, `get_register_by_name(name)`

**Properties:** `total_registers`, `total_address_space`

### `AddressBlock`

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Block name |
| `base_address` | `int` | Start address |
| `range` | `int` | Total byte range |
| `usage` | `BlockUsage` | `REGISTERS`, `MEMORY`, `RESERVED` |
| `default_reg_width` | `int` | Default register width (bits) |
| `registers` | `List[RegisterDef]` | Register definitions |

### `RegisterDef`

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Register name |
| `address_offset` | `int` | Byte offset |
| `size` | `int` | Width in bits (default 32) |
| `access` | `AccessType` | Default access type |
| `reset_value` | `Optional[int]` | Reset value |
| `fields` | `List[BitFieldDef]` | Bit field definitions |
| `count` | `Optional[int]` | Array count |
| `stride` | `Optional[int]` | Array stride |

**Runtime bridge:** `to_runtime_register(bus, base_offset, register_class)`
creates a runtime `Register` or `AsyncRegister`.

### `BitFieldDef`

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Field name |
| `bit_offset` | `int` | LSB position |
| `bit_width` | `int` | Width in bits |
| `bits` | `Optional[str]` | `"[msb:lsb]"` shorthand |
| `access` | `AccessType` | Access type |
| `reset_value` | `Optional[int]` | Reset value |

The `bits` field is a convenience notation. A model validator converts
`"[7:4]"` to `bit_offset=4, bit_width=4`.

### `AccessType`

Enum: `READ_ONLY`, `WRITE_ONLY`, `READ_WRITE`, `WRITE_1_TO_CLEAR`,
`READ_WRITE_1_TO_CLEAR`

Methods: `normalize(value)`, `from_string(value)`, `to_runtime_access()`

---

## File Set Types

### `FileSet`

Contains `name`, `description`, and `files: List[File]`.

**Properties:** `hdl_files`, `constraint_files`, `software_files`,
`documentation_files`

### `File`

| Field | Type | Description |
|-------|------|-------------|
| `path` | `str` | Relative file path |
| `type` | `FileType` | File type enum |
| `description` | `Optional[str]` | Description |
| `is_include_file` | `bool` | Whether this is an include file |

### `FileType`

Enum with 20+ values: `VHDL`, `VERILOG`, `SYSTEMVERILOG`, `XDC`, `SDC`,
`C_HEADER`, `PYTHON`, `TCL`, `YAML`, `JSON`, `XML`, `UNKNOWN`, etc.

---

## Parameter

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Parameter name (maps to VHDL generic) |
| `value` | `Any` | Default value |
| `data_type` | `ParameterType` | `INTEGER`, `NATURAL`, `POSITIVE`, `REAL`, `BOOLEAN`, `STRING` |
| `description` | `Optional[str]` | Description |

**Properties:** `is_numeric`, `is_boolean`, `is_string`

---

## Validation

### `IpCoreValidator`

Performs semantic validation beyond Pydantic type checking:

| Check | Description |
|-------|-------------|
| Unique names | No duplicates in clocks, resets, ports, bus interfaces, memory maps |
| Reference integrity | Bus interface clock/reset/memory map refs point to existing objects |
| Address alignment | Registers aligned to byte boundaries |
| Register overlap | No overlapping registers within address blocks |
| Address bounds | Registers fit within address block range |
| Bus associations | Warnings for missing clock/reset/memory map references |

```python
from ipcraft.model.validators import validate_ip_core

is_valid, errors, warnings = validate_ip_core(ip_core)
```
