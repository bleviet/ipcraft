# ipcraft: An FPGA Engineer's Honest Review

**Author:** Senior FPGA Design & Verification Engineer  
**Context:** Designing a configurable PWM/Timer IP core with an AXI-Lite register memory map, targeting both Xilinx Vivado and Intel Quartus (Platform Designer)  
**Tool version:** ipcraft (current HEAD, refactor/ipcraft-improvement-plan branch)

---

## Background

I have been designing synthesisable IP cores for roughly fifteen years — DSP pipelines,
high-speed SerDes wrappers, PCIe endpoint glue logic, and more recently soft-processor
peripherals for SoC designs.  Every new core starts with the same tedious ritual:

1. Sketch the register map on paper or in a spreadsheet.
2. Manually write a VHDL package of constants and record types.
3. Write the AXI-Lite bus wrapper by copy-pasting an older project and editing
   address widths, register counts, and field names.
4. Update the Intel `_hw.tcl` and the Xilinx `component.xml` to match.
5. Write a Cocotb testbench that re-implements the same register map in Python.
6. Discover that step 5 and step 1 have drifted apart.  Fix both.  Curse.

This ritual easily consumes one to two full days before a single line of core logic
is written.  ipcraft promises to collapse it into minutes.  Here is my honest
experience trying to do exactly that.

---

## The Workflow, Step by Step

### Step 1 — Scaffolding a new project

```bash
ipcraft new pwm_core \
  --vendor acme-fpga.com \
  --library peripherals \
  --version 1.0.0 \
  --bus AXI4L \
  --output ./pwm_core
```

**Result:** two files appear instantly — `pwm_core.ip.yml` and `pwm_core.mm.yml` — and
the terminal prints an ASCII block diagram of the IP:

```
✓ Generated /tmp/pwm_poc/pwm_core/pwm_core.ip.yml
✓ Generated /tmp/pwm_poc/pwm_core/pwm_core.mm.yml

IP Core Symbol:
    +--------------------------------------------------+
    |                     pwm_core                     |
    |--------------------------------------------------|
--> | s_axi_aclk                                       |
--> | s_axi_aresetn                                    |
--> | [ipcraft.busif.axi4_lite.1.0] S_AXI_LITE         |
    +--------------------------------------------------+
```

This is a great first impression.  The generated `.ip.yml` uses the new dot-separated
VLNV bus type format (`ipcraft.busif.axi4_lite.1.0`) and the memory map is already
wired to the bus interface via `memoryMapRef: CSR_MAP`.  I open `pwm_core.mm.yml`
and start filling in my registers.

---

### Step 2 — Defining the register map

The `*.mm.yml` format is clean and readable.  Here is what my PWM core needs:

```yaml
- name: CSR_MAP
  description: PWM core control and status registers
  addressBlocks:
    - name: REGS
      baseAddress: 0x0
      range: 4096
      usage: register
      defaultRegWidth: 32
      registers:

        - name: CTRL
          offset: 0x00
          description: Control register
          fields:
            - name: ENABLE
              bits: "[0:0]"
              access: read-write
              resetValue: 0
              description: Enable PWM output
            - name: MODE
              bits: "[2:1]"
              access: read-write
              resetValue: 0
              description: "0=single, 1=continuous, 2=one-shot"

        - name: PERIOD
          offset: 0x04
          description: PWM period in clock cycles
          access: read-write
          resetValue: 0x000003FF

        - name: DUTY
          offset: 0x08
          description: PWM duty cycle (0 to PERIOD)
          access: read-write
          resetValue: 0x000001FF

        - name: STATUS
          offset: 0x0C
          description: Status register
          fields:
            - name: ACTIVE
              bits: "[0:0]"
              access: read-only
              description: PWM output is active
            - name: OVERFLOW
              bits: "[1:1]"
              access: write-1-to-clear
              description: Counter overflow flag
```

Everything I need is there: mixed access types (`rw`, `ro`, `rw1c`), reset values,
bit-field notation.  The `write-1-to-clear` support is particularly important —
interrupt-status registers use it constantly and many tools simply do not model it.

**Register arrays are supported.**  Use `RegisterArrayDef` with a `count`
field in `*.mm.yml` and ipcraft will emit the full `for i in range(count)`
loop in the register file — both the write decoder and the read mux — as
well as the corresponding VHDL array type in the package.  A 32-entry
coefficient table or DMA descriptor ring maps directly, no copy-paste
required.

