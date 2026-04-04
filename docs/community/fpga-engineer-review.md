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
  lives in the data model and the CLI honours it.  **Verified end-to-end** —
  see the [Managed Flag Verification](#managed-flag-verification) section below.

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

## Managed Flag Verification

Every behaviour described above was verified with a live `managed_test` IP core
using GHDL 6.0.0-dev and ipcraft from source.  A bug was discovered and fixed
during this process (see note below).

### Test setup

```bash
ipcraft new managed_test --vendor test.com --library test \
    --version 1.0.0 --bus AXI4L --output /tmp/managed_test/managed_test
ipcraft generate managed_test.ip.yml --output /tmp/managed_test/out \
    --vendor both --testbench --regs
```

After the first `generate`, the ip.yml contains:

```yaml
fileSets:
  - name: RTL_Sources
    files:
      - path: rtl/managed_test_pkg.vhd
        type: vhdl
      - path: rtl/managed_test_core.vhd
        type: vhdl
        managed: false          # auto-set by ipcraft generate
      - path: rtl/managed_test_axil.vhd
        type: vhdl
      ...
```

### Test 1 — Auto-protection of `_core.vhd`

Append `-- SENTINEL_UNMANAGED` to `managed_test_core.vhd` and
`-- SENTINEL_MANAGED` to `managed_test_pkg.vhd`, then re-run generate:

```
  Written: rtl/managed_test_pkg.vhd
  Written: rtl/managed_test.vhd
  Skipped (unmanaged): rtl/managed_test_core.vhd   ← protected
  Written: rtl/managed_test_axil.vhd
  ...
```

**Result:** `_core.vhd` sentinel preserved; `_pkg.vhd` sentinel erased. ✅

### Test 2 — Manual `managed: false` on any file

Add `managed: false` to the `_axil.vhd` entry, append a sentinel, re-run:

```
  Written: rtl/managed_test_pkg.vhd
  Written: rtl/managed_test.vhd
  Skipped (unmanaged): rtl/managed_test_core.vhd
  Skipped (unmanaged): rtl/managed_test_axil.vhd   ← also protected
  ...
```

**Result:** Both `managed: false` files preserved. ✅

### Test 3 — Absent unmanaged file is created on first run

Delete `managed_test_core.vhd` and re-run generate:

```
  Written: rtl/managed_test_core.vhd   ← created because it did not exist
  Skipped (unmanaged): rtl/managed_test_axil.vhd
  ...
```

**Result:** Absent `managed: false` files are created, not silently skipped. ✅

### Bug found and fixed

During testing the protection did **not** work on the first attempt.
Investigation showed that `fileset_parser.py → _parse_files()` only read
`path`, `type`, and `description` from each YAML file entry — the `managed` key
was silently ignored.  Every file was therefore parsed with the default
`managed=True`, so all files were overwritten.

**Fix:** `_parse_files()` now also reads `managed`, `is_include_file`, and
`logical_name` from the YAML entry.  The fix is a two-line addition to
`ipcraft/parser/yaml/fileset_parser.py`.

All 142 existing tests continue to pass after the fix.

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

## Expert Review Addendum

**Reviewer:** Second-pass code-level review by FPGA design and verification engineer
(Altera/Xilinx toolchain, formal verification background)

**Scope:** Full codebase analysis of `model/`, `generator/`, `driver/`, `runtime/`,
`cli.py`, and all Jinja2 templates.  142 passing tests confirmed.  Findings are
organised into critical bugs, important improvements, and new proposals.

### Codebase Architecture Assessment

The layered architecture is clean and well-separated:

```
model/      (Pydantic data models -- single source of truth)
parser/     (YAML / VHDL -> IpCore model)
generator/  (IpCore model -> VHDL / XML / TCL via Jinja2)
driver/     (IpCore model -> runtime Cocotb driver)
cli.py      (User interface)
```

The separation between `model/memory_map.py` (Pydantic definitions with `*Def`
suffix) and `runtime/register.py` (runtime accessor objects) is a smart design
decision.  It keeps schema validation clean and avoids Cocotb dependencies in the
model layer.

| Area | Rating | Notes |
|------|--------|-------|
| Model layer (`model/`) | 9/10 | Clean Pydantic models, good validation, proper type hints |
| Generator (`generator/hdl/`) | 7/10 | Works well but has design concerns listed below |
| Templates (`.j2`) | 7/10 | Functionally correct VHDL, some synthesizability concerns |
| CLI (`cli.py`) | 8/10 | Clean argparse, good JSON mode, proper error handling |
| Driver (`driver/`) | 8/10 | Elegant `load_driver()` from YAML, good async support |
| Tests | 8/10 | 142 passing, 37 skipped worth investigating |
| Validators (`validators.py`) | 8/10 | Comprehensive overlap, alignment, reference checks |

---

### Critical Bugs

These must be fixed before the next release.  All are localised template or
generator changes with no architectural impact.

#### ~~BUG-1: `write-1-to-clear` is modeled but not implemented in the register file~~ ✅ **Done**

**File:** `ipcraft/generator/hdl/templates/register_file.vhdl.j2` (write process,
line ~96)

The write process in `register_file.vhdl.j2` handles `read-write` and
`read-only` access types in the `case` statement, but there is no `write-1-to-clear`
arm.  For W1C, the write process must clear only the bits that software writes as
`'1'`, not overwrite the register:

```vhdl
-- Current (wrong for W1C): overwrites the field
regs.status <= to_status(v_wdata);

-- Correct W1C behaviour: clear bits where software writes '1'
regs.status.overflow <= regs.status.overflow and not v_wdata(1);
```

The model layer (`AccessType.WRITE_1_TO_CLEAR`) and the Cocotb driver both
handle W1C correctly.  The mismatch means simulation may show correct behaviour
(the driver knows W1C semantics) while the actual hardware does not implement
them.

**Impact:** Safety-critical for interrupt status registers.  A hardware interrupt
flag that does not clear on W1C will cause interrupt storms.

**Fix details:** See [TASK-01](#task-01--implement-w1c-in-register-file-template)
below.

---

#### ~~BUG-2: `reg_addr()` function returns wrong addresses for sparse register maps~~ ✅ **Done**

**File:** `ipcraft/generator/hdl/templates/package.vhdl.j2` (line ~165)

```vhdl
function reg_addr(reg : t_reg_id) return natural is
begin
  return t_reg_id'pos(reg) * C_REG_WIDTH;
end function;
```

This assumes contiguous registers with no gaps.  If a user defines registers at
offsets `0x00`, `0x04`, `0x10` (skipping `0x08` and `0x0C`), the function returns
`0x00`, `0x04`, `0x08` -- wrong for the third register.

The register file's `case` statement uses `to_integer(unsigned(addr))` from the
actual bus address, so read/write *decoding* works correctly.  But any user code
that calls `reg_addr(REG_STATUS)` from the package will get an incorrect offset.

**Fix details:** See [TASK-02](#task-02--fix-reg_addr-for-sparse-address-maps)
below.

---

#### ~~BUG-3: Hard-coded `s_axi_` prefix in AXI-Lite output signal assignments~~ ✅ **Done**

**File:** `ipcraft/generator/hdl/templates/bus_axil.vhdl.j2` (lines ~99-117)

The output port assignments use hard-coded `s_axi_` prefixes:

```jinja
{% if port.logical_name == 'AWREADY' %}
  s_axi_awready <= axi_awready;
```

But the entity port declarations above correctly use `{{ port.name }}` (which
respects the configured `physical_prefix`).  If a user sets `physical_prefix:
s_ctrl_`, the entity will declare `s_ctrl_awready` but the architecture will
try to drive `s_axi_awready` -- a compilation error.

**Fix details:** See [TASK-03](#task-03--use-template-variable-for-bus-port-prefix)
below.

---

### Important Improvements

#### ~~IMP-1: Mixed access-type string comparisons in the generator~~ ✅ **Done**

**File:** `ipcraft/generator/hdl/ipcore_project_generator.py` (line ~200)

```python
_ro_accesses = {"read-only", "ro", "write-1-to-clear", "rw1c", "w1c"}
```

This duplicates normalisation already handled by `AccessType.from_string()`.
Use enum comparisons instead of string sets to avoid drift.

**Fix:** Replace raw string checks with:

```python
from ipcraft.model.memory_map import AccessType

access = AccessType.from_string(enum_value(f.access))
is_hw_driven = access in {AccessType.READ_ONLY, AccessType.WRITE_1_TO_CLEAR}
```

---

#### ~~IMP-2: Address width is hard-coded to 8~~ ✅ **Done**

**File:** `ipcraft/generator/hdl/ipcore_project_generator.py` (line ~419)

```python
"addr_width": 8,
```

`C_ADDR_WIDTH` should be auto-calculated from the maximum register offset:

```python
max_offset = max((r["offset"] + 4) for r in registers) if registers else 16
addr_width = max(max_offset.bit_length(), 4)  # minimum 4 bits
```

A hard-coded `8` silently limits the address space to 256 bytes (64 registers).
Users with larger register maps will get incorrect decode logic.

---

#### ~~IMP-3: Missing `WSTRB` default when port is absent~~ ✅ **Done**

**Files:** `bus_axil.vhdl.j2`, `register_file.vhdl.j2`

If `WSTRB` is not included as an optional port, the register file's `wr_strb`
input is left undriven.  The bus wrapper should default to all-ones:

```vhdl
wr_strb <= s_axi_wstrb when HAS_WSTRB else (others => '1');
```

Or the template should conditionally omit `wr_strb` from the port map and
hard-wire it inside the register file.

---

#### ~~IMP-4: pyparsing deprecation warnings~~ ✅ **Done**

**File:** `ipcraft/parser/hdl/vhdl_parser.py` (lines 72, 79, 86)

The VHDL parser uses deprecated pyparsing APIs (`oneOf`, `nestedExpr`).  Migrate
to `one_of` and `nested_expr` to suppress warnings and ensure forward
compatibility with pyparsing >= 3.2.

---

#### ~~IMP-5: 37 skipped tests uninvestigated~~ ✅ **Done**

The test suite reports `142 passed, 37 skipped`.  Skipped tests may mask
regressions.  Each skipped test should either have a documented reason (missing
simulator, platform-specific) or be converted to `xfail` with a ticket reference.

---

### New Improvement Proposals

These extend the original P0/P1 wishlist based on the codebase analysis.

#### PROP-1: AXI4-Lite Formal Verification Property File

Generate a `.psl` or SystemVerilog assertion file alongside the bus wrapper
containing AXI4 protocol compliance properties:

- `AWREADY` must not assert without `AWVALID`
- `RDATA` must be stable while `RVALID` and not `RREADY`
- `BRESP` must be `OKAY` for successful writes
- No channel may starve indefinitely (liveness)

This would make ipcraft the only register generator that ships with formal
verification hooks.  The implementation is a new `formal_axil.psl.j2` template.

---

#### PROP-2: Register Documentation Generation (Markdown/HTML)

Add a `regmap_docs.md.j2` template producing a human-readable register map:

- Address table with name, offset, access type, reset value
- Per-register bit-field table
- Auto-generated from the same `mm.yml` used for VHDL

This is zero-effort for the user and solves the perennial documentation-drift
problem.  Consider also adding `--format html` using a second template.

---

#### PROP-3: First-Class Interrupt Support

Add interrupt modeling to the memory map schema:

```yaml
interrupts:
  - name: IRQ
    statusRegister: INT_STATUS    # W1C register
    enableRegister: INT_ENABLE    # RW register
    output: o_irq                 # active-high output
```

The generator would emit:
- `INT_STATUS` (W1C) and `INT_ENABLE` (RW) registers
- `o_irq <= '1' when (int_status and int_enable) /= x"0" else '0';`
- Corresponding entries in the Cocotb testbench

This is the single most requested feature in every IP register tool.

---

#### PROP-4: WSTRB-Aware Sub-Byte Field Masking

The current `apply_wstrb` works at byte granularity.  For sub-byte fields (e.g.,
a 2-bit MODE field at bits [2:1]), a write with full WSTRB overwrites all 8 bits
of the byte, potentially corrupting adjacent fields in the same byte.

The fix is to generate a per-field mask in the write process so that only defined
field bits are updated on write.  This matches the behaviour of Xilinx AXI GPIO
and AXI Timer IPs.

---

#### PROP-5: Change Impact Analysis CLI

Add `ipcraft diff old.ip.yml new.ip.yml` that compares two versions and reports:

- Registers added/removed/modified
- Address changes
- Field width or access-type changes
- Which generated files would be affected

Essential for CI/CD pipelines managing IP repositories.  The original review
listed this as P1; based on codebase analysis, the data model already contains
everything needed to implement this as a model-level diff.

---

## Developer Task Backlog

Actionable tasks derived from both the original review and the expert addendum.
Each task includes file references, implementation guidance, and a verification
method.

### ~~TASK-01 -- Implement W1C in register file template~~ ✅ **Done**

**Priority:** Critical
**Files:**
- `ipcraft/generator/hdl/templates/register_file.vhdl.j2`
- `ipcraft/generator/hdl/ipcore_project_generator.py`

**Implementation:**

1. In `_prepare_registers()`, propagate a `w1c_fields` list to the template
   context for each register.  A field is W1C if its access type normalises to
   `AccessType.WRITE_1_TO_CLEAR` or `AccessType.READ_WRITE_1_TO_CLEAR`.

2. In `register_file.vhdl.j2`, add a W1C branch in the write `case` statement:

```jinja
{% if reg.w1c_fields %}
          when t_reg_id'pos(REG_{{ reg.name | upper }}) =>
            -- Write-1-to-clear: clear bits where software writes '1'
{% for field in reg.w1c_fields %}
{% if field.width == 1 %}
            regs.{{ reg.name | lower }}.{{ field.name | lower }} <=
              regs.{{ reg.name | lower }}.{{ field.name | lower }} and not wr_data({{ field.offset }});
{% else %}
            regs.{{ reg.name | lower }}.{{ field.name | lower }} <=
              regs.{{ reg.name | lower }}.{{ field.name | lower }}
              and not wr_data({{ field.offset + field.width - 1 }} downto {{ field.offset }});
{% endif %}
{% endfor %}
{% endif %}
```

3. For mixed registers (some fields RW, some W1C), generate per-field handling
   within the same `when` arm.  The RW fields use `apply_wstrb`; the W1C fields
   use the AND-NOT pattern above.

4. W1C registers also need a hardware *set* path.  Add a `hw_set` input to the
   register file so that hardware can assert status bits:

```vhdl
-- In the write process, after the case statement:
-- Hardware set has priority over software clear
{% for reg in registers %}
{% if reg.w1c_fields %}
{% for field in reg.w1c_fields %}
if regs_in.{{ reg.name | lower }}.{{ field.name | lower }} = '1' then
  regs.{{ reg.name | lower }}.{{ field.name | lower }} <= '1';
end if;
{% endfor %}
{% endif %}
{% endfor %}
```

**Verification:**
- Add a unit test with a W1C STATUS register
- Write `0xFF` to the register; read back should show `0xFF`
- Write `0x02` (W1C bit 1); read back should show `0xFD`
- Hardware sets bit 1 again; read back should show `0xFF`

---

### ~~TASK-02 -- Fix `reg_addr()` for sparse address maps~~ ✅ **Done**

**Priority:** Critical
**File:** `ipcraft/generator/hdl/templates/package.vhdl.j2`

**Implementation:**

Replace the linear calculation with a lookup:

```jinja
  function reg_addr(reg : t_reg_id) return natural is
  begin
    case reg is
{% for reg in registers %}
{% if reg.is_array %}
{% for i in range(reg.count) %}
      when REG_{{ reg.name | upper }}_{{ i }} => return {{ reg.offset + (i * reg.stride) }};
{% endfor %}
{% else %}
      when REG_{{ reg.name | upper }} => return {{ reg.offset }};
{% endif %}
{% endfor %}
    end case;
  end function;
```

This handles both contiguous and sparse register maps correctly.

**Verification:**
- Create a test IP with registers at offsets `0x00`, `0x04`, `0x10`, `0x20`
- Compile the generated package
- Assert that `reg_addr(REG_STATUS)` returns `0x10` (not `0x08`)

---

### ~~TASK-03 -- Use template variable for bus port prefix~~ ✅ **Done**

**Priority:** Critical
**File:** `ipcraft/generator/hdl/templates/bus_axil.vhdl.j2`

**Implementation:**

Replace all hard-coded `s_axi_*` references in the output assignments
(lines ~99-117) with `{{ port.name }}`:

```jinja
  -- Connect internal AXI signals to ports
{% for port in bus_ports %}
{% if port.direction == 'out' %}
  {{ port.name }} <= axi_{{ port.logical_name | lower }};
{% endif %}
{% endfor %}
```

And for input references in process bodies, replace `s_axi_awvalid` with a
template-generated signal name.  The cleanest approach is to generate
`signal` aliases at the top of the architecture:

```jinja
  -- Alias bus port names to internal signals
{% for port in bus_ports %}
{% if port.direction == 'in' %}
  alias {{ port.logical_name | lower }}_i : {{ port.type }} is {{ port.name }};
{% endif %}
{% endfor %}
```

Then use `awvalid_i`, `wvalid_i`, etc. throughout the process bodies.

**Verification:**
- Create a test IP with `physical_prefix: s_ctrl_`
- Run `ipcraft generate`
- Compile the generated VHDL -- must succeed without unresolved signals

---

### ~~TASK-04 -- Auto-calculate `C_ADDR_WIDTH`~~ ✅ **Done**

**Priority:** Important
**File:** `ipcraft/generator/hdl/ipcore_project_generator.py`

**Implementation:**

In `_get_template_context()`, replace:

```python
"addr_width": 8,
```

With:

```python
max_addr = max((r["offset"] + 4) for r in registers) if registers else 16
addr_width = max(max_addr.bit_length(), 4)
```

Update `C_ADDR_WIDTH` in `package.vhdl.j2` to use this value.  Also update
`xilinx_component_xml.j2` and `intel_hw_tcl.j2` if they reference address width.

**Verification:**
- Create an IP with 128 registers (offset up to `0x1FC`)
- Verify `C_ADDR_WIDTH` is generated as 9 (not 8)
- Compile and simulate

---

### ~~TASK-05 -- Normalise access-type comparisons in generator~~ ✅ **Done**

**Priority:** Important
**File:** `ipcraft/generator/hdl/ipcore_project_generator.py`

**Implementation:**

Replace all raw string sets like:

```python
_ro_accesses = {"read-only", "ro", "write-1-to-clear", "rw1c", "w1c"}
```

With enum-based comparisons:

```python
from ipcraft.model.memory_map import AccessType

def _is_hw_driven(access_str: str) -> bool:
    access = AccessType.from_string(access_str)
    return access in {AccessType.READ_ONLY, AccessType.WRITE_1_TO_CLEAR,
                      AccessType.READ_WRITE_1_TO_CLEAR}
```

Apply the same pattern to `sw_access` / `hw_access` filter lists in
`_get_template_context()`.

**Verification:**
- Existing tests must pass
- Add a test with `access: rw1c` and verify it is classified as hw-driven

---

### TASK-06 -- C/C++ register header template

**Priority:** P0
**Files (new):**
- `ipcraft/generator/hdl/templates/c_header.h.j2`
- Add generation call in `ipcore_project_generator.py`

**Implementation:**

Create `c_header.h.j2`:

```c
/* {{ entity_name | upper }}_REGS.h
 * Generated by ipcraft -- DO NOT EDIT
 */
#ifndef {{ entity_name | upper }}_REGS_H
#define {{ entity_name | upper }}_REGS_H

#include <stdint.h>

/* Base address (set by SoC integration) */
#ifndef {{ entity_name | upper }}_BASE
#define {{ entity_name | upper }}_BASE 0x00000000UL
#endif

/* Register offsets */
{% for reg in registers %}
#define {{ entity_name | upper }}_{{ reg.name | upper }}_OFFSET  0x{{ "%04X" | format(reg.offset) }}UL
{% endfor %}

/* Field masks and shifts */
{% for reg in registers %}
{% for field in reg.fields %}
#define {{ entity_name | upper }}_{{ reg.name | upper }}_{{ field.name | upper }}_SHIFT  {{ field.offset }}
#define {{ entity_name | upper }}_{{ reg.name | upper }}_{{ field.name | upper }}_MASK   0x{{ "%08X" | format(((1 << field.width) - 1) << field.offset) }}UL
#define {{ entity_name | upper }}_{{ reg.name | upper }}_{{ field.name | upper }}_WIDTH  {{ field.width }}
{% endfor %}
{% endfor %}

/* Accessor macros */
#define {{ entity_name | upper }}_READ(reg) \
    (*(volatile uint32_t *)({{ entity_name | upper }}_BASE + {{ entity_name | upper }}_##reg##_OFFSET))

#define {{ entity_name | upper }}_WRITE(reg, val) \
    (*(volatile uint32_t *)({{ entity_name | upper }}_BASE + {{ entity_name | upper }}_##reg##_OFFSET) = (val))

#define {{ entity_name | upper }}_READ_FIELD(reg, field) \
    (({{ entity_name | upper }}_READ(reg) & {{ entity_name | upper }}_##reg##_##field##_MASK) \
     >> {{ entity_name | upper }}_##reg##_##field##_SHIFT)

#define {{ entity_name | upper }}_WRITE_FIELD(reg, field, val) \
    {{ entity_name | upper }}_WRITE(reg, \
        ({{ entity_name | upper }}_READ(reg) & ~{{ entity_name | upper }}_##reg##_##field##_MASK) \
        | (((val) << {{ entity_name | upper }}_##reg##_##field##_SHIFT) \
           & {{ entity_name | upper }}_##reg##_##field##_MASK))

#endif /* {{ entity_name | upper }}_REGS_H */
```

Wire into `generate_all_with_structure()`:

```python
if include_regs:
    files[f"sw/{name}_regs.h"] = self.generate_c_header(ip_core)
```

Add `--c-header` / `--no-c-header` CLI flags.

**Verification:**
- Generate for the PWM core example
- Compile with `gcc -fsyntax-only -Wall pwm_core_regs.h`
- Verify offsets match the VHDL package constants

---

### ~~TASK-07 -- Register map documentation template~~ ✅ **Done**

**Priority:** P0
**File (new):** `ipcraft/generator/hdl/templates/regmap_docs.md.j2`

**Implementation:**

Generate a Markdown document with:

1. Title and description from `ip.yml`
2. Register summary table (offset, name, access, reset value)
3. Per-register detail sections with bit-field tables

Example output structure:

```markdown
# PWM Core Register Map

| Offset | Name   | Access | Reset      | Description             |
|--------|--------|--------|------------|-------------------------|
| 0x0000 | CTRL   | RW     | 0x00000000 | Control register        |
| 0x0004 | PERIOD | RW     | 0x000003FF | PWM period in clk cycles|

## CTRL (0x0000)

| Bits  | Name   | Access | Reset | Description          |
|-------|--------|--------|-------|----------------------|
| [0]   | ENABLE | RW     | 0     | Enable PWM output    |
| [2:1] | MODE   | RW     | 0     | 0=single, 1=cont ... |
```

Wire into `generate_all_with_structure()` alongside the testbench.

**Verification:**
- Generate for PWM core
- Verify the Markdown renders correctly
- Cross-check offsets against generated VHDL package

---

### ~~TASK-08 -- Migrate pyparsing deprecated APIs~~ ✅ **Done**

**Priority:** Important
**File:** `ipcraft/parser/hdl/vhdl_parser.py`

**Implementation:**

| Old API | New API |
|---------|---------|
| `oneOf(...)` | `one_of(...)` |
| `nestedExpr()` | `nested_expr()` |

These are drop-in replacements.  Update imports and call sites at lines 72, 79,
86.

**Verification:**
- Run `pytest ipcraft/tests/parser/` with `-W error::DeprecationWarning`
- All parser tests must pass with zero warnings

---

### ~~TASK-09 -- Investigate and document skipped tests~~ ✅ **Done**

**Priority:** Important
**File:** Various test files

**Implementation:**

Run `pytest --co -q` to list all collected tests.  For each skipped test:

1. If skipped due to missing simulator (GHDL, Icarus): add
   `@pytest.mark.skipif(reason="requires GHDL")` with documentation
2. If skipped due to incomplete feature: convert to `@pytest.mark.xfail`
   with a ticket reference
3. If skipped for no clear reason: investigate and either fix or remove

**Verification:**
- `pytest -v` output should show no unexplained skips
- Each skip reason should be documented in a comment or marker

---

### Task Priority Matrix

| Task | Priority | Effort | Risk if Deferred |
|------|----------|--------|------------------|
| TASK-01: W1C implementation | Critical | Medium (template + test) | Incorrect interrupt handling in hardware |
| TASK-02: Sparse `reg_addr()` | Critical | Low (template only) | User code with wrong addresses |
| TASK-03: Bus prefix variable | Critical | Low (template only) | Compile failure for non-default prefix |
| TASK-04: Auto addr width | Important | Low (generator) | Silent address space limitation |
| TASK-05: Enum access types | Important | Low (generator) | Future access-type bugs |
| TASK-06: C header template | P0 | Medium (new template) | Manual drift for firmware teams |
| TASK-07: Register docs | P0 | Low (new template) | Documentation drift |
| TASK-08: pyparsing migration | Important | Low (3 line changes) | Future breakage |
| TASK-09: Skipped tests | Important | Low (investigation) | Hidden regressions |

---

*This review reflects hands-on use of the ipcraft CLI and Python API.
All command examples were run against the actual tool; output has been
lightly reformatted for readability.  The expert addendum is based on
static analysis of the full codebase and confirmed against 142 passing
unit tests.*

---

## Second Expert Review Addendum

**Reviewer:** Third-pass deep-dive by senior FPGA design and verification engineer
(15 years Altera/Xilinx toolchain, AXI protocol formal verification background)

**Scope:** Full template-level code review of all `.j2` files, generator Python, and
cross-layer consistency checks.  The previous addendum's tasks are confirmed done.
This pass focuses on newly discovered issues and opportunities.

---

### What Has Been Done Well (Confirmed)

The previous two review rounds surfaced real problems and the fixes are solid:

- **W1C register file template (TASK-01):** The `w1c_fields` context and dual-assignment
  pattern are correctly wired.  The hardware-set priority-over-software-clear logic
  outside the `case` statement is the right architectural choice.
- **Sparse `reg_addr()` (TASK-02):** The lookup-table approach using a `case` statement
  is exactly right — it is both correct and synthesisable.  The old positional multiply
  was a latent correctness bug waiting to bite anyone with a sparse map.
- **Bus prefix aliases (TASK-03):** The `alias` approach in `bus_axil.vhdl.j2` is
  idiomatic VHDL 2008 and eliminates the hard-coded `s_axi_` prefix cleanly.
- **Auto `C_ADDR_WIDTH` (TASK-04):** The `max_addr.bit_length()` calculation in
  `ipcore_project_generator.py` is correct and handles arrays via `stride × count`.
- **Access-type enum normalisation (TASK-05):** The `AccessType.normalize()` path
  replaces brittle string sets.  This is the right fix.
- **Register docs template (TASK-07):** `regmap_docs.md.j2` exists and produces a
  proper bit-field table.  Zero-effort documentation from the same YAML is a standout
  feature.
- **VHDL-2008 in the cocotb Makefile:** `--std=08` and `-frelaxed` are both set,
  which is required for VHDL 2008 record sub-element assignments used in the register
  file.  Good.
- **`managed: false` auto-protection:** `_core.vhd` is correctly scaffolded as
  unmanaged.  The fileset parser bug fix (reading `managed` from YAML) is confirmed.

---

### Newly Discovered Bugs

#### ~~BUG-A: Jinja2 Variable Scoping — `has_wstrb` Always `false`~~ ✅ **Done**

**File:** `ipcraft/generator/hdl/templates/bus_axil.vhdl.j2` (lines ~174–185)

**Severity: High — silent functional error**

```jinja
{% set has_wstrb = false %}
{% for port in bus_ports %}
{% if port.logical_name == 'WSTRB' %}
{% set has_wstrb = true %}   {# ← This does NOT escape the for-loop scope in Jinja2 #}
{% endif %}
{% endfor %}
  wr_strb <= wstrb_i;          {# ← This branch is NEVER reached #}
```

Jinja2 uses block-scoped `set`.  A `{% set %}` inside a `{% for %}` block does not
propagate to the outer scope.  `has_wstrb` is therefore always `false` after the loop,
so `wr_strb` is unconditionally driven with `(others => '1')`.

**Consequence:** The WSTRB port is declared in the entity (if the bus definition
includes it), connected via `alias wstrb_i`, but the alias is never used.  Byte-enable
partial writes are silently ignored — the full 32-bit word is always written.  For
firmware using `memcpy`-style accesses with non-aligned WSTRB patterns this is a
data corruption hazard.

**Fix — Option A (preferred, no Python change):**

Use the Jinja2 `namespace()` idiom, the standard workaround for this scoping rule:

```jinja
{% set ns = namespace(has_wstrb=false) %}
{% for port in bus_ports %}
{% if port.logical_name == 'WSTRB' %}
{% set ns.has_wstrb = true %}
{% endif %}
{% endfor %}
{% if ns.has_wstrb %}
  wr_strb <= wstrb_i;
{% else %}
  wr_strb <= (others => '1');
{% endif %}
```

**Fix — Option B (cleaner, Python-side):**

Pre-compute `has_wstrb` in `_get_template_context()` and pass it directly:

```python
"has_wstrb": any(p["logical_name"] == "WSTRB" for p in bus_ports),
```

Then the template becomes a simple `{% if has_wstrb %}`.  This moves logic out of
templates and into testable Python — the better long-term approach.

**Verification:**
- Generate a core with an AXI-Lite bus that includes WSTRB
- Confirm `wr_strb <= wstrb_i;` appears in the generated `_axil.vhd`
- Write `0x01` to a 32-bit register with `wstrb = 0x01`; verify only byte 0 is updated

---

#### ~~BUG-B: W1C Registers Excluded from `t_regs_sw2hw` in `package.vhdl.j2`~~ ✅ **Done**

**File:** `ipcraft/generator/hdl/templates/package.vhdl.j2` (lines 90–91)

**Severity: High — compile error for any pure-W1C register**

```jinja
{% set sw2hw_regs = registers | selectattr('access', 'in',
    ['read-write', 'write-only', 'rw', 'wo']) | list %}
{% set hw2sw_regs = registers | selectattr('access', 'in',
    ['read-only', 'ro']) | list %}
```

A register whose *top-level* `access` is `write-1-to-clear` (or `rw1c`, `w1c`) matches
**neither** filter.  It receives no record-type declaration.  The register file
template's write `case` statement (line 96) does match it and tries to assign to
`regs.status`, but `t_regs_sw2hw` has no `status` field — this is a compile error.

The generator in `ipcore_project_generator.py` (line 213) already computes `is_hw2sw`
correctly via `AccessType.normalize()`, but the package template ignores this flag and
re-derives membership from raw strings.

**Impact:**
- A register map where `STATUS` has top-level `access: write-1-to-clear` (rather than
  field-level access on sub-fields) produces uncompilable VHDL.
- With field-level W1C, the parent register's access is usually `read-write` or absent,
  so the bug does not surface in simple examples.  It lurks until a user writes a
  flat W1C register (e.g., a 32-bit interrupt-status word with no named sub-fields).

**Fix:**

Replace the string-literal filters with the generator-computed `hw2sw` flag AND extend
`sw2hw_regs` to include W1C registers (since the register file stores their value):

```jinja
{# Registers where SW writes (control + W1C) → stored in register file, output to core #}
{% set sw2hw_regs = registers | selectattr('access', 'in',
    ['read-write', 'write-only', 'rw', 'wo',
     'write-1-to-clear', 'rw1c', 'w1c',
     'read-write-1-to-clear']) | list %}

{# Registers where HW writes (status + W1C) → hardware drives the value #}
{% set hw2sw_regs = registers | selectattr('hw2sw', 'equalto', true) | list %}
```

The `hw2sw` key is already populated in each register dict by the generator.
This also removes the string-duplication problem that IMP-1 / TASK-05 targeted.

**Verification:**
- Create a register map with a flat `access: write-1-to-clear` register (no sub-fields)
- Run `ipcraft generate` and confirm the package compiles without errors
- Verify the register appears in `t_regs_sw2hw` in the package
- Write 0xFF, read 0xFF; write 0x02 (W1C), read 0xFD

---

#### ~~BUG-C: Stale Linear Addressing in `bus_axil.vhdl.j2` Header Comment~~ ✅ **Done**

**File:** `ipcraft/generator/hdl/templates/bus_axil.vhdl.j2` (lines ~6–8)

**Severity: Low — cosmetic, but confusing**

```jinja
{% for reg in registers %}
--   {{ "0x%04X" | format(loop.index0 * reg_width) }} : {{ reg.name }} ({{ reg.access }})
{% endfor %}
```

`loop.index0 * reg_width` is the old sequential addressing.  After TASK-02 fixed the
`reg_addr()` function and VHDL package, this banner comment still shows wrong addresses
for sparse maps.  A developer reading the generated file would see a comment that
contradicts the actual register file.

**Fix:**

```jinja
{% for reg in registers %}
{% if reg.is_array %}
{% for i in range(reg.count) %}
--   0x{{ '%04X' | format(reg.offset + i * reg.stride) }} : {{ reg.name | upper }}_{{ i }} ({{ reg.access }})
{% endfor %}
{% else %}
--   0x{{ '%04X' | format(reg.offset) }} : {{ reg.name | upper }} ({{ reg.access }})
{% endif %}
{% endfor %}
```

---

### Important Improvements

#### ~~IMP-A: W1C Dual-Assignment Synthesis Concern~~ ✅ **Done**

**File:** `ipcraft/generator/hdl/templates/register_file.vhdl.j2` (write process)

The current W1C write pattern makes two sequential signal assignments to the same record
in the same process:

```vhdl
regs.status <= to_status(v_wdata);                          -- (1) whole-record assign
regs.status.overflow <= regs.status.overflow and not wr_data(1);  -- (2) field override
```

Per IEEE Std 1076-2008 §8.5, the last assignment to any given sub-element wins.
Assignment (2) is to a *sub-element* of `regs.status` and takes precedence for that
bit.  This is correct in simulation and in VHDL-2008-compliant synthesis tools.

However, Synopsys DC and older Quartus versions may emit "multiple drivers" or
"last assignment wins" warnings for this pattern, and some linting tools (SpyGlass,
Ascent Lint) will flag it as a rule violation even though it is LRM-correct.

**Recommended fix — variable-based approach:**

```vhdl
when t_reg_id'pos(REG_STATUS) =>
  v_wdata := apply_wstrb(to_slv(regs.status), wr_data, wr_strb);
  v_reg   := to_status(v_wdata);
  -- Override W1C fields: clear bits where SW writes '1'
  v_reg.overflow := regs.status.overflow and not wr_data(1);
  regs.status <= v_reg;  -- single assignment
```

This makes one assignment per register, is lint-clean, and synthesises identically.
Requires a per-register variable declaration (`v_reg`) in the process declarative
region — the template can generate this.

---

#### ~~IMP-B: `cocotb_makefile.j2` PYTHONPATH Hard-Codes Four Directory Levels~~ ✅ **Done**

**File:** `ipcraft/generator/hdl/templates/cocotb_makefile.j2` (line ~61)

```makefile
export PYTHONPATH := $(shell cd $(CURDIR)/../../../.. && pwd):$(PYTHONPATH)
```

This path walks four levels up: `tb/ → <name>/ → <project>/ → <workspace>/`.  It
matches the layout of the ipcraft examples directory but breaks for any other project
structure.  The original review noted this; the fix was not yet applied.

**Better approaches (in priority order):**

1. **Detect installed package first:** `python -c "import ipcraft" 2>/dev/null && echo
   "installed"`.  If importable, no PYTHONPATH needed.
2. **Environment variable override:** `IPCRAFT_ROOT ?= $(shell cd ... && pwd)` with a
   clear comment telling the user to override it.
3. **Pass path from generator:** `ipcore_project_generator.py` knows where it lives;
   it can inject the correct absolute path into the template context.

Option 3 is the cleanest because it eliminates the hard-coded level count entirely.

---

#### ~~IMP-C: Cocotb Testbench Uses `dir()` for Register Discovery~~ ✅ **Done**

**File:** `ipcraft/generator/hdl/templates/cocotb_test.py.j2`

```python
for block_name in dir(driver):
    if block_name.startswith('_'):
        continue
```

`dir()` returns all attributes, including methods, properties, and dunder-adjacent
names that don't start with `_`.  This is fragile and will spuriously iterate over any
public method or class attribute added to the driver in the future.

The `ipcraft.driver` module's `load_driver()` returns an object wrapping address
blocks.  The driver should expose a `_blocks` or `__registers__` iterable that the
generated testbench iterates instead of relying on `dir()`.  This is a driver API
improvement, but the testbench template should be updated in parallel.

---

#### ~~IMP-D: `top.vhdl.j2` Indentation Inconsistency~~ ✅ **Done**

**File:** `ipcraft/generator/hdl/templates/top.vhdl.j2`

The architecture body mixes indentation levels: signal declarations use 2 spaces,
instantiation labels use 4 spaces, port map contents use 6 spaces.  VHDL is
whitespace-insensitive, but generated code should be consistently formatted for
readability and diff cleanliness.

Recommended: 2-space indent throughout (matching the entity template style), or
standardise on 4-space.  Either is fine; inconsistency is not.

---

### Outstanding Wishlist Items

The following items from the original P0/P1 wishlist and PROP-* proposals remain open.
They are additive features, not bugs.

| Item | Status | Priority | Notes |
|------|--------|----------|-------|
| C/C++ register header (`c_header.h.j2`) | **Open** | P0 | No template exists yet |
| AXI4-Full burst wrapper template | **Open** | P0 | Bus definition exists, no wrapper |
| Multi-interface top-level generation | **Partial** | P0 | `secondary_bus_ports` in templates, generator not fully wired |
| SystemVerilog generator (`.sv.j2`) | **Open** | P1 | Architecture supports it |
| UVM RAL model generation | **Open** | P1 | High value for verification teams |
| AXI4-Lite formal PSL properties (PROP-1) | **Open** | P1 | Would be unique in the market |
| First-class interrupt modeling (PROP-3) | **Open** | P1 | Most-requested register tool feature |
| Change impact analysis `ipcraft diff` (PROP-5) | **Open** | P1 | Data model ready |
| Interactive `new` wizard | **Open** | P2 | Quality-of-life |

---

### Updated Ratings

Incorporating fixes since the first review:

| Area | Previous | Current | Change |
|------|----------|---------|--------|
| Model layer (`model/`) | 9/10 | 9/10 | Stable |
| Generator (`generator/hdl/`) | 7/10 | 8/10 | +1 — enum normalisation, addr width |
| Templates (`.j2`) | 7/10 | 7/10 | BUG-A and BUG-B new findings hold the score |
| CLI (`cli.py`) | 8/10 | 8/10 | Stable |
| Driver (`driver/`) | 8/10 | 8/10 | IMP-C open |
| Tests | 8/10 | 9/10 | +1 — skipped tests now xfail with reasons |
| Validators | 8/10 | 8/10 | Stable |

**Overall tool rating: 8.5 / 10** — excellent for AXI-Lite register-map-centric
designs.  BUG-A (Jinja2 scoping) and BUG-B (W1C record classification) are the only
remaining blockers before I would call the VHDL output fully production-safe.

---

### New Developer Task Backlog (Round 2)

| Task | File(s) | Priority | Effort |
|------|---------|----------|--------|
| TASK-10: Fix Jinja2 `has_wstrb` scoping | `bus_axil.vhdl.j2` | Critical | Low |
| TASK-11: Fix W1C exclusion from `t_regs_sw2hw` | `package.vhdl.j2` | Critical | Low |
| TASK-12: Fix header comment addresses | `bus_axil.vhdl.j2` | Low | Trivial |
| TASK-13: Variable-based W1C write pattern | `register_file.vhdl.j2` | Important | Medium |
| TASK-14: Fix PYTHONPATH generation strategy | `cocotb_makefile.j2`, generator | Important | Low |
| TASK-15: Replace `dir()` in testbench discovery | `cocotb_test.py.j2`, driver | Important | Low |
| TASK-16: Standardise `top.vhdl.j2` indentation | `top.vhdl.j2` | Low | Trivial |
| TASK-06 (carry-over): C/C++ register header | `c_header.h.j2` (new) | P0 | Medium |
