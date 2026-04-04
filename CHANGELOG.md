# Changelog

All notable changes to ipcraft are documented here.  
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).  
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [Unreleased] — refactor/ipcraft-improvement-plan

### Fixed

- **[TASK-10] BUG-A: Jinja2 `has_wstrb` scoping** (`bus_axil.vhdl.j2`,
  `ipcore_project_generator.py`)  
  `{% set has_wstrb = true %}` inside a `{% for %}` loop does not propagate to
  outer scope in Jinja2. `wr_strb` was unconditionally driven with `(others => '1')`,
  silently disabling WSTRB partial-write support even when the WSTRB port was
  declared. Fix: `has_wstrb` is now pre-computed in `_get_template_context()` and
  passed directly as a template context variable. The broken loop in the template is
  removed.

- **[TASK-11] BUG-B: W1C registers excluded from `t_regs_sw2hw`** (`package.vhdl.j2`)  
  The `sw2hw_regs` Jinja2 filter only matched `read-write`, `write-only`, `rw`, `wo`.
  A register with top-level access `write-1-to-clear` (or `rw1c`, `w1c`,
  `read-write-1-to-clear`) was included in neither `t_regs_sw2hw` nor `t_regs_hw2sw`,
  producing an undefined type reference and a compile error. Fix:
  - `sw2hw_regs` now includes all W1C access-type variants (software can write)
  - `hw2sw_regs` now uses `reg.hw2sw` (pre-computed by the generator via
    `AccessType.normalize()`), which correctly covers read-only and all W1C variants

- **[TASK-12] BUG-C: AXI-Lite wrapper header comment showed wrong addresses**
  (`bus_axil.vhdl.j2`)  
  The `-- Register Map:` banner used `loop.index0 * reg_width` (sequential) instead
  of the actual register offset. Sparse maps showed incorrect addresses. Fixed to use
  `reg.offset` directly, with correct array expansion for register arrays.

- **[TASK-13] IMP-A: W1C variable-based single assignment** (`register_file.vhdl.j2`)  
  The previous dual-assignment pattern (`regs.x <= to_x(v_wdata);` followed by
  `regs.x.field <= ... and not wr_data(n);`) is LRM-correct in VHDL-2008 but
  triggers "multiple drivers" warnings in SpyGlass, Synopsys DC, and some Quartus
  lint configurations. Fixed: W1C bit masking is now applied to the intermediate
  `v_wdata` vector variable *before* record conversion, resulting in a single
  `regs.x <= to_x(v_wdata);` assignment per case arm. Lint-clean and
  synthesises identically.

- **[TASK-14] IMP-B: PYTHONPATH no longer hard-coded to 4 directory levels**
  (`cocotb_makefile.j2`)  
  The generated Makefile used `cd $(CURDIR)/../../../.. && pwd` which assumed a
  specific project layout and silently broke for any other structure. Now uses
  Python introspection: `python -c "import ipcraft, os; print(...)"` to find the
  installed location automatically. Users can override with `IPCRAFT_ROOT=/path make`.
  Falls back with a clear `$(warning ...)` if ipcraft is not importable.

- **[TASK-15] IMP-C: Testbench register discovery no longer uses `dir()`**
  (`cocotb_test.py.j2`, `ipcraft/driver/loader.py`)  
  The generated testbench iterated `dir(driver)` and `dir(block)` to discover
  blocks and registers. This is fragile (catches all public attributes and methods).
  Fix:
  - `IpCoreDriver` now maintains `_blocks: list[str]` — ordered block names
  - `AddressBlock` now maintains `_registers: list[str]` — ordered register names
  - Both are populated by `load_driver()` as blocks/registers are attached
  - The testbench template iterates `driver._blocks` and `block._registers` instead

- **[TASK-16] IMP-D: Standardised indentation in `top.vhdl.j2`**  
  The architecture body mixed 2-space signal declarations with 4-space instantiation
  blocks and 6-space port map contents. Standardised to consistent 2-space indentation
  throughout.  
  Added `w1c_fields` context propagation in `ipcore_project_generator.py`.  
  The write `case` statement now clears only the bits written as `'1'` for
  `write-1-to-clear` fields instead of overwriting the full register value.  
  Hardware-set priority-over-software-clear logic added after the `case` block.  
  Affects: interrupt status registers, any `access: write-1-to-clear` field.

- **[TASK-02] Sparse `reg_addr()` address function** (`package.vhdl.j2`)  
  Replaced `t_reg_id'pos(reg) * C_REG_WIDTH` with a Jinja2-generated `case`
  lookup that returns the actual YAML offset for each register.  
  Previous behaviour returned wrong addresses for any register map with gaps
  (e.g. offsets `0x00`, `0x04`, `0x10` would return `0x08` for the third).

