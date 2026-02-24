# Model API

::: ipcraft.model

## Module: `ipcraft.model`

All model types are exported from `ipcraft.model`:

```python
from ipcraft.model import (
    IpCore, VLNV, Parameter, ParameterType,
    Clock, Reset, Polarity,
    Port, PortDirection,
    BusInterface, BusType, ArrayConfig,
    MemoryMap, AddressBlock, RegisterDef, BitFieldDef, RegisterArrayDef,
    AccessType, BlockUsage, MemoryMapReference,
    FileSet, File, FileType,
    StrictModel, FlexibleModel,
)
```

---

## `IpCore`

The canonical IP core representation.

```python
from ipcraft.model import IpCore

# Fields
ip_core.api_version      # str
ip_core.vlnv             # VLNV
ip_core.description      # str
ip_core.clocks           # List[Clock]
ip_core.resets           # List[Reset]
ip_core.ports            # List[Port]
ip_core.bus_interfaces   # List[BusInterface]
ip_core.memory_maps      # List[MemoryMap]
ip_core.file_sets        # List[FileSet]
ip_core.parameters       # List[Parameter]
ip_core.use_bus_library  # Optional[str]

# Lookup by name (returns None if not found)
ip_core.get_clock("i_clk")
ip_core.get_reset("i_rst_n")
ip_core.get_port("o_irq")
ip_core.get_bus_interface("S_AXI_LITE")
ip_core.get_memory_map("CSR_MAP")
ip_core.get_parameter("DATA_WIDTH")
ip_core.get_file_set("RTL_Sources")

# Computed properties
ip_core.master_bus_interfaces    # List[BusInterface]
ip_core.slave_bus_interfaces     # List[BusInterface]
ip_core.total_registers          # int
ip_core.has_memory_maps          # bool
ip_core.has_bus_interfaces       # bool
ip_core.hdl_file_sets            # List[FileSet]

# Reference validation
errors: List[str] = ip_core.validate_references()
```

---

## `VLNV`

Frozen (immutable) vendor-library-name-version identifier.

```python
from ipcraft.model import VLNV

vlnv = VLNV(vendor="co.com", library="ip", name="core", version="1.0")
vlnv.full_name                # "co.com:ip:core:1.0"

vlnv = VLNV.from_string("co.com:ip:core:1.0")
```

---

## `Parameter`

Maps to VHDL generics.

```python
from ipcraft.model import Parameter, ParameterType

p = Parameter(name="WIDTH", value=32, data_type=ParameterType.INTEGER)
p.is_numeric   # True
p.is_boolean   # False
p.is_string    # False
```

---

## `Port`, `Clock`, `Reset`

```python
from ipcraft.model import Port, PortDirection, Clock, Reset, Polarity

port = Port(name="o_data", direction=PortDirection.OUT, width=8)
port.is_vector      # True
port.range_string   # "(7 downto 0)"

clock = Clock(name="i_clk", direction=PortDirection.IN, frequency="100MHz")
clock.frequency_hz  # 100000000.0

reset = Reset(name="i_rst_n", direction=PortDirection.IN, polarity=Polarity.ACTIVE_LOW)
reset.is_active_low  # True
```

---

## `BusInterface`

```python
from ipcraft.model import BusInterface, ArrayConfig

bi = BusInterface(
    name="S_AXI", type="AXI4L", mode="slave",
    physical_prefix="s_axi_",
    associated_clock="i_clk",
    associated_reset="i_rst_n",
    memory_map_ref="CSR_MAP",
)
bi.is_slave         # True
bi.is_array         # False
bi.instance_count   # 1

# With array
bi_arr = BusInterface(
    name="M_AXIS", type="AXIS", mode="master",
    array=ArrayConfig(count=4, naming_pattern="M_AXIS_CH{index}",
                      physical_prefix_pattern="m_axis_ch{index}_"),
)
bi_arr.is_array        # True
bi_arr.instance_count  # 4
```

---

## `MemoryMap`, `AddressBlock`, `RegisterDef`, `BitFieldDef`

```python
from ipcraft.model import MemoryMap, AddressBlock, RegisterDef, BitFieldDef, AccessType

field = BitFieldDef(name="EN", bit_offset=0, bit_width=1, access=AccessType.READ_WRITE)
reg = RegisterDef(name="CTRL", address_offset=0, fields=[field])
block = AddressBlock(name="REGS", base_address=0, range=4096, registers=[reg])
mmap = MemoryMap(name="CSR", address_blocks=[block])

mmap.total_registers       # 1
mmap.total_address_space   # 4096
block.end_address          # 4096
block.contains_address(0)  # True
reg.hex_address            # "0x0000"

# Access type conversion
AccessType.READ_WRITE.to_runtime_access()  # "rw"
AccessType.from_string("write-1-to-clear") # AccessType.WRITE_1_TO_CLEAR
```

---

## `FileSet`, `File`

```python
from ipcraft.model import FileSet, File, FileType

f = File(path="rtl/core.vhd", type=FileType.VHDL)
f.file_name       # "core.vhd"
f.is_hdl          # True
f.is_constraint   # False

fs = FileSet(name="RTL", files=[f])
fs.hdl_files      # [f]
```

---

## `BusLibrary`

Singleton access to bus definitions.

```python
from ipcraft.model.bus_library import get_bus_library, BusLibrary

lib = get_bus_library()
lib.list_bus_types()                    # ["AXI4L", "AXIS", ...]
bus_def = lib.get_bus_definition("AXI4L")
bus_def.required_ports                  # List[PortDefinition]
bus_def.optional_ports                  # List[PortDefinition]
bus_def.get_suggested_prefix("slave")   # "s_axil_"

lib.get_bus_info("AXI4L", include_ports=True)  # Dict with details
```

---

## `IpCoreValidator`

```python
from ipcraft.model.validators import validate_ip_core, IpCoreValidator

# Quick validation
is_valid, errors, warnings = validate_ip_core(ip_core)

# Detailed validation
validator = IpCoreValidator(ip_core)
validator.validate_all()
validator.errors    # List[ValidationError]
validator.warnings  # List[ValidationError]
print(validator.get_error_summary())
```