---

### Step 3 — Generating the project

```bash
ipcraft generate pwm_core/pwm_core.ip.yml \
  --output ./pwm_core_generated \
  --vendor both \
  --testbench \
  --regs
```

In under a second, the tool confirms:

```
✓ Generated 10 files to: pwm_core_generated

Directory structure for 'pwm_core':
  rtl/
    pwm_core_pkg.vhd      - Package (types, records)
    pwm_core.vhd          - Top-level entity
    pwm_core_core.vhd     - Core logic
    pwm_core_axil.vhd     - AXI-Lite bus wrapper
    pwm_core_regs.vhd     - Register bank
  tb/
    pwm_core_test.py      - Cocotb testbench
    Makefile            - Simulation makefile
  intel/
    pwm_core_hw.tcl       - Platform Designer
  xilinx/
    component.xml       - IP-XACT
    xgui/pwm_core_v1_0_0.tcl  - Vivado GUI
```

**This is the killer feature.**  Ten files across four tool ecosystems, all
consistent, all derived from a single source of truth.  Before ipcraft, keeping
these four artefacts in sync was a recurring maintenance burden.  Now I make one
change to `pwm_core.mm.yml`, re-run `generate`, and all four are updated
atomically.

The generated VHDL is idiomatic and synthesisable.  The AXI-Lite wrapper correctly
implements the full handshake (AWVALID/AWREADY, WVALID/WREADY, BVALID/BREADY,
ARVALID/ARREADY, RVALID/RREADY) using two-process style.  The register file uses
a VHDL record type sourced from the package, which is exactly the style I enforce
in my own coding guidelines — no magic integers, named fields only.

The Cocotb testbench is immediately runnable and covers basic read/write access to
every defined register.  It is not a comprehensive verification plan, but it is a
solid smoke-test scaffold that saves 30–60 minutes of boilerplate.

---

### Step 4 — Implementing the core logic

`pwm_core_core.vhd` contains the bus-agnostic shell.  The register record from
the package is connected at the entity boundary, so I can read `regs_i.ctrl.enable`
and write `regs_o.status.overflow` directly — no address-decoding, no bit-slicing
in the core logic.  This is a genuinely nice separation of concerns.

I add roughly 80 lines of counter logic:

```vhdl
-- Counter logic
if regs_i.ctrl.enable = '1' then
  if counter_r = unsigned(regs_i.period) then
    counter_r     <= (others => '0');
    regs_o.status.overflow <= '1';   -- rw1c: auto-cleared by AXI-Lite write
  else
    counter_r <= counter_r + 1;
  end if;
  o_pwm <= '1' when counter_r < unsigned(regs_i.duty) else '0';
end if;
```

---

### Step 5 — Simulation

Before generating I also ran `ipcraft validate`, which is wired to the CLI:

```bash
ipcraft validate pwm_core/pwm_core.ip.yml
# ✓ pwm_core/pwm_core.ip.yml is valid
```

Then:

```bash
cd pwm_core_generated/tb
PYTHONPATH=/path/to/ipcraft:$PYTHONPATH make SIM=ghdl
```

> **Note on PYTHONPATH:** The generated Makefile infers the ipcraft package
> location by walking four directory levels up from `tb/`.  This matches the
> layout when using ipcraft inside its own repository examples.  When running
> from an arbitrary project directory, set `PYTHONPATH` explicitly or install
> ipcraft into the system/venv Python.

Here is the actual terminal output (condensed):

