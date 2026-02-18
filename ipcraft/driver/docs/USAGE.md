# Python Driver Usage Guide

This guide explains how to use the generated Python driver for IP cores in both **simulation (Cocotb)** and **hardware (JTAG/UART)**.

## Quick Start

The driver is dynamically generated from your IP Core's YAML memory map. This ensures your software driver is always in sync with your hardware generation.

```python
from ipcraft.driver import load_driver
from ipcraft.driver.bus import CocotbBus  # or JtagBus for hardware

# 1. Initialize Bus
bus = CocotbBus(dut, 's_axi', dut.clk)

# 2. Load Driver
driver = load_driver('my_core.mm.yml', bus)

# 3. Access Registers (Simulation Pattern)
val = await driver.CSR.CONTROL.read_async()
await driver.CSR.CONTROL.write_field_async('ENABLE', 1)
```

---

## 2. Access Patterns

The driver supports two distinct access patterns depending on your environment.

### A. Async API (Simulation / Cocotb)

In Cocotb simulations, bus operations require simulated time to pass, so they are `async`.

| Operation | Method | Example |
|-----------|--------|---------|
| Read Register | `read_async()` | `val = await driver.BLOCK.REG.read_async()` |
| Write Register | `write_async(val)` | `await driver.BLOCK.REG.write_async(0x1234)` |
| Read Field | `read_field_async(name)` | `val = await driver.BLOCK.REG.read_field_async('ENABLE')` |
| Write Field | `write_field_async(name, val)` | `await driver.BLOCK.REG.write_field_async('ENABLE', 1)` |

**Example:**
```python
@cocotb.test()
async def test_my_core(dut):
    # Setup
    bus = CocotbBus(dut, "s_axi", dut.clk)
    driver = load_driver('regs.yaml', bus)
    
    # Read-Modify-Write a specific field
    await driver.GLOBAL.CONTROL.write_field_async('ENABLE', 1)
    
    # Read back status
    ready = await driver.GLOBAL.STATUS.read_field_async('READY')
    assert ready == 1
```

### B. Synchronous API (Hardware / Properties)

For blocking backends (like JTAG or PySerial) where operations happen "instantly" from the software perspective, you can use the concise property syntax.

> **⚠️ Warning:** Do NOT use this syntax in Cocotb tests! It will raise a TypeError because it attempts to operate on a Coroutine object.

| Operation | Syntax | Example |
|-----------|--------|---------|
| Read Field | `reg.field` | `if driver.BLOCK.REG.ENABLE:` |
| Write Field | `reg.field = val` | `driver.BLOCK.REG.ENABLE = 1` |
| Read Register | `reg.read()` | `val = driver.BLOCK.REG.read()` |

**Example (JTAG Script):**
```python
# Hardware interactions are synchronous
driver.GLOBAL.CONTROL.ENABLE = 1

if driver.GLOBAL.STATUS.READY:
    print("Core is ready!")
```

---

## 3. Register Arrays

For repeated blocks (like tables or per-channel settings), use array indexing.

```yaml
# Memory map definition
- name: LUT_ENTRY
  count: 64
  stride: 4
```

**Usage:**
```python
# Write to index 5
await driver.LUT_BLOCK.LUT_ENTRY[5].write_async(0xFF)

# Read field from index 10
val = await driver.LUT_BLOCK.LUT_ENTRY[10].read_field_async('COEFF')
```

---

## 4. Bus Backends

The driver is agnostic to the communication capabilities. You can simply swap the bus object.

### Cocotb (Simulation)
```python
from ipcraft.driver.bus import CocotbBus
bus = CocotbBus(dut, prefix="s_axi", clock=dut.clk)
```

### JTAG (Hardware)
(Implementation specific, typically wrappers around XSDB or OpenOCD)
```python
class JtagBus(AbstractBusInterface):
    def read_word(self, addr): ...
    def write_word(self, addr, val): ...

bus = JtagBus(xsdb_connection)
```

---

## 5. Troubleshooting

**"TypeError: object int can't be used in 'await' expression"**
*   **Cause:** You used `await` on a synchronous method (e.g., `driver.REG.read()`) in simulation, OR the backend is synchronous but you are awaiting it.
*   **Fix:** Use `read_async()` in simulation.

**"TypeError: unsupported operand type(s) for >>: 'coroutine' and 'int'"**
*   **Cause:** You tried to use property syntax `val = driver.REG.FIELD` with an async bus. The driver tried to mask a coroutine object.
*   **Fix:** Use `await driver.REG.read_field_async('FIELD')`.
