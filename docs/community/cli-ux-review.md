# ipcraft CLI: A UX/Command-Line Experience Review

**Reviewer:** UI/UX Engineer with a focus on developer tooling and CLI design  
**Scope:** Full review of `cli.py`, `utils/diagram.py`, `--help` output, error paths, and
the overall command-line interaction model  
**Method:** Static code analysis, live invocation of all subcommands, comparison against
established CLI conventions (POSIX, GNU, 12-Factor, Google Shell Style Guide)

---

## Overview

ipcraft is a code-generation tool for hardware engineers. Its users are comfortable in
terminals, tend to run the tool from shell scripts and `Makefile` recipes, and often
integrate it into CI pipelines or IDE extensions. That context shapes every design choice
in a CLI. The good news is that the foundation is solid; the areas that need work are all
well-defined and additive.

**Overall CLI UX rating: 7 / 10**

---

## What Works Really Well

### 1. Immediate visual payoff — the ASCII diagram

Running `ipcraft new my_core --bus AXI4_LITE` prints a block diagram of the resulting IP
symbol before the user touches a single file:

```
✓ Generated ./my_core.ip.yml
✓ Generated ./my_core.mm.yml

IP Core Symbol:
    +--------------------------------------------------+
    |                     my_core                      |
    |--------------------------------------------------|
--> | s_axi_aclk                                       |
--> | s_axi_aresetn                                    |
--> | [ipcraft.busif.axi4_lite.1.0] S_AXI_LITE         |
    +--------------------------------------------------+
```

This is genuinely delightful.  The user gets instant feedback not just that the command
succeeded but *what* was created — without opening a file.  It answers the most common
post-scaffold question ("Did it pick up the right ports?") at zero cost.

### 2. Dual-mode output design

Every subcommand supports a `--json` flag that converts all output to a single JSON
object on stdout.  This is the right design pattern for a tool that must be used both by
humans and by IDE extensions.  The JSON schema is flat and predictable (`success`,
`files`, `count`, `busType`) and the error path mirrors it (`{"success": false, "error":
"…"}`).  VS Code and similar editors can consume this without fragile stdout parsing.

### 3. Sane opt-out defaults

Flags like `--testbench`, `--regs`, and `--update-yaml` default to `true` and have
explicit `--no-*` negations.  This means the typical invocation is short:

```bash
ipcraft generate my_core.ip.yml --output ./build
```

and power users who need to override have a clean path.  This follows the principle that
*the common case should be easy*.

### 4. `✓` / `✗` status glyphs

The use of `✓` for success and `✗` for failure in `validate` output is clear,
scannable, and consistent.  The file-per-line output in `generate` with `Written:` and
`Skipped (unmanaged):` labels lets the user skim the log and spot anomalies quickly.

### 5. `list-buses` as a self-service reference

`ipcraft list-buses` and `ipcraft list-buses AXI4L --ports` give the user a discoverable
reference for bus types and their port definitions without leaving the terminal.  This
removes a whole category of "what's the right port name again?" look-ups.

---

## Areas for Improvement

### 1. Silent success — `generate` is quiet by default

**Impact: High.** Running `ipcraft generate my_core.ip.yml` with no extra flags produces
no output at all while running, then prints the directory structure summary *after*
completion. On a large IP with many registers, the command may take several seconds. The
user has no indication that anything is happening.

```bash
$ ipcraft generate my_core.ip.yml   # ... nothing for 3 seconds ... then output
```

**Recommendation:** Print at least a single progress line by default (e.g., `Generating
10 files from my_core.ip.yml…`). Keep `--progress` for verbose per-file output. The
`--json` path already emits `PROGRESS:` lines when both flags are set; a non-JSON default
of one summary line would resolve this for the common terminal case.

The current `log()` helper is gated on `args.progress` — a two-line change would emit
the start and completion messages unconditionally in non-JSON mode.

---

### 2. `--no-testbench`, `--no-regs`, `--no-update-yaml` have empty help strings

**Impact: Medium.** Running `ipcraft generate --help` shows:

```
  --no-testbench
  --no-regs
  --update-yaml         Update IP core YAML with fileSets
  --no-update-yaml
```