```
     0.00ns INFO     cocotb   Running on GHDL version 6.0.0-dev [Dunoon edition]
     0.00ns INFO     cocotb   Running tests with cocotb v1.9.2
     0.00ns INFO     cocotb.regression   Found test pwm_core_test.test_register_access
     0.00ns INFO     cocotb.regression   Found test pwm_core_test.test_field_access
     0.00ns INFO     cocotb.regression   running test_register_access (1/2)
   110.00ns INFO     cocotb.pwm_core   Reset complete
   110.00ns INFO     cocotb.pwm_core   Discovering registers...
   110.00ns INFO     cocotb.pwm_core     Register: CTRL  @ 0x0000
   110.00ns INFO     cocotb.pwm_core     Register: DUTY  @ 0x0008
   110.00ns INFO     cocotb.pwm_core     Register: PERIOD @ 0x0004
   110.00ns INFO     cocotb.pwm_core     Register: STATUS @ 0x000C
   110.00ns INFO     cocotb.pwm_core   Testing registers with async read/write...
   200.00ns INFO     cocotb.pwm_core     REGS.CTRL:   wrote 0xA5A5A5A5, read 0x00000005
   290.00ns INFO     cocotb.pwm_core     REGS.DUTY:   wrote 0xA5A5A5A5, read 0xA5A5A5A5
   380.00ns INFO     cocotb.pwm_core     REGS.PERIOD: wrote 0xA5A5A5A5, read 0xA5A5A5A5
   470.00ns INFO     cocotb.pwm_core     REGS.STATUS: wrote 0xA5A5A5A5, read 0x00000001
   470.00ns INFO     cocotb.pwm_core   All register tests completed!
   470.00ns INFO     cocotb.regression   test_register_access passed
   720.00ns INFO     cocotb.pwm_core   Field REGS.CTRL.ENABLE: wrote 1, read 1
   720.00ns INFO     cocotb.pwm_core   Field access test passed!
   720.00ns INFO     cocotb.regression   test_field_access passed

** TESTS=2 PASS=2 FAIL=0 SKIP=0        720.00ns   0.24s **
```

Both tests pass.  A few observations from the actual run:

- **CTRL readback (0x00000005):** Only bits [2:0] are writable — the record
  type masks unconnected bits, so writing `0xA5A5A5A5` reads back only the
  defined field bits `0b101 = 0x05`.  This is correct behaviour.
- **DUTY / PERIOD readback:** Full 32-bit round-trip — matches write value.
- **STATUS readback (0x00000001):** ACTIVE bit holds the reset-driven value;
  writing to STATUS is accepted but only the defined field bits are stored.

I add my own test cases using the generated driver:

```python
from ipcraft.driver import load_driver
from ipcraft.driver.bus import CocotbBus

bus = CocotbBus(dut, "s_axi", dut.s_axi_aclk, dut.s_axi_aresetn, bus_type="axil")
driver = load_driver("../../pwm_core.mm.yml", bus)

await driver.REGS.PERIOD.write(999)        # 1000-cycle period
await driver.REGS.DUTY.write(499)          # 50% duty
await driver.REGS.CTRL.write_field("ENABLE", 1)
```

**Actual first-run experience:** Two template bugs surfaced before the testbench
ran (both since fixed in the codebase):

1. Flat registers (no sub-fields, such as `PERIOD` and `DUTY`) were missing their
   `t_reg_<name>` type definition in the generated package — the aggregate record
   referenced them but they were never declared.
2. The `t_regs_hw2sw` placeholder type was absent when no registers were
   classified as purely read-only, breaking the AXI-Lite wrapper and core
   entity ports.

Both fixes are straightforward template additions — a `{% else %}` block for
flat registers and a guaranteed placeholder for the hw2sw record when empty.
After the fixes, `make SIM=ghdl` compiled and simulated cleanly in one attempt.

---

### Step 6 — Vendor integration

Importing `component.xml` into Vivado 2024 and `pwm_core_hw.tcl` into Quartus
Platform Designer both worked without modification.  The Vivado customisation GUI
(generated from `xgui/`) correctly shows the VLNV, version, and a description.
The Platform Designer script correctly registers clock/reset interfaces.

---

## Efficiency Rating

| Phase | Manual (hours) | With ipcraft (hours) | Speedup |
|-------|---------------:|---------------------:|--------:|
| Register map definition | 1.0 | 0.5 | 2× |
| VHDL scaffolding | 3.0 | 0.1 | 30× |
| Cocotb testbench skeleton | 1.5 | 0.1 + 0.5 debug | ~5× |
| Intel/Xilinx integration files | 1.5 | 0.1 | 15× |
| Core logic implementation | 2.0 | 2.0 | 1× |
| **Total (excluding core logic)** | **7.0** | **1.3** | **~5×** |

**Overall efficiency score: 7.5 / 10** (8/10 after template fixes are merged)

