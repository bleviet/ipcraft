# IPCraft -- Improvement Plan (Updated)

> **Based on:** [review.md](file:///wsl.localhost/Ubuntu/home/balevision/workspace/bleviet/ipcraft/review.md)
> **Date:** 2026-02-21 (completed)
> **Status:** 19/19 original tasks completed. 3 new minor items completed.

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
| 2.4 | Clean Up Empty/Placeholder Modules | `converter/` directory removed |
| 2.5 | Standardize on `pathlib.Path` | `cli.py` |
| 2.6 | Remove Over-Defensive `getattr` Chains | `ipcore_project_generator.py` |
| 2.8 | Clean Up Unused Imports in `vhdl_parser.py` | `vhdl_parser.py` |
| 2.9 | Move `test_vhdl_ai_parser.py` | `tests/parser/hdl/test_vhdl_ai_parser.py` |
| 2.10 | Fix `VhdlLlmParser` Path Hardcoding | `vhdl_ai_parser.py` |
| 3.1 | Remove Redundant `count` Validator | `bus.py` |
| 3.2 | Simplify `_find_by_name` with `next()` | `core.py` |
| 3.3 | Cache `AddressBlock.end_address` | `memory_map.py` |
| 3.4 | Add Deprecation Warnings to Legacy Aliases | `ipcore_project_generator.py` |
| 3.5 | Remove No-Op `_process_port_list` | `vhdl_parser.py` |

---

## Recently Completed Tasks

---

### Task A -- Add Mixin Typing Protocols (Medium Priority)

**Context:** Mixins call methods defined on sibling classes without type contracts. IDE refactoring is unreliable and `mypy` cannot verify cross-mixin method calls.

**Affected Files:**
- [NEW] `ipcraft/generator/hdl/_protocols.py`
- [NEW] `ipcraft/parser/yaml/_protocols.py`
- [MODIFY] [testbench_generator.py](file:///wsl.localhost/Ubuntu/home/balevision/workspace/bleviet/ipcraft/ipcraft/generator/hdl/testbench_generator.py)
- [MODIFY] [vendor_generator.py](file:///wsl.localhost/Ubuntu/home/balevision/workspace/bleviet/ipcraft/ipcraft/generator/hdl/vendor_generator.py)
- [MODIFY] [fileset_manager.py](file:///wsl.localhost/Ubuntu/home/balevision/workspace/bleviet/ipcraft/ipcraft/generator/hdl/fileset_manager.py)
- [MODIFY] [memory_map_parser.py](file:///wsl.localhost/Ubuntu/home/balevision/workspace/bleviet/ipcraft/ipcraft/parser/yaml/memory_map_parser.py)
- [MODIFY] [fileset_parser.py](file:///wsl.localhost/Ubuntu/home/balevision/workspace/bleviet/ipcraft/ipcraft/parser/yaml/fileset_parser.py)

#### Step 1: Create generator protocol

```python
# NEW FILE: ipcraft/generator/hdl/_protocols.py

from __future__ import annotations
from typing import Any, Dict, Protocol

from jinja2 import Environment

from ipcraft.model.core import IpCore


class GeneratorHost(Protocol):
    """Protocol for the host class that generator mixins expect."""

    env: Environment

    def _get_template_context(
        self, ip_core: IpCore, bus_type: str = "axil"
    ) -> Dict[str, Any]: ...
```

#### Step 2: Create parser protocol

```python
# NEW FILE: ipcraft/parser/yaml/_protocols.py

from __future__ import annotations
from typing import Any, Dict, Protocol


class ParserHost(Protocol):
    """Protocol for the host class that parser mixins expect."""

    @staticmethod
    def _parse_access(access: Any) -> Any: ...
```

> [!NOTE]
> `_filter_none` was moved to `utils/` and is now imported directly as `filter_none()`.
> The mixins import it from `ipcraft.utils`, so the protocol does NOT need to include it.

#### Step 3: Type-hint `self` in mixin methods

```python
# In testbench_generator.py:
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._protocols import GeneratorHost

class TestbenchGenerationMixin:
    def generate_cocotb_test(
        self: GeneratorHost, ip_core: IpCore, bus_type: str = "axil"
    ) -> str:
        template = self.env.get_template("cocotb_test.py.j2")
        context = self._get_template_context(ip_core, bus_type)
        return template.render(**context)
```

Apply the same pattern to `VendorGenerationMixin` and `FileSetManagerMixin`.

For parser mixins (`MemoryMapParserMixin`, `FileSetParserMixin`), type-hint `self: ParserHost` on methods that call `self._parse_access()`.

#### Validation

```bash
# Run mypy to verify protocols catch real errors:
uv run mypy ipcraft/generator/hdl/ ipcraft/parser/yaml/
```

---

### Task B -- Add `BusIOError` Exception (Medium Priority)

**Context:** `register.py` catches bare `Exception` in 3 RMW locations (lines 316, 342, 396). This can hide programming errors (e.g., `TypeError`, `AttributeError`).

**Affected Files:**
- [MODIFY] [register.py](file:///wsl.localhost/Ubuntu/home/balevision/workspace/bleviet/ipcraft/ipcraft/runtime/register.py) -- Define `BusIOError`, update catch blocks
- [MODIFY] `ipcraft/runtime/__init__.py` -- Export `BusIOError`

#### Step 1: Define exception class

```python
# In runtime/register.py -- add at module level (after imports):

class BusIOError(IOError):
    """Raised when a bus read/write operation fails.

    Bus interface implementations should raise this when
    a hardware read or write operation fails (timeout, NACK, etc.).
    """
```

#### Step 2: Update docstrings on abstract bus interfaces

```python
# In AbstractBusInterface.read_word docstring, add:
#     Raises:
#         BusIOError: If the bus operation fails.

# Same for AbstractBusInterface.write_word, AsyncBusInterface.read_word,
# AsyncBusInterface.write_word.
```

#### Step 3: Replace catch blocks (3 locations)

```python
# Lines 314-321 (Register.write_field):
        try:
            current_reg_val = self.read()
        except BusIOError as exc:
            logger.warning(
                "Failed to read register '%s' during RMW: %s; "
                "proceeding with current_value=0",
                self.name,
                exc,
            )

# Lines 339-347 (Register.write_multiple_fields):
        try:
            current_reg_val = self.read()
        except BusIOError as exc:
            logger.warning(
                "Failed to read register '%s' during RMW: %s; "
                "proceeding with current_value=0",
                self.name,
                exc,
            )

# Lines 393-401 (AsyncRegister.write_field):
        try:
            current_reg_val = await self.read()
        except BusIOError as exc:
            logger.warning(
                "Failed to read register '%s' during async RMW: %s; "
                "proceeding with current_value=0",
                self.name,
                exc,
            )
```

#### Step 4: Export from `runtime/__init__.py`

```python
# In ipcraft/runtime/__init__.py add:
from ipcraft.runtime.register import BusIOError
```

#### Validation and Tests

```python
# tests/core/test_bus_io_error.py

import logging
import pytest
from ipcraft.runtime.register import (
    AbstractBusInterface, BitField, BusIOError, Register,
)


class FailingBus(AbstractBusInterface):
    """Bus that raises BusIOError on read."""
    def read_word(self, address: int) -> int:
        raise BusIOError("bus timeout")
    def write_word(self, address: int, data: int) -> None:
        pass


class TestRMWWithBusError:
    def test_write_field_logs_warning_on_bus_error(self, caplog):
        fields = [BitField(name="ENABLE", offset=0, width=1, access="rw")]
        reg = Register("CTRL", 0x00, FailingBus(), fields)

        with caplog.at_level(logging.WARNING):
            reg.write_field("ENABLE", 1)

        assert "bus timeout" in caplog.text

    def test_bus_io_error_is_ioerror(self):
        assert issubclass(BusIOError, IOError)

    def test_programming_errors_propagate(self):
        """Non-BusIOError exceptions should NOT be caught."""
        class BrokenBus(AbstractBusInterface):
            def read_word(self, address: int) -> int:
                raise TypeError("this is a bug")
            def write_word(self, address: int, data: int) -> None:
                pass

        fields = [BitField(name="ENABLE", offset=0, width=1, access="rw")]
        reg = Register("CTRL", 0x00, BrokenBus(), fields)
        with pytest.raises(TypeError, match="this is a bug"):
            reg.write_field("ENABLE", 1)
```

---

### Task C -- Add `__version__` to `ipcraft/__init__.py` (Low Priority)

**Affected Files:**
- [MODIFY] [\_\_init\_\_.py](file:///wsl.localhost/Ubuntu/home/balevision/workspace/bleviet/ipcraft/ipcraft/__init__.py)

#### Implementation

```python
# ipcraft/__init__.py
"""IPCraft -- Python library for IP Core development and VHDL generation."""

__version__ = "0.1.0"
```

#### Validation

```python
# tests/test_package_init.py
def test_version_exported():
    import ipcraft
    assert hasattr(ipcraft, "__version__")
    assert ipcraft.__version__ == "0.1.0"
```

---

## Minor Cleanup Tasks

---

### Task D -- Remove Unused Imports in `verilog_parser.py`

**Affected Files:**
- [MODIFY] [verilog_parser.py](file:///wsl.localhost/Ubuntu/home/balevision/workspace/bleviet/ipcraft/ipcraft/parser/hdl/verilog_parser.py)

#### Implementation

Remove `LineEnd` and `delimitedList` from the pyparsing import block (lines 13, 25).

```diff
 from pyparsing import (
     CaselessKeyword,
     CaselessLiteral,
     Group,
-    LineEnd,
     ParseBaseException,
 )
 from pyparsing import Optional as Opt
 from pyparsing import (
     ParserElement,
     SkipTo,
     Suppress,
     Word,
     ZeroOrMore,
     alphanums,
     alphas,
-    delimitedList,
     nums,
     oneOf,
 )
```

#### Validation

```bash
uv run flake8 ipcraft/parser/hdl/verilog_parser.py --select F401
# Expected: no output
```

---

### Task E -- Fix Stale `hasattr` Pattern in Test

**Affected Files:**
- [MODIFY] [test_hdl_roundtrip.py](file:///wsl.localhost/Ubuntu/home/balevision/workspace/bleviet/ipcraft/ipcraft/tests/parser/hdl/test_hdl_roundtrip.py)

#### Implementation

```python
# Line 224 -- BEFORE:
if hasattr(port.direction, "value")

# AFTER:
from ipcraft.utils import enum_value
# ... then use enum_value(port.direction) where needed
```

#### Validation

```bash
uv run pytest ipcraft/tests/parser/hdl/test_hdl_roundtrip.py -v
```

---

## Final Validation

After all remaining tasks are complete:

```bash
# Full test suite
uv run pytest -v

# Lint
uv run flake8 ipcraft

# Type checking
uv run mypy ipcraft

# Grep checks
grep -r "except Exception" ipcraft/runtime/register.py  # Should find 0 hits
grep -r "hasattr.*value" ipcraft/ --include="*.py"       # Should find 0 non-docstring hits
```

### Acceptance Criteria

| Check | Target |
|-------|--------|
| All existing tests pass | Required |
| No new flake8 warnings | Required |
| `mypy` passes with mixin protocols | Required |
| `grep -r "except Exception" ipcraft/runtime/register.py` returns 0 hits | Required |
| `grep -r "hasattr.*value" ipcraft/` returns 0 non-docstring hits | Required |
| `ipcraft.__version__` is accessible | Required |