The negation flags have no help text at all. A user encountering the help page for the
first time has no idea what `--no-testbench` disables.

```python
# current
gen_parser.add_argument("--no-testbench", dest="testbench", action="store_false")

# recommended
gen_parser.add_argument("--no-testbench", dest="testbench", action="store_false",
                        help="Skip cocotb testbench generation")
```

---

### 3. Error output goes to stdout, not stderr

**Impact: Medium.** All error messages — including full Python tracebacks — are printed
via `print()` to stdout. This breaks shell pipelines and prevents callers from separating
data from diagnostics:

```bash
# This silently discards the error message:
ipcraft generate bad_file.yml > /dev/null
echo $?   # 1, but user never saw why
```

**Recommendation:** Send all error messages and tracebacks to `sys.stderr`. This is
standard POSIX behaviour and is expected by any script or CI system wrapping ipcraft.

```python
# current
print(f"Error: {e}")
traceback.print_exc()

# recommended
print(f"Error: {e}", file=sys.stderr)
traceback.print_exc(file=sys.stderr)
```

This applies to all four command handlers (`cmd_generate`, `cmd_parse`, `cmd_validate`,
`cmd_new`).

---

### 4. Tracebacks are printed to users on any exception

**Impact: Medium.** In non-JSON mode, any exception triggers a full Python traceback to
the terminal. This is useful for developers but alarming and unhelpful for end users:

```
Error: 'NoneType' object has no attribute 'vlnv'
Traceback (most recent call last):
  File "/opt/ipcraft/ipcraft/cli.py", line 144, in cmd_generate
    ip_core = YamlIpCoreParser().parse_file(args.input)
  ...
```

**Recommendation:** Gate tracebacks behind a `--debug` or `--verbose` flag. By default,
show only a concise user-facing message with a hint:

```
✗ Error parsing my_core.ip.yml: unexpected field 'vlvn' (did you mean 'vlnv'?)
  Run with --debug for a full traceback.
```

A thin `UserError` exception class that carries a user-facing message (vs. internal
exceptions that show the traceback) would make this distinction clean.

---

### 5. `--progress` and `--json` are independent but entangled in surprising ways

**Impact: Medium.** The `log()` function's behaviour depends on the *combination* of both
flags:

| `--progress` | `--json` | Behaviour |
|:---:|:---:|---|
| ✗ | ✗ | No progress output |
| ✓ | ✗ | Plain text progress |
| ✗ | ✓ | No progress output (silent) |
| ✓ | ✓ | `PROGRESS: message` text lines mixed into stdout with the final JSON object |

The last row is the problem: `PROGRESS: Parsing IP core YAML...` is not valid JSON, so
a JSON consumer that reads stdout line-by-line will fail to parse those lines.

**Recommendation:** In `--json` mode, emit progress events as JSON Lines
(`{"type":"progress","message":"Parsing IP core YAML..."}`) so the stream is fully
machine-parseable. Alternatively, send progress to stderr when `--json` is active. The
final result object stays on stdout.

---

### 6. No `--version` flag

**Impact: Medium.** There is no `ipcraft --version`. This is expected by virtually every
command-line tool and is required for bug reports, CI logs, and dependency pinning.

```python
# In main():
parser.add_argument(
    "--version", action="version",
    version=f"%(prog)s {importlib.metadata.version('ipcraft')}"
)
```

One line addition to `argparse` setup. The package version is already defined in
`pyproject.toml`.

---

### 7. The `generate` directory structure summary is always hardcoded

**Impact: Low to Medium.** After a successful `generate`, the tool prints:

```
Directory structure for 'my_core':
  rtl/
    my_core_pkg.vhd      - Package (types, records)
    my_core.vhd          - Top-level entity
    my_core_core.vhd     - Core logic
    my_core_axil.vhd     - AXI-Lite bus wrapper
    my_core_regs.vhd     - Register bank
  tb/
    my_core_test.py      - Cocotb testbench
    Makefile             - Simulation makefile
  intel/
    ...
  xilinx/
    ...
```

This summary is **hardcoded in `cli.py`**, always listing all files regardless of what
flags were actually passed. If the user ran `--vendor none --no-testbench`, the summary
still shows `intel/`, `xilinx/`, and `tb/` directories that were never created.

