# Memory Maps

Memory maps define the register interface of an IP core. They are stored in
`*.mm.yml` files and referenced from the IP YAML via `import`.

## File Format

A memory map file is a YAML list of memory map objects:

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
```

---

## Structure Hierarchy

```
MemoryMap
  AddressBlock[]
    Register[]
      BitField[]
```

---

## Address Blocks

```yaml
addressBlocks:
  - name: REGS
    baseAddress: 0           # Byte address
    range: 4096              # Total byte range
    usage: register          # register | memory | reserved
    defaultRegWidth: 32      # Default register width in bits
    registers: [...]
```

Multiple address blocks are supported. IPCraft validates that blocks do not
overlap.

---

## Registers

```yaml
registers:
  - name: CTRL
    offset: 0               # Byte offset (auto-incremented if omitted)
    size: 32                 # Bits (defaults to defaultRegWidth)
    access: read-write       # Default access for the register
    resetValue: 0x00000000   # Reset value
    description: Control register
    fields: [...]
```

When `offset` is omitted, registers are placed sequentially based on
`defaultRegWidth / 8` byte stride.

---

## Bit Fields

```yaml
fields:
  - name: ENABLE
    bits: "[0:0]"            # Bit range notation [msb:lsb]
    access: read-write
    resetValue: 0
    description: Enable bit

  - name: MODE
    bits: "[2:1]"            # 2-bit field at bits 2..1
    access: read-write
```

The `bits` notation uses `[msb:lsb]` (inclusive). Single-bit fields use
`[n:n]` or `[n]`.

When `bits` is omitted, fields are auto-packed sequentially from bit 0.

---

## Access Types

| Value | Alias | Description |
|-------|-------|-------------|
| `read-write` | `rw` | Normal read/write |
| `read-only` | `ro` | Read-only (status, version) |
| `write-only` | `wo` | Write-only (command triggers) |
| `write-1-to-clear` | `w1c` | Writing 1 clears bits (interrupt flags) |
| `read-write-1-to-clear` | `rw1c` | Read-write with write-1-to-clear behavior |

Access types can be set at register level (applies to all fields) or per-field
(overrides register default).

---

## Register Arrays

For repeated register groups (e.g., per-channel configuration):

```yaml
registers:
  - name: TIMER
    count: 4                 # Number of instances
    stride: 16               # Bytes between instances (must be >= 4)
    registers:               # Template registers within each instance
      - name: CTRL
        offset: 0
        fields:
          - name: ENABLE
            bits: "[0:0]"
            access: read-write

      - name: STATUS
        offset: 4
        access: read-only
        fields:
          - name: BUSY
            bits: "[0:0]"

      - name: COMPARE
        offset: 8
        access: read-write
```

This expands to:

| Register | Address |
|----------|---------|
| `TIMER_0_CTRL` | base + 0 |
| `TIMER_0_STATUS` | base + 4 |
| `TIMER_0_COMPARE` | base + 8 |
| `TIMER_1_CTRL` | base + 16 |
| `TIMER_1_STATUS` | base + 20 |
| ... | ... |

---

## Multi-Document YAML

Memory map files support YAML multi-document format with register templates:

```yaml
# Document 1: Register templates
registerTemplates:
  timer_regs:
    - name: CTRL
      offset: 0
      fields:
        - name: ENABLE
          bits: "[0:0]"
          access: read-write

---

# Document 2: Memory map using templates
- name: CSR_MAP
  addressBlocks:
    - name: TIMERS
      baseAddress: 0
      range: 256
      registers:
        - name: TIMER
          count: 4
          stride: 16
          template: timer_regs
```

---

## Validation Rules

IPCraft enforces:

- **No overlapping address blocks** within a memory map
- **No overlapping registers** within an address block
- **Register alignment** to byte boundaries
- **Stride >= 4** for register arrays (word-aligned)
- **Bit field ranges** must fit within register width

Use `validate_ip_core()` programmatically or rely on parse-time validation.

---

## Example: LED Controller

```yaml
- name: CSR_MAP
  description: LED Controller Control/Status Registers
  addressBlocks:
    - name: CONTROL_STATUS_REGS
      baseAddress: 0
      usage: register
      defaultRegWidth: 32
      registers:
        - name: CONTROL
          description: Global LED controller control register
          fields:
            - name: ENABLE
              bits: "[0:0]"
              access: read-write
              description: Global enable
            - name: PWM_ENABLE
              bits: "[1:1]"
              access: read-write
            - name: BLINK_ENABLE
              bits: "[2:2]"
              access: read-write
            - name: IRQ_ENABLE
              bits: "[3:3]"
              access: read-write

        - name: STATUS
          access: read-only
          fields:
            - name: READY
              bits: "[0:0]"
            - name: ERROR
              bits: "[1:1]"

        - name: LED_OUTPUT
          fields:
            - name: LED_STATE
              bits: "[31:0]"
              access: read-write
              description: One bit per LED
```