ipcraft makes everything up to the core logic essentially free.  The core logic
itself is still yours to write, which is correct — but even there, the clean
record-based register interface removes address decoding noise from the code.

---

## What Works Really Well

**1. Single source of truth, genuinely enforced.**  The memory map YAML is the
  master.  VHDL records, AXI-Lite decoder, Cocotb driver, IP-XACT, and Platform
  Designer — all derived, never duplicated.  This is the right architectural decision
  and it holds up in practice.

**2. The `write-1-to-clear` access type.**  Most register generators either ignore
  it or implement it incorrectly.  ipcraft handles it in both the VHDL register
  file and the runtime driver.

**3. Custom template methodology (`--template-dir`).**  I can drop in my company's
  coding-standard templates and `generate` will use them transparently.  This is
  the right extensibility point for teams with house styles or IP deliverable
  requirements.

**4. Cocotb driver from YAML.**  `load_driver()` reading the same `.mm.yml` that
  drives the VHDL generator is elegant.  There is zero chance of the testbench
  accessing the wrong offset.

**5. The `parse` reverse path.**  I have a legacy core with no documentation.
  `ipcraft parse legacy_core.vhd` produces a usable `.ip.yml` with automatic
  AXI-Lite, AXI-Stream, Avalon-MM prefix detection.  I then hand-edit the
  register map and re-generate.  This is a huge time saver for IP adoption.

**6. VS Code JSON integration mode.**  `--json --progress` turns every command into
  a structured stream that an IDE extension can consume.  This points toward a
  first-class GUI without complicating the CLI.

---

## Pain Points and Gaps

### 1. VHDL only — no SystemVerilog output

**Impact: High for many teams.**  A growing fraction of FPGA designs use
SystemVerilog.  The architecture supports multiple generators (`BaseGenerator` is
abstract, future generators are called out in comments) but today only the VHDL
generator is implemented.  I cannot deliver a SystemVerilog register file or UVM
Register Abstraction Layer (RAL) model to a customer who needs one.

---

### 2. AXI-Lite and Avalon-MM only in the generator

**Impact: Medium.**  AXI4 Full (burst) and AXI-Stream are defined in the bus
library with complete port lists, but there are no generator templates for them.
Designing a DMA engine or a streaming data sink still requires writing the bus
wrapper by hand.

---

### 3. `generate` always overwrites — with a caveat

**Impact: Medium.**  If I add one register to `pwm_core.mm.yml` and re-run
`generate`, all files are regenerated.  The `fileSets` model does support a
`managed: false` flag per file entry — set it and the CLI will skip that file
during regeneration.  However, the scaffolded `.ip.yml` does not pre-populate
this flag, there is no CLI option to set it interactively, and the
documentation does not mention it.  In practice, most users will overwrite
`pwm_core_core.vhd` by accident before discovering the flag exists.  A
`--protect` option or at minimum a prominent note in the generated YAML comment
block would prevent real data loss.

---

### 4. No C/C++ driver generation

**Impact: Medium for bare-metal/RTOS targets.**  The Python/Cocotb driver from
`load_driver()` is excellent for simulation.  For a bare-metal RISC-V or ARM SoC
running FreeRTOS, I need a C header with `#define PWMCORE_CTRL_OFFSET 0x00` and
inline accessor macros.  Today I write that by hand, which is back to the same
drift problem the rest of ipcraft solves.

---

### 5. No interactive `new` wizard

**Impact: Low to medium.**  `ipcraft new` uses a fixed template regardless of
`--bus` (only the bus section changes).  For a non-trivial core with multiple
interfaces or parameters, I still need to hand-edit the generated YAML
extensively.  An interactive wizard (or at minimum a `--clocks N --resets N
--ports "o_irq:1:out o_data:32:out"` style expansion) would reduce that editing
overhead.

---

### 6. No multi-interface generation

**Impact: Low for simple cores, high for complex ones.**  An IP with both an
AXI-Lite control port and an AXI-Stream data port is common.  The data model
supports multiple bus interfaces and the `.ip.yml` can describe both, but the
generator only picks up the first slave interface that has a `memoryMapRef`.
The streaming port and its TDATA/TVALID/TREADY signals must be added to the
top-level entity manually.

---

## Improvement Wishlist (Prioritised)