**Recommendation:** Build the summary from the `written` dictionary (which is already
computed), so it reflects exactly what was written to disk:

```python
# Instead of hardcoded lines, derive from actual output:
for filepath in sorted(written):
    print(f"  {filepath}")
```

This removes the maintenance burden of keeping the summary in sync with templates and
makes it accurate for custom `--template-dir` methodologies.

---

### 8. `new` lacks `--json` output mode

**Impact: Low.** All other subcommands support `--json` for IDE integration. `new` does
not. An IDE extension that scaffolds a new IP core gets no structured response — it must
parse the human-readable output.

**Recommendation:** Add `--json` to `new_parser` and return a JSON object with the paths
of all generated files, mirroring `generate`'s response shape.

---

### 9. `--bus` on `new` accepts silently wrong values

**Impact: Low.** Running `ipcraft new my_core --bus TYPO` fails with a generic Python
exception rather than a clean error:

```
Error: Unknown bus type: TYPO
```

There is no hint about what values are valid. The `--bus` argument is a free string with
no `choices=` constraint.

**Recommendation:** Either add `choices=list_of_valid_bus_types` to the argument
definition (which provides both validation *and* tab-completion), or catch the error
earlier in `cmd_new` and print:

```
✗ Unknown bus type: 'TYPO'
  Available: AXI4_LITE, AXI_STREAM, AVALON_MM, AVALON_ST, AXI4_FULL
  Use 'ipcraft list-buses' for details.
```

---

### 10. `--progress` is only available on `generate`

**Impact: Low.** The `parse` and `validate` commands have no `--progress` flag. For a
large VHDL file with many entities, `parse` could benefit from progress reporting too.
More importantly, the *absence* of the flag on some commands and presence on others
creates an inconsistent mental model.

**Recommendation:** Either add `--progress` to all subcommands for consistency, or
remove it from `generate` and make per-step output conditional on a global `-v` /
`--verbose` flag at the top-level parser.

---

## Minor Observations

| Item | Observation |
|------|-------------|
| `--dump-context` | Debug-only flag with no help text describing what `template_context.json` contains or why a user would want it. Add a short description. |
| `--template-dir` / `--methodology` alias | The alias `--methodology` is meaningful but undocumented. Neither flag's help string explains what a "template directory" is or where to find examples. Link to the templates documentation. |
| `parse` overwrites guard | `parse` requires `--force` to overwrite an existing `.ip.yml`. `generate` overwrites silently (respecting `managed: false`). The asymmetry is non-obvious. Add a short note in the `generate` help text. |
| Top-level `--help` | `ipcraft --help` lists subcommands but provides no workflow examples. A one-line `Examples:` epilog showing the canonical new→generate flow would significantly reduce time-to-first-success for new users. |
| `list-buses` naming | The subcommand uses kebab-case while all others use single words. Consider `list-buses` → `buses` (consistent with `git branch`, `npm list`) or document the convention explicitly. |

---

## Actionable Summary

The following table orders improvements by value-to-effort ratio:

| Priority | Item | Effort |
|----------|------|--------|
| P0 | Redirect errors/tracebacks to stderr | Minutes |
| P0 | Add `--version` flag | Minutes |
| P0 | Add help text to `--no-testbench`, `--no-regs`, `--no-update-yaml` | Minutes |
| P1 | Print one progress line by default in `generate` (non-JSON mode) | Small |
| P1 | Gate tracebacks behind `--debug`; show concise user errors by default | Small |
| P1 | Fix `PROGRESS:` lines to be JSON Lines when `--json` is active | Small |
| P1 | Derive `generate` summary from `written` dict instead of hardcoded text | Small |
| P2 | Add `--json` to `new` subcommand | Small |
| P2 | Add `choices=` or early validation for `--bus` on `new` | Small |
| P3 | Add `--progress` / `--verbose` consistently across all subcommands | Medium |
| P3 | Add `Examples:` epilog to top-level `--help` | Small |

---

## What This Tool Does Right as a CLI *Product*

Setting aside the individual issues above, ipcraft makes several design decisions that
distinguish it from the typical "Python script with flags" tool:

