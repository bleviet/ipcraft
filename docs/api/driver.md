# Driver API

## Module: `ipcraft.driver`

High-level driver layer for cocotb simulation and hardware register access.

```python
from ipcraft.driver import load_driver, CocotbBus, IpCoreDriver, RuntimeAccessType
```

---

## `load_driver`

Dynamically constructs a register driver from a YAML memory map.

```python
from ipcraft.driver import load_driver

driver = load_driver(
    yaml_path="my_core.mm.yml",
    bus_interface=cocotb_bus,
    async_driver=True,           # True for cocotb, False for sync
)
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `yaml_path` | `str` | -- | Path to `*.mm.yml` file |
| `bus_interface` | `AbstractBusInterface` or `AsyncBusInterface` | -- | Bus backend |
| `async_driver` | `bool` | `True` | Use `AsyncRegister` (True) or `Register` (False) |

**Returns:** `IpCoreDriver` with address blocks and registers as attributes.

### Generated Hierarchy

```
driver                     # IpCoreDriver
  .BLOCK_NAME              # AddressBlock
    .REGISTER_NAME         # Register or AsyncRegister
      .FIELD_NAME          # RegisterBoundField or AsyncRegisterBoundField
    .ARRAY_NAME[index]     # RegisterArrayAccessor -> Register
```

---

## `CocotbBus`

Concrete `AsyncBusInterface` for cocotb simulations.

```python
from ipcraft.driver.bus import CocotbBus

bus = CocotbBus(
    dut=dut,
    bus_name="s_axi",        # Signal prefix in DUT
    clock=dut.clk,
    reset=None,              # Auto-detected if None
    bus_type="axil",         # "axil" or "avmm"
)
```

**Supported bus types:**

| `bus_type` | Backend | Library |
|------------|---------|---------|
| `"axil"` | `AxiLiteMaster` | `cocotbext-axi` |
| `"avmm"` | `AvalonMaster` | `cocotb-bus` |

Reset auto-detection tries: `rst`, `rst_n`, `i_rst_n`, `reset`, `reset_n`.

---

## `IpCoreDriver`

Root container returned by `load_driver()`. Address blocks are attached as
attributes.

```python
driver = load_driver("core.mm.yml", bus)

# Access address blocks
block = driver.REGS

# Access registers
reg = driver.REGS.CTRL

# Access fields
field = driver.REGS.CTRL.ENABLE
```

---

## Complete Cocotb Example

```python
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge
from ipcraft.driver import load_driver, CocotbBus

@cocotb.test()
async def test_led_controller(dut):
    # Start clock
    cocotb.start_soon(Clock(dut.i_clk, 10, units="ns").start())

    # Initialize bus
    bus = CocotbBus(dut, "s_axi", dut.i_clk, bus_type="axil")

    # Load driver from memory map
    driver = load_driver("led_controller.mm.yml", bus)

    # Wait for reset
    dut.i_rst_n.value = 0
    for _ in range(10):
        await RisingEdge(dut.i_clk)
    dut.i_rst_n.value = 1
    for _ in range(2):
        await RisingEdge(dut.i_clk)

    # Enable the controller
    await driver.CONTROL_STATUS_REGS.CONTROL.write_field("ENABLE", 1)

    # Verify ready
    ready = await driver.CONTROL_STATUS_REGS.STATUS.read_field("READY")
    assert ready == 1

    # Set LED output
    await driver.CONTROL_STATUS_REGS.LED_OUTPUT.write_field("LED_STATE", 0xFF)

    # Read back
    val = await driver.CONTROL_STATUS_REGS.LED_OUTPUT.read()
    assert val == 0xFF
```

---

## Custom Bus Backend Example

```python
from ipcraft.runtime import AbstractBusInterface
from ipcraft.driver import load_driver

class UartBus(AbstractBusInterface):
    def __init__(self, serial_port):
        self._port = serial_port

    def read_word(self, addr: int) -> int:
        self._port.write(f"R {addr:#010x}\n".encode())
        return int(self._port.readline().strip(), 16)

    def write_word(self, addr: int, data: int) -> None:
        self._port.write(f"W {addr:#010x} {data:#010x}\n".encode())
        self._port.readline()  # wait for ack

bus = UartBus(serial.Serial("/dev/ttyUSB0", 115200))
driver = load_driver("core.mm.yml", bus, async_driver=False)

driver.REGS.CTRL.write_field("ENABLE", 1)
status = driver.REGS.STATUS.read()
```
