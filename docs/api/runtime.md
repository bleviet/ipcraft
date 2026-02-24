# Runtime API

## Module: `ipcraft.runtime`

Register access classes for both simulation and hardware environments.

```python
from ipcraft.runtime import (
    Register, AsyncRegister,
    BitField, RuntimeAccessType, BusIOError,
    AbstractBusInterface, AsyncBusInterface,
    RegisterArrayAccessor,
)
```

---

## `Register`

Synchronous register access for hardware backends.

```python
from ipcraft.runtime import Register, BitField, RuntimeAccessType

fields = [
    BitField("ENABLE", offset=0, width=1, access=RuntimeAccessType.RW),
    BitField("MODE", offset=1, width=2, access=RuntimeAccessType.RW),
    BitField("STATUS", offset=8, width=4, access=RuntimeAccessType.RO),
]

reg = Register("CTRL", offset=0x00, bus=my_bus, fields=fields)

# Full register operations
val = reg.read()
reg.write(0x01)

# Field operations (read-modify-write)
reg.write_field("ENABLE", 1)
en = reg.read_field("ENABLE")

# Bulk field operations
all_fields = reg.read_all_fields()    # Dict[str, int]
reg.write_multiple_fields({"ENABLE": 1, "MODE": 2})

# Bound field access
val = reg.ENABLE.read()
reg.ENABLE.write(1)

# Field metadata
reg.get_field_names()   # ["ENABLE", "MODE", "STATUS"]
reg.get_field_info()    # Dict with field details
reg.reset_value         # Computed from field reset values
```

---

## `AsyncRegister`

Asynchronous register access for cocotb simulations. Same interface as
`Register` but all I/O methods are `async`.

```python
reg = AsyncRegister("CTRL", offset=0x00, bus=cocotb_bus, fields=fields)

val = await reg.read()
await reg.write(0x01)
await reg.write_field("ENABLE", 1)
en = await reg.read_field("ENABLE")

# Bound field access
val = await reg.ENABLE.read()
await reg.ENABLE.write(1)
```

---

## `BitField`

Immutable bit field descriptor (dataclass).

```python
from ipcraft.runtime import BitField, RuntimeAccessType

field = BitField(
    name="ENABLE",
    offset=0,
    width=1,
    access=RuntimeAccessType.RW,
    description="Enable bit",
    reset_value=0,
)

field.mask           # 0x1
field.max_value      # 1

# Bit manipulation
field.extract_value(0xFF)       # 1
field.insert_value(0x00, 1)     # 0x01
```

Maximum register width: 64 bits.

---

## `RuntimeAccessType`

```python
from ipcraft.runtime import RuntimeAccessType

RuntimeAccessType.RO    # Read-only
RuntimeAccessType.WO    # Write-only
RuntimeAccessType.RW    # Read-write
RuntimeAccessType.RW1C  # Read-write, write-1-to-clear
```

---

## `BusIOError`

Raised on bus read/write failures.

```python
from ipcraft.runtime import BusIOError

try:
    val = reg.read()
except BusIOError as e:
    print(f"Bus error: {e}")
```

---

## Bus Interfaces

### `AbstractBusInterface` (Synchronous)

```python
from ipcraft.runtime import AbstractBusInterface

class JtagBus(AbstractBusInterface):
    def read_word(self, addr: int) -> int:
        ...
    def write_word(self, addr: int, data: int) -> None:
        ...
```

### `AsyncBusInterface` (Asynchronous)

```python
from ipcraft.runtime import AsyncBusInterface

class MyAsyncBus(AsyncBusInterface):
    async def read_word(self, addr: int) -> int:
        ...
    async def write_word(self, addr: int, data: int) -> None:
        ...
```

---

## `RegisterArrayAccessor`

Lazy accessor for register arrays. Creates register instances on-demand when
indexed.

```python
from ipcraft.runtime import RegisterArrayAccessor

accessor = RegisterArrayAccessor(
    name="LUT",
    base_offset=0x100,
    count=64,
    stride=4,
    fields=[...],
    bus=my_bus,
    register_class=AsyncRegister,
)

# Access by index (creates register on first access)
reg = accessor[5]
val = await reg.read()
```

---

## Write-1-to-Clear Handling

When performing read-modify-write on a register containing W1C fields, the
RMW logic automatically zeros W1C fields in the written value to prevent
accidental clearing:

```python
# Register: [RW1C: IRQ_FLAG at bit 0] [RW: ENABLE at bit 1]
# Writing ENABLE=1 via write_field will NOT accidentally clear IRQ_FLAG
await reg.write_field("ENABLE", 1)
# Internally: read -> zero W1C bits -> set ENABLE -> write
```