1. **It respects the user's time.** The ASCII diagram after `new`, the file-count
   summary after `generate`, and the `✓ is valid` response after `validate` all close
   the feedback loop immediately.

2. **It was designed for automation from the start.** The `--json` flag is not an
   afterthought — it is documented, consistent across subcommands, and returns a
   predictable schema. Most tools add machine-readable output years too late.

3. **It is honest about what it did.** The `Skipped (unmanaged)` line in generate output
   tells the user exactly why a file was not touched. Many tools silently skip files and
   leave users debugging phantom state.

4. **It does not surprise you.** Defaults are conservative (`managed: false` protects
   user code; `parse` requires `--force` to overwrite). The tool errs on the side of
   asking rather than silently losing work.

These properties are harder to add after the fact than the missing features. ipcraft has
the right values. The remaining work is polish.

---

*Review written against ipcraft source at current HEAD. All `--help` outputs verified by
live invocation.*

---

## Addendum: One Command, TUI Wizard, or Both? An FPGA Designer's Wishlist

*This section captures personal preferences and feature requests from the perspective of
an FPGA engineer who cares about both raw productivity at the terminal and a great
first-run experience for newcomers.*

---

### My honest answer: both — but for different moments

There are two very different contexts in which I use ipcraft:

1. **Starting a new peripheral from scratch** — I am sitting at my desk, I have a design
   sketch on paper, and I want to turn it into a working scaffold as quickly as possible
   without having to look up the YAML syntax for a bus interface or remember whether the
   version default is `1.0` or `1.0.0`.

2. **Iterating on an existing core** — I have just added three registers to `core.mm.yml`
   and I need to regenerate.  I want to type `ipcraft generate my_core.ip.yml` and have
   it done in under a second, with no prompts, no interruptions.

These two contexts have completely opposite UX needs.  A TUI wizard is perfect for
context 1.  A terse, scriptable CLI is essential for context 2.  The answer is **not
either/or** — it is an interactive mode that is always opt-in and never blocks the
scripted path.

The model I want is:

```
ipcraft init          # interactive TUI wizard → emits new .ip.yml + .mm.yml + generates
ipcraft new my_core   # non-interactive scaffold, no prompts (current behaviour)
ipcraft generate ...  # non-interactive generation, no prompts (current behaviour)
```

---

### What "one command, do it all" means to me

For brand-new projects, I want a single `ipcraft init` command that walks me through
every decision, then calls `generate` automatically at the end.  I should be able to go
from zero to compiled VHDL + passing Cocotb test with a single command.

```
$ ipcraft init
```

That is the whole invocation.  The wizard does the rest.

This is not a replacement for `new` + `generate`.  Those stay exactly as they are for
scripts and CI.  `init` is purely a convenience wrapper that exists to serve newcomers
and speed up the first-run experience.

---

### Interactive TUI wizard — proposed question flow

The wizard should proceed in logical, grouped phases.  Each phase can be skipped with
`Enter` (accept defaults) or exited early with `Ctrl+C`.  The user should be able to
go back with `Backspace` or `←`.

Below is the full question sequence I would want, with the control type for each item.

#### Phase 1 — Identity

```
┌─ IP Core Identity ──────────────────────────────────────────────┐
│                                                                   │
│  Core name    [my_core        ]                                   │
│  Vendor       [example.com    ]   (e.g. acme-fpga.com)            │
│  Library      [ip             ]   (e.g. peripherals)              │
│  Version      [1.0.0          ]                                   │
│  Description  [               ]   (optional, one line)            │
│                                                                   │
└───────────────────────────────────────────────────── [Next →]  ──┘
```

- All fields are inline text inputs with defaults pre-filled.
- Validation happens on blur: names must be `[a-z0-9_]`, version must be semver.
- The core name becomes the filename — show the preview: `my_core.ip.yml`.

#### Phase 2 — Bus interface (the most important decision)