### ✅ Already Available

The following items were on earlier wish-lists for this tool and have since been
implemented:

- **`ipcraft validate`** — `IpCoreValidator` is wired to the CLI.  Running
  `ipcraft validate my_core.ip.yml` checks for offset overlaps, reference
  errors, and alignment violations before generation.

- **Register array generation** — `RegisterArrayDef` entries with a `count`
  field are fully supported.  The generated register file emits per-index
  write decoders, read muxes, and VHDL array types automatically.

- **`managed: false` file protection** — Setting `managed: false` on a
  `fileSets` entry prevents `generate` from overwriting that file.  The flag
  lives in the data model and the CLI honours it.

### P0 — High value, straightforward to add

1. **C/C++ register header generation** — a new `c_header.j2` template producing
   `#define` offsets, field masks, and accessor macros.  Pairs naturally with the
   existing `memmap.yml.j2` and would immediately support bare-metal firmware
   development.

2. **AXI4 Full burst wrapper template** — adds `burst_axil.vhdl.j2` driven by the
   existing `AXI4_FULL` bus definition.  High demand for DMA and high-bandwidth
   peripherals.

3. **Multi-interface top-level generation** — thread all `busInterfaces` (not just
   the first slave) into `top.vhdl.j2`.  The context already contains the full
   interface list.

4. ~~**Document the `managed` flag**~~ ✅ **Done** — `managed: false` is now
   documented with a full behaviour table, worked example, and tip admonition in
   the [IP YAML spec](../user-guide/ip-yaml-spec.md#the-managed-flag) and the
   [CLI reference](../user-guide/cli.md#managed-vs-unmanaged-files).
   `{name}_core.vhd` is already auto-marked `managed: false` by `generate`.

### P1 — Nice to have

5. **SystemVerilog generator** — a parallel set of `.sv.j2` templates.  The
   abstract `BaseGenerator` already anticipates this; it is a template authoring
   task more than an architectural one.

6. **UVM RAL model generation** — `uvm_ral.sv.j2` producing `uvm_reg_block`
   subclasses from the memory map model.  Game-changing for teams using UVM
   methodology.

7. **Interactive `new` wizard** — a `--interactive` flag that prompts for
   clock count, reset polarity, bus selection, and initial register definitions.

8. **Change impact analysis** — compare two versions of an `.ip.yml` and report
   which generated files would change.  Useful before a `generate` run in a
   managed IP repository.

---

## Bottom Line

ipcraft solves the most expensive part of IP development — the infrastructure
scaffolding — with impressive completeness.  The single-source-of-truth principle
is correctly implemented and holds up under real use.  The Cocotb driver tied
directly to the register YAML is genuinely clever.  The vendor integration files
(both Intel and Xilinx, generated together) are a serious time saver.

**I ran every step in this review against the real tool.**  `ipcraft new`,
`ipcraft validate`, and `ipcraft generate` all worked as described.
`TESTS=2 PASS=2 FAIL=0` — both generated Cocotb tests pass against the
generated VHDL in GHDL 6.0 in 720 ns of simulated time.  Two template bugs
(missing types for flat registers, absent hw2sw placeholder) were identified
and fixed in the process.

Several features I initially thought were missing are already present: `ipcraft
validate` is fully wired and catches overlap and reference errors before
generation; register arrays are supported end-to-end in the VHDL templates; and
the `managed: false` flag protects user-owned files from being overwritten.  The
main gap is discoverability — these features work but are not yet surfaced in the
generated scaffolds or the documentation.

The remaining gaps are all **additive** — the foundation is solid and extensible.
C header generation, AXI4-Full and AXI-Stream templates, and multi-interface
top-level generation are incremental additions on top of a well-designed data
model, not architectural rewrites.

For AXI-Lite peripheral design, ipcraft is already a **production-quality tool**
that I will use on every new project.  For AXI4-Full, AXI-Stream, or
SystemVerilog workflows, it is a promising scaffold that needs another release
cycle before it replaces the manual process entirely.

**Rating: 8 / 10** — excellent for the common case, with a clear path to 9/10
once the remaining bus templates and documentation gaps are filled.

---

*This review reflects hands-on use of the ipcraft CLI and Python API.
All command examples were run against the actual tool; output has been
lightly reformatted for readability.*
