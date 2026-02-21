# IPCraft -- Improvement Plan (Updated)

> **Based on:** [review.md](file:///wsl.localhost/Ubuntu/home/balevision/workspace/bleviet/ipcraft/review.md)
> **Date:** 2026-02-21 (final update)
> **Status:** All 21 review findings resolved. 3 minor polish items remain.

---

## Completed Tasks (Reference)

| Task | Description | Files Changed |
|------|-------------|---------------|
| 1.1 | Unify Bus Definition Loading via `BusLibrary` Singleton | `bus_library.py`, `ipcore_project_generator.py`, `bus_detector.py` |
| 1.2 | Consolidate Bus Type Mapping Tables | `utils/__init__.py`, `cli.py`, `ipcore_project_generator.py` |
| 1.3 | Extract `enum_value()` Utility | `utils/__init__.py`, `ipcore_project_generator.py` |
| 1.4 | Extract Generic List Parser | `ip_yaml_parser.py` |
| 2.1 | Fix CLI Naming (`ipcore` -> `ipcraft`) | `cli.py` |
| 2.2 | Move `_filter_none` to `utils/` | `utils/__init__.py`, `ip_yaml_parser.py` |
| 2.3 | Add Mixin Typing Protocols | `_protocols.py`, `protocols.py`, `testbench_generator.py`, `vendor_generator.py`, `memory_map_parser.py` |
| 2.4 | Clean Up Empty/Placeholder Modules | `converter/` directory removed |
| 2.5 | Standardize on `pathlib.Path` | `cli.py` |
| 2.6 | Remove Over-Defensive `getattr` Chains | `ipcore_project_generator.py` |
| 2.7 | Add `BusIOError` Exception | `register.py`, `runtime/__init__.py` |
| 2.8 | Clean Up Unused Imports in `vhdl_parser.py` | `vhdl_parser.py` |
| 2.9 | Move `test_vhdl_ai_parser.py` | `tests/parser/hdl/test_vhdl_ai_parser.py` |
| 2.10 | Fix `VhdlLlmParser` Path Hardcoding | `vhdl_ai_parser.py` |
| 3.1 | Remove Redundant `count` Validator | `bus.py` |
| 3.2 | Simplify `_find_by_name` with `next()` | `core.py` |
| 3.3 | Cache `AddressBlock.end_address` | `memory_map.py` |
| 3.4 | Add Deprecation Warnings to Legacy Aliases | `ipcore_project_generator.py` |
| 3.5 | Remove No-Op `_process_port_list` | `vhdl_parser.py` |
| 3.6 | Add `__version__` to `ipcraft/__init__.py` | `__init__.py` |
| 3.7 | Fix Stale `hasattr` in Test Roundtrip | `test_hdl_roundtrip.py` |

---

## Remaining Tasks

---

### Task A -- Remove Unnecessary `hasattr` Guard in `vendor_generator.py` (Low Priority)

**Context:** `IpCore.description` is a Pydantic field with `default=""`. It always exists on valid `IpCore` instances. The `hasattr` check is dead code that obscures the intent.

**Affected Files:**
- [MODIFY] [vendor_generator.py](file:///wsl.localhost/Ubuntu/home/balevision/workspace/bleviet/ipcraft/ipcraft/generator/hdl/vendor_generator.py)

#### Implementation

```diff
 # Line 22-24 (generate_intel_hw_tcl):
-        context["description"] = (
-            ip_core.description if hasattr(ip_core, "description") else ""
-        )
+        context["description"] = ip_core.description

 # Line 36-38 (generate_xilinx_component_xml):
-        context["description"] = (
-            ip_core.description if hasattr(ip_core, "description") else ""
-        )
+        context["description"] = ip_core.description
```

#### Validation

```bash
/home/linuxbrew/.linuxbrew/bin/uv run pytest -v ipcraft/tests/
/home/linuxbrew/.linuxbrew/bin/uv run flake8 ipcraft/generator/hdl/vendor_generator.py
```

---

### Task B -- Fix Changelog Exception Name (Low Priority)

**Context:** `docs/changelog.md` line 16 references `BusLibraryError` but the actual exception class is `BusIOError`.

**Affected Files:**
- [MODIFY] [changelog.md](file:///wsl.localhost/Ubuntu/home/balevision/workspace/bleviet/ipcraft/docs/changelog.md)

#### Implementation

```diff
 # Line 16:
-- Add specific exceptions for Bus I/O errors (`BusLibraryError`)
+- Add specific exceptions for Bus I/O errors (`BusIOError`)
```

---

### Task C -- Configurable Register Width in `register.py` (Enhancement, Low Priority)

**Context:** `BitField.__post_init__` hardcodes a 32-bit width limit. This prevents support for 64-bit registers which are common in high-speed interfaces (PCIe, AXI4-Full).

**Affected Files:**
- [MODIFY] [register.py](file:///wsl.localhost/Ubuntu/home/balevision/workspace/bleviet/ipcraft/ipcraft/runtime/register.py)

#### Implementation

Replace the hardcoded `32` with a class-level constant:

```python
# register.py -- add class constant after docstring:
@dataclass
class BitField:
    """Represents a single bit field within a register."""

    MAX_REGISTER_WIDTH: ClassVar[int] = 64

    name: str
    offset: int
    width: int
    access: str = "rw"
    description: str = ""
    reset_value: Optional[int] = None

    def __post_init__(self):
        """Validate bit field parameters."""
        # ... existing access validation ...

        if self.width <= 0:
            raise ValueError(f"Bit field '{self.name}' width must be positive")
        if self.width > self.MAX_REGISTER_WIDTH:
            raise ValueError(
                f"Bit field '{self.name}' width cannot exceed "
                f"{self.MAX_REGISTER_WIDTH} bits"
            )
        if self.offset < 0:
            raise ValueError(
                f"Bit field '{self.name}' offset must be non-negative"
            )
        if self.offset + self.width > self.MAX_REGISTER_WIDTH:
            raise ValueError(
                f"Bit field '{self.name}' extends beyond "
                f"{self.MAX_REGISTER_WIDTH}-bit register boundary"
            )
```

> [!NOTE]
> This requires adding `from typing import ClassVar` to the imports.

#### Validation

```bash
/home/linuxbrew/.linuxbrew/bin/uv run pytest -v ipcraft/tests/core/
/home/linuxbrew/.linuxbrew/bin/uv run flake8 ipcraft/runtime/register.py
```

---

## Final Validation

After all remaining tasks are complete:

```bash
# Full test suite
/home/linuxbrew/.linuxbrew/bin/uv run pytest -v

# Lint
/home/linuxbrew/.linuxbrew/bin/uv run flake8 ipcraft/

# Type checking
/home/linuxbrew/.linuxbrew/bin/uv run mypy ipcraft/

# Grep checks
grep -rn 'hasattr.*description' ipcraft/generator/  # Should find 0 hits
```

### Acceptance Criteria

| Check | Target |
|-------|--------|
| All existing tests pass | Required |
| No new flake8 warnings | Required |
| `mypy` passes | Required |
| `grep -rn 'hasattr.*description' ipcraft/generator/` returns 0 hits | Required (Task A) |
| `docs/changelog.md` references `BusIOError` | Required (Task B) |