```
┌─ Primary Bus Interface ──────────────────────────────────────────┐
│                                                                   │
│  Select bus type:                                                 │
│                                                                   │
│  ❯ AXI4-Lite   Control/status register slave (most common)        │
│    AXI4-Full   High-bandwidth burst slave (DMA engines)           │
│    AXI-Stream  Streaming data path (DSP, video)                   │
│    Avalon-MM   Intel/Quartus register slave                       │
│    Avalon-ST   Intel/Quartus streaming path                       │
│    None        No bus interface (standalone or custom)            │
│                                                                   │
│  [ ] Add a second bus interface after this one                    │
│                                                                   │
└───────────────────────────── [← Back]  ──────────── [Next →]  ──┘
```

- Arrow-key selection list, not a text prompt. Bus type names must never require me to
  remember the exact string (`AXI4_LITE` vs `AXI4L` vs `axi4_lite`).
- One-line description beside each type so newcomers understand the choice.
- The "add a second bus interface" checkbox unlocks Phase 2b (same list again) for
  mixed-interface cores (e.g. AXI-Lite control + AXI-Stream data).

#### Phase 3 — Clocks and resets

```
┌─ Clocks & Resets ────────────────────────────────────────────────┐
│                                                                   │
│  Clock name     [s_axi_aclk   ]   (pre-filled from bus choice)   │
│  Reset name     [s_axi_aresetn]   (pre-filled from bus choice)   │
│  Reset polarity  ● Active-low    ○ Active-high                   │
│                                                                   │
│  [ ] Add a second clock domain                                    │
│                                                                   │
└───────────────────────────── [← Back]  ──────────── [Next →]  ──┘
```

- Pre-fill names from the selected bus convention (AXI-Lite → `s_axi_aclk`,
  `s_axi_aresetn`; Avalon → `clk`, `reset`).
- Let the user change them if their design uses non-standard names.
- Radio button for reset polarity — this is the single most common source of bugs
  in generated wrappers when the designer assumes active-low and the tool generates
  active-high.

#### Phase 4 — Extra ports

```
┌─ Additional Ports ───────────────────────────────────────────────┐
│                                                                   │
│  Add non-bus ports to the top-level entity:                       │
│                                                                   │
│  #   Name        Width   Direction                                │
│  1   [+ Add port]                                                 │
│                                                                   │
│  Leave empty to skip.  These appear in the entity port list.      │
│                                                                   │
└───────────────────────────── [← Back]  ──────────── [Next →]  ──┘
```

Common examples I always add by hand: `o_irq : out std_logic`, `o_pwm : out std_logic`,
`i_data : in std_logic_vector(31 downto 0)`.  Pre-suggest them based on the IP name if
possible (a core named `pwm_core` should see `o_pwm` in the suggestions list).

#### Phase 5 — Output choices

```
┌─ What to Generate ───────────────────────────────────────────────┐
│                                                                   │
│  Vendor integration files:                                        │
│  [x] Intel (Platform Designer .tcl)                               │
│  [x] Xilinx (IP-XACT component.xml + Vivado xgui .tcl)           │
│                                                                   │
│  [x] Cocotb testbench skeleton                                    │
│  [x] Standalone register bank (_regs.vhd)                         │
│                                                                   │
│  Output directory   [./my_core  ]                                  │
│                                                                   │
└───────────────────────────── [← Back]  ──────────── [Next →]  ──┘
```

- Checkbox list, all on by default.  One keypress to toggle.
- Show the output directory preview in real time as the name is typed.

#### Phase 6 — Confirmation and generation

```
┌─ Ready to Generate ──────────────────────────────────────────────┐
│                                                                   │
│  ipcraft will create:                                             │
│                                                                   │
│    ./my_core/my_core.ip.yml                                       │
│    ./my_core/my_core.mm.yml                                       │
│    ./my_core/rtl/my_core_pkg.vhd                                  │
│    ./my_core/rtl/my_core.vhd                                      │
│    ./my_core/rtl/my_core_core.vhd                                 │
│    ./my_core/rtl/my_core_axil.vhd                                 │
│    ./my_core/rtl/my_core_regs.vhd                                 │
│    ./my_core/tb/my_core_test.py                                   │
│    ./my_core/tb/Makefile                                          │
│    ./my_core/intel/my_core_hw.tcl                                 │
│    ./my_core/xilinx/component.xml                                 │
│    ./my_core/xilinx/xgui/my_core_v1_0_0.tcl                      │
│                                                                   │
│  ──────────────────────────────────────────────────              │
│  Equivalent CLI command (copy to script or CI):                   │
│                                                                   │
│  ipcraft new my_core --vendor example.com --bus AXI4_LITE \       │
│    --output ./my_core && \                                        │
│  ipcraft generate ./my_core/my_core.ip.yml --vendor both          │
│                                                                   │
│  [Generate]   [← Back]   [Cancel]                                 │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
```