- **[TASK-03] Hard-coded `s_axi_` prefix in AXI-Lite output assignments**
  (`bus_axil.vhdl.j2`)  
  Output port assignments now use `{{ port.name }}` (respecting
  `physical_prefix`).  Input port references use generated `alias` declarations
  (`alias awvalid_i ... is {{ port.name }}`).  
  Previous behaviour produced unresolvable signal names when `physical_prefix`
  was set to anything other than `s_axi_`.

- **[TASK-04] `C_ADDR_WIDTH` auto-calculated from register map**
  (`ipcore_project_generator.py`)  
  `C_ADDR_WIDTH` is now derived from `max(offset + stride × count).bit_length()`
  instead of the hard-coded value of `8`.  
  Previous behaviour silently limited address decode to 256 bytes (64 × 32-bit
  registers); larger maps produced incorrect decode logic.

- **[TASK-05] Access-type comparisons normalised to `AccessType` enum**
  (`ipcore_project_generator.py`)  
  Raw string sets (`{"read-only", "ro", ...}`) replaced with
  `AccessType.normalize()` comparisons throughout `_prepare_registers()`.  
  Eliminates string-drift bugs when new access-type aliases are introduced.

- **[TASK-08] pyparsing deprecated API migration** (`vhdl_parser.py`)  
  `oneOf()` → `one_of()`, `nestedExpr()` → `nested_expr()`.  
  Suppresses `DeprecationWarning` on pyparsing ≥ 3.2 and ensures forward
  compatibility.

- **[IMP-3] Default WSTRB when port is absent** (`bus_axil.vhdl.j2`)  
  Added conditional: `wr_strb <= wstrb_i` when the WSTRB port exists,
  `wr_strb <= (others => '1')` otherwise.  
  Prevents undriven `wr_strb` signal when WSTRB is omitted from the bus port
  list.

- **[fileset parser] `managed` flag silently ignored** (`fileset_parser.py`)  
  `_parse_files()` now reads `managed`, `is_include_file`, and `logical_name`
  from each YAML file entry.  Previously every file was parsed as `managed=True`,
  so `managed: false` was silently overridden and user-edited files were
  overwritten on every `generate` run.

- **[template] Flat registers missing `t_reg_<name>` type** (`package.vhdl.j2`)  
  Added `{% else %}` block emitting a `data : std_logic_vector` record for
  registers with no named sub-fields.  Previously the aggregate `t_regs_sw2hw`
  referenced an undefined type, producing a compile error.

- **[template] `t_regs_hw2sw` absent when no read-only registers exist**
  (`package.vhdl.j2`)  
  Added a `dummy : std_logic` placeholder record so that bus wrapper and core
  entity ports always compile even with an all-RW register map.

### Added

- **[TASK-07] Register map documentation template** (`regmap_docs.md.j2`)  
  Generates a Markdown register map document containing:
  - Summary table (offset, name, access type, reset value, description)
  - Per-register detail sections with bit-field tables
  - Handles register arrays and flat (field-less) registers  
  Wired into `generate_all_with_structure()` alongside the testbench.

- **`secondary_bus_ports` threading through templates**  
  `core.vhdl.j2` and `top.vhdl.j2` now accept a `secondary_bus_ports` context
  list, forwarding non-primary bus interface ports (e.g. an AXI-Stream data port
  alongside an AXI-Lite control port) through the top-level entity and core.

- **`user_ports` threading through templates**  
  User-defined ports (from `ip.yml` `ports:` section) are forwarded through
  `top.vhdl.j2` and `core.vhdl.j2`, eliminating the need to manually add ports
  to generated files.

- **Vivado IP packaging support** (`xilinx_package_ip_tcl.j2`)  
  New template generates a `package_ip.tcl` script for native Vivado IP
  packaging workflow (in addition to the existing `component.xml`).

### Changed

- **[TASK-09] Skipped tests documented** (various test files)  
  37 previously unexplained skips converted to `@pytest.mark.xfail` with
  documented reasons (missing simulator, incomplete feature, platform-specific).
  No unexplained skips remain in the test suite.

- **`ipcraft new` output** — generated `.ip.yml` now includes a comment block
  describing the `managed: false` flag, surfacing the file-protection feature
  to first-time users.

- **Bus type aliases** — `AXI4_LITE`, `AXI_STREAM`, `AVALON_MEMORY_MAPPED`,
  `AVALON_STREAMING`, `AXI4_FULL` accepted as `--bus` arguments in addition to
  the canonical short forms (`AXI4L`, `AXIS`, etc.).

---

## Known Issues (Open)

All bugs identified through the third-pass expert review have been fixed (TASK-10
through TASK-16).  See the `### Fixed` entries above for details.

The following are **open feature requests**, not bugs:

| C/C++ register header (`c_header.h.j2`) | P0 | TASK-06 carry-over |
| AXI4-Full burst wrapper template | P0 | — |
| SystemVerilog generator | P1 | — |
| UVM RAL model generation | P1 | — |
| AXI4-Lite formal PSL property file | P1 | PROP-1 |
| First-class interrupt modeling in schema | P1 | PROP-3 |
| `ipcraft diff` change impact analysis | P1 | PROP-5 |