**The "Equivalent CLI command" panel is the most important UX feature in the entire
wizard.**  It means the wizard is a *learning tool*, not a crutch.  After a few uses I
have the flags memorised and I stop using the wizard.  I stay in muscle-memory CLI mode
for all subsequent cores.  The wizard never creates lock-in.

---

### What I want from the non-interactive CLI path

For the non-TUI path, the two changes I care about most are already in the priority table
above, but worth restating here with FPGA-workflow context:

**1. Default progress output in `generate`.**
When I regenerate after changing the register map, I want to see one line confirming the
run started and one line confirming it finished.  Silent success is indistinguishable
from a hung process on a slow NFS mount.

```
$ ipcraft generate my_core.ip.yml
Generating 11 files from my_core.ip.yml... done (0.4s)
✓ 11 files written to ./build
```

**2. `--watch` mode for the iteration loop.**
The tightest inner loop in FPGA peripheral development is:
*edit register map → regenerate VHDL → recompile → rerun testbench → repeat*.
A `--watch` flag that re-runs `generate` whenever `*.ip.yml` or `*.mm.yml` change would
close this loop without requiring a `Makefile` wrapper:

```bash
ipcraft generate my_core.ip.yml --watch --output ./build
# Watching my_core.ip.yml and my_core.mm.yml for changes...
# [14:22:03] Change detected: my_core.mm.yml
# [14:22:03] Regenerating... done (0.3s)
# [14:22:03] ✓ 11 files written to ./build
```

**3. A `diff` / `--dry-run` mode before destructive regeneration.**
Before I regenerate over an established project, I want to know *which* managed files
will change content:

```bash
$ ipcraft generate my_core.ip.yml --dry-run
Would write (changed):
  rtl/my_core_pkg.vhd        (register count: 3 → 5)
  rtl/my_core_axil.vhd       (address width: 4 → 6 bits)
Would write (unchanged, skipped):
  rtl/my_core.vhd
  rtl/my_core_regs.vhd
  ...
Would skip (unmanaged):
  rtl/my_core_core.vhd
```

This is the single most-requested feature on any code-generation tool I have used.
It turns a black-box `generate` run into a reviewable, reversible action.

---

### Technology recommendation for the TUI

I am not prescriptive about implementation, but for a Python project the two most mature
options are:

| Library | Strengths | Trade-offs |
|---------|-----------|------------|
| [**Textual**](https://github.com/Textualize/textual) | Rich widgets (tables, checkboxes, text inputs), CSS-like layout, active development, good docs | Heavier dependency |
| [**questionary**](https://github.com/tmbo/questionary) | Lightweight, prompt-based (no full-screen TUI), excellent `select` / `checkbox` / `text` primitives, minimal deps | Less rich layout |

For ipcraft's use case **questionary** is the right fit. The wizard is linear
(question → answer → next question), not a full-screen editor. `questionary` handles
that pattern perfectly with minimal dependencies — `select`, `checkbox`, and `text`
primitives cover every phase in the flow above.

---

### Summary of requests

| # | Request | Mode | Priority |
|---|---------|------|----------|
| 1 | `ipcraft init` TUI wizard, runs `generate` at the end | TUI | High |
| 2 | Equivalent CLI command panel on wizard confirmation screen | TUI | High |
| 3 | Bus type selection as arrow-key list, never free text | TUI | High |
| 4 | Pre-filled clock/reset names from bus convention | TUI | Medium |
| 5 | Extra port quick-add (name, width, direction) | TUI | Medium |
| 6 | Default one-line progress output in `generate` (no flag needed) | CLI | High |
| 7 | `--watch` mode for file-change-triggered regeneration | CLI | Medium |
| 8 | `--dry-run` mode showing which managed files would change | CLI | Medium |
| 9 | `--bus` on `new` as validated choice, not free text | CLI | Medium |
