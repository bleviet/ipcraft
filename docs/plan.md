# IPCraft — Improvement Plan

> **Based on:** [review.md](file:///wsl.localhost/Ubuntu/home/balevision/workspace/bleviet/ipcraft/review.md)  
> **Date:** 2026-02-21  
> **Structure:** Each task includes context, detailed implementation, affected files, and a validation/testing section.

---

## Phase 1 — 🔴 High Priority: DRY Violations

These tasks eliminate the most impactful code duplication.

---

### Task 1.1 — Unify Bus Definition Loading via `BusLibrary` Singleton

**Context:** Bus definitions YAML is loaded independently in 3 places with 3 different implementations. The `BusLibrary` singleton already exists in `model/bus_library.py` — the generator and detector should delegate to it.

**Affected Files:**
- [bus_library.py](file:///wsl.localhost/Ubuntu/home/balevision/workspace/bleviet/ipcraft/ipcraft/model/bus_library.py) — Add raw-dict accessor
- [ipcore_project_generator.py](file:///wsl.localhost/Ubuntu/home/balevision/workspace/bleviet/ipcraft/ipcraft/generator/hdl/ipcore_project_generator.py) — Remove `_load_bus_definitions()`, use `BusLibrary`
- [bus_detector.py](file:///wsl.localhost/Ubuntu/home/balevision/workspace/bleviet/ipcraft/ipcraft/parser/hdl/bus_detector.py) — Remove `_load_definitions()`, use `BusLibrary`

#### Step 1: Add raw-dict accessor to `BusLibrary`

The generator and detector currently need raw dict access to bus port definitions. Add a method to `BusLibrary` that exposes this:

```python
# In model/bus_library.py — add to BusLibrary class

def get_raw_bus_dict(self, bus_type: str) -> Dict[str, Any]:
    """Get raw bus definition dict (ports list, busType info) for a given type.

    Returns {} if bus_type not found. Useful for generator/detector
    code that needs the original port-list structure.
    """
    defn = self._definitions.get(bus_type)
    if not defn:
        return {}
    return {
        "busType": {
            "vendor": defn.bus_type.vendor,
            "library": defn.bus_type.library,
            "name": defn.bus_type.name,
            "version": defn.bus_type.version,
        },
        "ports": [
            {
                "name": p.name,
                "direction": p.direction,
                "width": p.width,
                "presence": p.presence,
            }
            for p in defn.ports
        ],
    }

def get_all_raw_dicts(self) -> Dict[str, Dict[str, Any]]:
    """Get all bus definitions as raw dicts (replaces yaml.safe_load consumers)."""
    return {key: self.get_raw_bus_dict(key) for key in self._definitions}
```

#### Step 2: Refactor `IpCoreProjectGenerator`

```python
# In generator/hdl/ipcore_project_generator.py

# BEFORE (remove this):
import yaml
# ...
def _load_bus_definitions(self) -> Dict[str, Any]:
    bus_defs_path = BUS_DEFINITIONS_PATH
    if bus_defs_path.exists():
        with open(bus_defs_path) as f:
            return yaml.safe_load(f)
    return {}

# AFTER (replace with):
from ipcraft.model.bus_library import get_bus_library

def __init__(self, template_dir=None, bus_library=None):
    # ... existing template setup ...
    self._bus_library = bus_library or get_bus_library()
    self.bus_definitions = self._bus_library.get_all_raw_dicts()
```

#### Step 3: Refactor `BusInterfaceDetector`

```python
# In parser/hdl/bus_detector.py

# BEFORE (remove this):
import yaml
# ...
def _load_definitions(self) -> Dict[str, Any]:
    if not self.bus_defs_path.exists():
        return {}
    with open(self.bus_defs_path, "r") as f:
        return yaml.safe_load(f) or {}

# AFTER (replace with):
from ipcraft.model.bus_library import BusLibrary, get_bus_library

class BusInterfaceDetector:
    def __init__(self, bus_library: Optional[BusLibrary] = None):
        self._bus_library = bus_library or get_bus_library()
        self.bus_definitions = self._bus_library.get_all_raw_dicts()
```

#### Validation & Tests

```python
# tests/model/test_bus_library_singleton.py

import pytest
from ipcraft.model.bus_library import BusLibrary, get_bus_library


class TestBusLibrarySingleton:
    """Verify single-loading behavior and raw dict accessors."""

    def test_singleton_returns_same_instance(self):
        lib1 = get_bus_library()
        lib2 = get_bus_library()
        assert lib1 is lib2

    def test_get_raw_bus_dict_structure(self):
        lib = get_bus_library()
        axi4l = lib.get_raw_bus_dict("AXI4L")
        assert "busType" in axi4l
        assert "ports" in axi4l
        assert isinstance(axi4l["ports"], list)
        assert all("name" in p for p in axi4l["ports"])

    def test_get_raw_bus_dict_unknown_type(self):
        lib = get_bus_library()
        result = lib.get_raw_bus_dict("NONEXISTENT")
        assert result == {}

    def test_get_all_raw_dicts_matches_list(self):
        lib = get_bus_library()
        all_dicts = lib.get_all_raw_dicts()
        assert set(all_dicts.keys()) == set(lib.list_bus_types())


class TestGeneratorUsesBusLibrary:
    """Verify generator no longer loads YAML independently."""

    def test_generator_accepts_bus_library(self):
        from ipcraft.generator.hdl.ipcore_project_generator import IpCoreProjectGenerator
        lib = get_bus_library()
        gen = IpCoreProjectGenerator(bus_library=lib)
        assert gen.bus_definitions == lib.get_all_raw_dicts()

    def test_detector_accepts_bus_library(self):
        from ipcraft.parser.hdl.bus_detector import BusInterfaceDetector
        lib = get_bus_library()
        detector = BusInterfaceDetector(bus_library=lib)
        assert detector.bus_definitions == lib.get_all_raw_dicts()
```

---

### Task 1.2 — Consolidate Bus Type Mapping Tables

**Context:** Three modules define overlapping bus type alias maps. Unify into a two-step canonical lookup in `utils/__init__.py`.

**Affected Files:**
- [utils/\_\_init\_\_.py](file:///wsl.localhost/Ubuntu/home/balevision/workspace/bleviet/ipcraft/ipcraft/utils/__init__.py) — Single source of truth
- [cli.py](file:///wsl.localhost/Ubuntu/home/balevision/workspace/bleviet/ipcraft/ipcraft/cli.py) — Remove `BUS_TYPE_MAP`, import from utils
- [ipcore_project_generator.py](file:///wsl.localhost/Ubuntu/home/balevision/workspace/bleviet/ipcraft/ipcraft/generator/hdl/ipcore_project_generator.py) — Remove `BUS_TYPE_MAP`, import from utils

#### Implementation

```python
# In utils/__init__.py — replace existing _BUS_TYPE_ALIASES and normalize_bus_type_key

# Step 1: Canonical bus type keys (alias → canonical key)
_BUS_TYPE_ALIASES: dict[str, str] = {
    "AXIL": "AXI4L",
    "AXI4-LITE": "AXI4L",
    "AXI4LITE": "AXI4L",
    "AXILITE": "AXI4L",
    "AVMM": "AVALON_MM",
    "AVALON-MM": "AVALON_MM",
    "AVALONMM": "AVALON_MM",
    "AVALON_MM": "AVALON_MM",
}

# Step 2: Canonical key → generator code (what the template system uses)
_CANONICAL_TO_GENERATOR: dict[str, str] = {
    "AXI4L": "axil",
    "AVALON_MM": "avmm",
}


def normalize_bus_type_key(raw: str) -> str:
    """Normalize a bus type string to its canonical key (e.g. 'axil' → 'AXI4L')."""
    upper = raw.upper() if isinstance(raw, str) else str(raw).upper()
    return _BUS_TYPE_ALIASES.get(upper, upper)


def bus_type_to_generator_code(raw: str) -> str:
    """Convert any bus type string to the generator template code ('axil' or 'avmm').

    Falls back to 'axil' for unknown types.

    Examples:
        >>> bus_type_to_generator_code("AXI4L")
        'axil'
        >>> bus_type_to_generator_code("AVALON-MM")
        'avmm'
        >>> bus_type_to_generator_code("axil")
        'axil'
    """
    canonical = normalize_bus_type_key(raw)
    return _CANONICAL_TO_GENERATOR.get(canonical, "axil")
```

Then in `cli.py`, replace `BUS_TYPE_MAP` usage:

```python
# cli.py — BEFORE:
bus_type = BUS_TYPE_MAP.get(bus_type.upper(), "axil")

# cli.py — AFTER:
from ipcraft.utils import bus_type_to_generator_code
bus_type = bus_type_to_generator_code(bus_type)
```

And in `ipcore_project_generator.py`, remove the class-level `BUS_TYPE_MAP` and import `normalize_bus_type_key` (already imported) — no other changes needed since it already uses that function.

#### Validation & Tests

```python
# tests/test_utils.py

import pytest
from ipcraft.utils import normalize_bus_type_key, bus_type_to_generator_code


class TestBusTypeMapping:
    @pytest.mark.parametrize("input_val, expected", [
        ("AXI4L", "AXI4L"),
        ("axil", "AXI4L"),
        ("axi4-lite", "AXI4L"),
        ("AXILITE", "AXI4L"),
        ("AVALON_MM", "AVALON_MM"),
        ("avmm", "AVALON_MM"),
        ("AVALON-MM", "AVALON_MM"),
        ("UNKNOWN", "UNKNOWN"),
    ])
    def test_normalize_bus_type_key(self, input_val, expected):
        assert normalize_bus_type_key(input_val) == expected

    @pytest.mark.parametrize("input_val, expected", [
        ("AXI4L", "axil"),
        ("axil", "axil"),
        ("AVALON_MM", "avmm"),
        ("avmm", "avmm"),
        ("axi4-lite", "axil"),
        ("UNKNOWN", "axil"),  # fallback
    ])
    def test_bus_type_to_generator_code(self, input_val, expected):
        assert bus_type_to_generator_code(input_val) == expected
```

---

### Task 1.3 — Extract `enum_value()` Utility

**Context:** The pattern `x.value if hasattr(x, "value") else str(x)` appears 8+ times across the codebase.

**Affected Files:**
- [utils/\_\_init\_\_.py](file:///wsl.localhost/Ubuntu/home/balevision/workspace/bleviet/ipcraft/ipcraft/utils/__init__.py) — Add `enum_value()`
- [ipcore_project_generator.py](file:///wsl.localhost/Ubuntu/home/balevision/workspace/bleviet/ipcraft/ipcraft/generator/hdl/ipcore_project_generator.py) — Replace 6+ occurrences
- [cli.py](file:///wsl.localhost/Ubuntu/home/balevision/workspace/bleviet/ipcraft/ipcraft/cli.py) — Replace 1–2 occurrences

#### Implementation

```python
# In utils/__init__.py — add:

from enum import Enum

def enum_value(v: Any) -> str:
    """Extract the string value from an Enum member or return str(v).

    Replaces the defensive ``v.value if hasattr(v, 'value') else str(v)``
    pattern used throughout the codebase.
    """
    return v.value if isinstance(v, Enum) else str(v)
```

Then search and replace all occurrences. Example in `ipcore_project_generator.py`:

```python
# BEFORE (appears ~6 times):
mode = iface.mode.value if hasattr(iface.mode, "value") else str(iface.mode)
direction = port.direction.value if hasattr(port.direction, "value") else str(port.direction)

# AFTER:
from ipcraft.utils import enum_value
mode = enum_value(iface.mode)
direction = enum_value(port.direction)
```

#### Validation & Tests

```python
# tests/test_utils.py — add:

from enum import Enum
from ipcraft.utils import enum_value


class Color(str, Enum):
    RED = "red"
    BLUE = "blue"


class TestEnumValue:
    def test_with_enum(self):
        assert enum_value(Color.RED) == "red"

    def test_with_string(self):
        assert enum_value("plain_string") == "plain_string"

    def test_with_int(self):
        assert enum_value(42) == "42"
```

---

### Task 1.4 — Extract Generic List Parser to Eliminate Boilerplate

**Context:** Every `_parse_*` method in the YAML parser follows the same try/except/enumerate pattern.

**Affected Files:**
- [ip_yaml_parser.py](file:///wsl.localhost/Ubuntu/home/balevision/workspace/bleviet/ipcraft/ipcraft/parser/yaml/ip_yaml_parser.py) — Add `_parse_list()`, refactor `_parse_clocks`, `_parse_resets`, `_parse_ports`, `_parse_parameters`

#### Implementation

Add a generic helper method to `YamlIpCoreParser`:

```python
# In ip_yaml_parser.py — add to YamlIpCoreParser class:

from typing import Callable, TypeVar

T = TypeVar("T")

def _parse_list(
    self,
    data: List[Dict[str, Any]],
    kind: str,
    builder: Callable[[Dict[str, Any]], T],
    file_path: Path,
) -> List[T]:
    """Generic list parser with consistent error handling.

    Args:
        data: List of raw dicts from YAML.
        kind: Human-readable item kind for error messages (e.g. 'clock', 'port').
        builder: Callable that converts one raw dict into a model instance.
        file_path: Source file path for error context.

    Returns:
        List of parsed model instances.
    """
    results = []
    for idx, item_data in enumerate(data):
        try:
            results.append(builder(item_data))
        except (KeyError, TypeError, ValueError, ValidationError) as e:
            raise ParseError(f"Error parsing {kind}[{idx}]: {e}", file_path)
    return results
```

Then refactor each parse method. Example for `_parse_clocks`:

```python
# BEFORE (14 lines):
def _parse_clocks(self, data, file_path):
    clocks = []
    for idx, clock_data in enumerate(data):
        try:
            clocks.append(Clock(**self._filter_none({
                "name": clock_data.get("name"),
                "logical_name": clock_data.get("logicalName", "CLK"),
                # ... etc
            })))
        except (KeyError, TypeError, ValueError, ValidationError) as e:
            raise ParseError(f"Error parsing clock[{idx}]: {e}", file_path)
    return clocks

# AFTER (7 lines):
def _parse_clocks(self, data, file_path):
    def build_clock(d):
        return Clock(**self._filter_none({
            "name": d.get("name"),
            "logical_name": d.get("logicalName", "CLK"),
            "direction": d.get("direction", "in"),
            "frequency": d.get("frequency"),
            "description": d.get("description"),
        }))
    return self._parse_list(data, "clock", build_clock, file_path)
```

Apply the same pattern to `_parse_resets`, `_parse_ports`, `_parse_bus_interfaces`, `_parse_parameters`.

#### Validation & Tests

```python
# tests/parser/test_parse_list_helper.py

import pytest
from ipcraft.parser.yaml.ip_yaml_parser import YamlIpCoreParser
from ipcraft.parser.yaml.errors import ParseError
from pathlib import Path


class TestParseListHelper:
    def setup_method(self):
        self.parser = YamlIpCoreParser()
        self.dummy_path = Path("/test/dummy.yml")

    def test_parse_list_success(self):
        data = [{"v": 1}, {"v": 2}]
        result = self.parser._parse_list(
            data, "item", lambda d: d["v"], self.dummy_path
        )
        assert result == [1, 2]

    def test_parse_list_error_includes_index(self):
        data = [{"v": 1}, {"bad": "no_key"}]
        with pytest.raises(ParseError, match=r"item\[1\]"):
            self.parser._parse_list(
                data, "item", lambda d: d["v"], self.dummy_path
            )

    def test_parse_list_empty(self):
        result = self.parser._parse_list([], "item", lambda d: d, self.dummy_path)
        assert result == []
```

---

## Phase 2 — 🟡 Medium Priority: Readability & Maintainability

---

### Task 2.1 — Fix CLI Naming (`ipcore` → `ipcraft`)

**Affected Files:**
- [cli.py](file:///wsl.localhost/Ubuntu/home/balevision/workspace/bleviet/ipcraft/ipcraft/cli.py)

#### Implementation

```diff
-"""
-ipcore - IP Core scaffolding and generation tool.
-
-Usage:
-    python scripts/ipcore.py generate my_core.ip.yml --output ./generated
-    python scripts/ipcore.py generate my_core.ip.yml --json --progress  # VS Code mode
-    python scripts/ipcore.py parse my_core.vhd --output my_core.ip.yml
+"""
+ipcraft - IP Core scaffolding and generation tool.
+
+Usage:
+    ipcraft generate my_core.ip.yml --output ./generated
+    ipcraft generate my_core.ip.yml --json --progress  # VS Code mode
+    ipcraft parse my_core.vhd --output my_core.ip.yml

 # Line 265:
-    parser = argparse.ArgumentParser(prog="ipcore", ...)
+    parser = argparse.ArgumentParser(prog="ipcraft", ...)
```

#### Validation

```bash
# Run CLI help and verify the output says "ipcraft":
uv run ipcraft --help
# Expected: "usage: ipcraft [-h] {generate,parse,list-buses} ..."
```

---

### Task 2.2 — Move `_filter_none` to `utils/`

**Affected Files:**
- [utils/\_\_init\_\_.py](file:///wsl.localhost/Ubuntu/home/balevision/workspace/bleviet/ipcraft/ipcraft/utils/__init__.py) — Add function
- [ip_yaml_parser.py](file:///wsl.localhost/Ubuntu/home/balevision/workspace/bleviet/ipcraft/ipcraft/parser/yaml/ip_yaml_parser.py) — Import from utils

#### Implementation

```python
# In utils/__init__.py — add:

def filter_none(data: dict) -> dict:
    """Remove keys with None values from a dictionary.

    Required for Pydantic v2 compatibility: passing None explicitly
    to fields with defaults causes validation errors. Filtering None
    values lets Pydantic use its own defaults.
    """
    return {k: v for k, v in data.items() if v is not None}
```

Then in `ip_yaml_parser.py`:
```python
# Replace:
#   @staticmethod
#   def _filter_none(data: Dict[str, Any]) -> Dict[str, Any]:
#       ...
# With:
from ipcraft.utils import filter_none

# And update all internal calls:
#   self._filter_none({...})   →   filter_none({...})
```

> [!IMPORTANT]
> The parser **mixins** (`MemoryMapParserMixin`, `FileSetParserMixin`) also call `self._filter_none()`. These must also be updated to import and call `filter_none()` directly.

#### Validation & Tests

```python
# tests/test_utils.py — add:

from ipcraft.utils import filter_none


class TestFilterNone:
    def test_removes_none_values(self):
        assert filter_none({"a": 1, "b": None, "c": "x"}) == {"a": 1, "c": "x"}

    def test_preserves_falsy_non_none(self):
        assert filter_none({"a": 0, "b": "", "c": False, "d": None}) == {
            "a": 0, "b": "", "c": False
        }

    def test_empty_dict(self):
        assert filter_none({}) == {}

    def test_all_none(self):
        assert filter_none({"a": None, "b": None}) == {}
```

---

### Task 2.3 — Add Mixin Typing Protocols

**Context:** Mixins call methods defined on sibling classes without any type contract, making IDE refactoring unreliable.

**Affected Files:**
- New file: `ipcraft/generator/hdl/_protocols.py`
- New file: `ipcraft/parser/yaml/_protocols.py`
- [testbench_generator.py](file:///wsl.localhost/Ubuntu/home/balevision/workspace/bleviet/ipcraft/ipcraft/generator/hdl/testbench_generator.py), [vendor_generator.py](file:///wsl.localhost/Ubuntu/home/balevision/workspace/bleviet/ipcraft/ipcraft/generator/hdl/vendor_generator.py), [fileset_manager.py](file:///wsl.localhost/Ubuntu/home/balevision/workspace/bleviet/ipcraft/ipcraft/generator/hdl/fileset_manager.py) — Type-hint `self`

#### Implementation

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

Then use it in each mixin:

```python
# In testbench_generator.py:
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._protocols import GeneratorHost

class TestbenchGenerationMixin:
    # Type-hint self in method signatures for IDE support:
    def generate_cocotb_test(self: GeneratorHost, ip_core: IpCore, bus_type: str = "axil") -> str:
        template = self.env.get_template("cocotb_test.py.j2")
        context = self._get_template_context(ip_core, bus_type)
        return template.render(**context)
```

```python
# NEW FILE: ipcraft/parser/yaml/_protocols.py

from __future__ import annotations
from typing import Any, Dict, Protocol

from ipcraft.model.memory_map import AccessType


class ParserHost(Protocol):
    """Protocol for the host class that parser mixins expect."""

    @staticmethod
    def _filter_none(data: Dict[str, Any]) -> Dict[str, Any]: ...

    @staticmethod
    def _parse_access(access: Any) -> AccessType: ...
```

#### Validation

```bash
# Run mypy to verify protocols catch real errors:
uv run mypy ipcraft/generator/hdl/ ipcraft/parser/yaml/
```

---

### Task 2.4 — Clean Up Empty/Placeholder Modules

**Affected Files:**
- [ipcraft/\_\_init\_\_.py](file:///wsl.localhost/Ubuntu/home/balevision/workspace/bleviet/ipcraft/ipcraft/__init__.py)
- [converter/\_\_init\_\_.py](file:///wsl.localhost/Ubuntu/home/balevision/workspace/bleviet/ipcraft/ipcraft/converter/__init__.py)

#### Implementation

```python
# ipcraft/__init__.py
"""IPCraft — Python library for IP Core development and VHDL generation."""

__version__ = "0.1.0"
```

```python
# converter/__init__.py
"""Format converters (e.g. IP-XACT ↔ ipcraft YAML).

This module is a placeholder for future converter implementations.
"""
```

#### Validation

```python
# Quick smoke test:
# tests/test_package_init.py

def test_version_exported():
    import ipcraft
    assert hasattr(ipcraft, "__version__")
    assert ipcraft.__version__ == "0.1.0"
```

---

### Task 2.5 — Standardize on `pathlib.Path` (Remove `os.path`)

**Affected Files:**
- [cli.py](file:///wsl.localhost/Ubuntu/home/balevision/workspace/bleviet/ipcraft/ipcraft/cli.py) — Replace `os.path` calls

#### Implementation

```python
# cli.py — cmd_generate function

# BEFORE:
output_base = args.output or os.path.dirname(args.input)
# ...
full_path = os.path.join(output_base, filepath)
os.makedirs(os.path.dirname(full_path), exist_ok=True)
# ...
gen.update_ipcore_filesets(os.path.abspath(args.input), ...)

# AFTER:
from pathlib import Path
output_base = Path(args.output) if args.output else Path(args.input).parent
# ...
full_path = output_base / filepath
full_path.parent.mkdir(parents=True, exist_ok=True)
# ...
gen.update_ipcore_filesets(str(Path(args.input).resolve()), ...)
```

Also remove the `import os` at the top of `cli.py` if no other `os.*` calls remain.

#### Validation

```bash
# Run existing tests — CLI path handling should be covered by generate/parse tests:
uv run pytest ipcraft/tests/ -v -k "test_"
```

---

### Task 2.6 — Remove Over-Defensive `getattr` Chains in Generator

**Context:** `ipcore_project_generator.py` uses `getattr(reg, "address_offset", None)` on Pydantic models that always define these fields.

**Affected Files:**
- [ipcore_project_generator.py](file:///wsl.localhost/Ubuntu/home/balevision/workspace/bleviet/ipcraft/ipcraft/generator/hdl/ipcore_project_generator.py)

#### Implementation

```python
# In _prepare_registers, process_register function:

# BEFORE:
current_offset = base_offset + (
    getattr(reg, "address_offset", None) or getattr(reg, "offset", None) or 0
)
reg_name = reg.name if hasattr(reg, "name") else "REG"

# AFTER:
current_offset = base_offset + (reg.address_offset or 0)
reg_name = reg.name
```

Apply similar cleanup to all `getattr(block, "base_address", 0)` calls — use `block.base_address or 0` instead, since these are defined Pydantic fields with `Optional[int]` and `default=0`.

#### Validation

```bash
# Run generator tests to ensure no regression:
uv run pytest ipcraft/tests/generator/ -v
```

---

### Task 2.7 — Add Specific Exceptions for Bus I/O Errors

**Context:** `register.py` catches bare `Exception` during RMW operations, which can hide bugs.

**Affected Files:**
- [register.py](file:///wsl.localhost/Ubuntu/home/balevision/workspace/bleviet/ipcraft/ipcraft/runtime/register.py) — Define `BusIOError`, catch it specifically

#### Implementation

```python
# In runtime/register.py — add at module level:

class BusIOError(IOError):
    """Raised when a bus read/write operation fails."""
    pass
```

Update `AbstractBusInterface` and `AsyncBusInterface` docstrings to document that implementations should raise `BusIOError`.

Then update the RMW catch blocks (4 locations):

```python
# BEFORE:
except Exception:
    logger.warning("Failed to read register '%s'...", self.name)

# AFTER:
except BusIOError as exc:
    logger.warning(
        "Failed to read register '%s' during RMW: %s; "
        "proceeding with current_value=0 — other fields may be corrupted",
        self.name,
        exc,
    )
```

Export `BusIOError` from `runtime/__init__.py`.

#### Validation & Tests

```python
# tests/test_register.py — add:

import pytest
from unittest.mock import MagicMock
from ipcraft.runtime.register import Register, BitField, BusIOError


class FailingBus:
    """Bus that raises BusIOError on read."""
    def read_word(self, address):
        raise BusIOError("bus timeout")
    def write_word(self, address, data):
        pass


class TestRMWWithBusError:
    def test_write_field_logs_warning_on_bus_error(self, caplog):
        fields = [BitField(name="ENABLE", offset=0, width=1, access="rw")]
        reg = Register("CTRL", 0x00, FailingBus(), fields)

        # Should not raise — warning is logged and write proceeds
        import logging
        with caplog.at_level(logging.WARNING):
            reg.write_field("ENABLE", 1)

        assert "bus timeout" in caplog.text

    def test_bus_io_error_is_ioerror(self):
        assert issubclass(BusIOError, IOError)
```

---

### Task 2.8 — Clean Up Unused Imports in HDL Parsers

**Affected Files:**
- [vhdl_parser.py](file:///wsl.localhost/Ubuntu/home/balevision/workspace/bleviet/ipcraft/ipcraft/parser/hdl/vhdl_parser.py)
- [verilog_parser.py](file:///wsl.localhost/Ubuntu/home/balevision/workspace/bleviet/ipcraft/ipcraft/parser/hdl/verilog_parser.py)

#### Implementation

Run `flake8` to identify unused imports, then remove them:

```bash
uv run flake8 ipcraft/parser/hdl/vhdl_parser.py --select F401
uv run flake8 ipcraft/parser/hdl/verilog_parser.py --select F401
```

Expected removals from `vhdl_parser.py`:
```python
# Remove these unused pyparsing imports:
Forward, Keyword, LineEnd, StringEnd, White, QuotedString,
cppStyleComment, delimitedList, Regex
```

Expected removals from `verilog_parser.py`:
```python
# Remove these unused pyparsing imports:
Forward, CharsNotIn, cppStyleComment, pythonStyleComment, QuotedString
```

#### Validation

```bash
# Verify no imports are flagged after cleanup:
uv run flake8 ipcraft/parser/hdl/ --select F401
# Expected: no output (clean)

# Run parser tests to ensure nothing broke:
uv run pytest ipcraft/tests/parser/ -v
```

---

### Task 2.9 — Move `test_vhdl_ai_parser.py` into Test Directory

**Affected Files:**
- `ipcraft/tests/test_vhdl_ai_parser.py` → move to `ipcraft/tests/parser/test_vhdl_ai_parser.py`

#### Implementation

```bash
mv ipcraft/tests/test_vhdl_ai_parser.py ipcraft/tests/parser/test_vhdl_ai_parser.py
```

Ensure `ipcraft/tests/parser/__init__.py` exists (create empty if missing).

#### Validation

```bash
uv run pytest ipcraft/tests/parser/test_vhdl_ai_parser.py -v
```

---

### Task 2.10 — Fix `VhdlLlmParser` Path Hardcoding

**Affected Files:**
- [vhdl_ai_parser.py](file:///wsl.localhost/Ubuntu/home/balevision/workspace/bleviet/ipcraft/ipcraft/parser/hdl/vhdl_ai_parser.py)

#### Implementation

Replace the hardcoded path with an environment variable lookup:

```python
# BEFORE:
llm_core_path = Path(__file__).parents[4] / "llm-playground" / "llm_core"

# AFTER:
import os
llm_core_path_env = os.environ.get("LLM_CORE_PATH")
if llm_core_path_env:
    llm_core_path = Path(llm_core_path_env)
else:
    # Fallback: try common relative location for dev environments
    llm_core_path = Path(__file__).parents[4] / "llm-playground" / "llm_core"
```

Document the environment variable in `README.md` under a "Configuration" section.

#### Validation

```bash
# Verify the parser still initializes without the env var (graceful fallback):
python -c "from ipcraft.parser.hdl.vhdl_ai_parser import VHDLAiParser; p = VHDLAiParser()"
# Expected: no crash (LLM features disabled warning is OK)
```

---

## Phase 3 — 🟢 Low Priority: Elegance Polish

---

### Task 3.1 — Remove Redundant `count` Validator from `ArrayConfig`

**Affected Files:**
- [bus.py](file:///wsl.localhost/Ubuntu/home/balevision/workspace/bleviet/ipcraft/ipcraft/model/bus.py)

#### Implementation

```python
# REMOVE this entire block (the Field(..., ge=1) already enforces it):

@field_validator("count")
@classmethod
def validate_count(cls, v: int) -> int:
    """Ensure count is positive."""
    if v < 1:
        raise ValueError("Array count must be at least 1")
    return v
```

#### Validation

```python
# tests/model/test_bus.py — add:

def test_array_config_rejects_zero_count():
    from pydantic import ValidationError
    from ipcraft.model.bus import ArrayConfig
    with pytest.raises(ValidationError):
        ArrayConfig(count=0, naming_pattern="CH{index}", physical_prefix_pattern="ch{index}_")
```

---

### Task 3.2 — Simplify `_find_by_name` with `next()`

**Affected Files:**
- [core.py](file:///wsl.localhost/Ubuntu/home/balevision/workspace/bleviet/ipcraft/ipcraft/model/core.py)

#### Implementation

```python
# Replace:
@staticmethod
def _find_by_name(items: Sequence[NamedItem], name: str) -> Optional[NamedItem]:
    """Return the first item with a matching ``name`` attribute."""
    for item in items:
        if getattr(item, "name", None) == name:
            return item
    return None

# With:
@staticmethod
def _find_by_name(items: Sequence[NamedItem], name: str) -> Optional[NamedItem]:
    """Return the first item with a matching ``name`` attribute."""
    return next((item for item in items if getattr(item, "name", None) == name), None)
```

#### Validation

```bash
uv run pytest ipcraft/tests/model/ -v
```

---

### Task 3.3 — Cache `AddressBlock.end_address` Range Parsing

**Affected Files:**
- [memory_map.py](file:///wsl.localhost/Ubuntu/home/balevision/workspace/bleviet/ipcraft/ipcraft/model/memory_map.py)

#### Implementation

Add a resolved range field computed once at init:

```python
class AddressBlock(FlexibleModel):
    # ... existing fields ...

    # Internal: resolved range in bytes (computed at init)
    _resolved_range: Optional[int] = None

    def model_post_init(self, __context: Any) -> None:
        """Resolve string range to integer once at init time."""
        if self.range is not None:
            self._resolved_range = self._parse_range(self.range)

    @staticmethod
    def _parse_range(range_val) -> int:
        """Convert range value (int or string like '4K') to bytes."""
        if isinstance(range_val, int):
            return range_val
        suffix = range_val[-1].upper()
        multipliers = {"K": 1024, "M": 1024**2, "G": 1024**3}
        if suffix in multipliers:
            return int(range_val[:-1]) * multipliers[suffix]
        return int(range_val)

    @property
    def end_address(self) -> int:
        size = self._resolved_range if self._resolved_range is not None else 0
        return self.base_address + size
```

#### Validation

```python
# tests/model/test_memory_map.py — add:

class TestAddressBlockRangeParsing:
    def test_integer_range(self):
        block = AddressBlock(name="test", range=256)
        assert block.end_address == 256

    def test_string_range_k(self):
        block = AddressBlock(name="test", range="4K")
        assert block.end_address == 4096

    def test_string_range_m(self):
        block = AddressBlock(name="test", range="1M")
        assert block.end_address == 1048576

    def test_no_range(self):
        block = AddressBlock(name="test")
        assert block.end_address == 0
```

---

### Task 3.4 — Add Deprecation Warnings to Legacy Aliases

**Affected Files:**
- [ipcore_project_generator.py](file:///wsl.localhost/Ubuntu/home/balevision/workspace/bleviet/ipcraft/ipcraft/generator/hdl/ipcore_project_generator.py)

#### Implementation

Replace the bare alias with a deprecation pattern (matching the `register.py` precedent):

```python
# BEFORE:
VHDLGenerator = IpCoreProjectGenerator

def generate_vhdl(ip_core, bus_type="axil"):
    generator = IpCoreProjectGenerator()
    return generator.generate_all(ip_core, bus_type)

# AFTER:
import warnings

def __getattr__(name):
    if name == "VHDLGenerator":
        warnings.warn(
            "'VHDLGenerator' is deprecated. Use 'IpCoreProjectGenerator' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return IpCoreProjectGenerator
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


def generate_vhdl(ip_core: IpCore, bus_type: str = "axil") -> Dict[str, str]:
    """Deprecated. Use ``IpCoreProjectGenerator().generate_all()`` instead."""
    warnings.warn(
        "'generate_vhdl()' is deprecated. Use IpCoreProjectGenerator().generate_all().",
        DeprecationWarning,
        stacklevel=2,
    )
    return IpCoreProjectGenerator().generate_all(ip_core, bus_type)
```

#### Validation

```python
# tests/generator/test_deprecations.py

import pytest
import warnings

def test_vhdl_generator_alias_warns():
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        from ipcraft.generator.hdl.ipcore_project_generator import VHDLGenerator
        assert len(w) == 1
        assert issubclass(w[0].category, DeprecationWarning)
        assert "VHDLGenerator" in str(w[0].message)
```

---

### Task 3.5 — Remove No-Op `_process_port_list` from `VHDLParser`

**Affected Files:**
- [vhdl_parser.py](file:///wsl.localhost/Ubuntu/home/balevision/workspace/bleviet/ipcraft/ipcraft/parser/hdl/vhdl_parser.py)

#### Implementation

Remove the method and the line that registers it:

```python
# REMOVE:
self.port_list.set_parse_action(self._process_port_list)

# REMOVE:
def _process_port_list(self, s, loc, tokens):
    """Parse action to process port list and extract all ports."""
    return tokens
```

#### Validation

```bash
uv run pytest ipcraft/tests/parser/ -v
```

---

## Phase 4 — 🧪 Final Validation

After all tasks are complete, run the full test and quality suite:

```bash
# Full test suite
uv run pytest -v

# Coverage report
uv run pytest --cov=ipcraft --cov-report=term-missing

# Lint
uv run flake8 ipcraft

# Type checking
uv run mypy ipcraft

# All quality checks
make quality
```

### Acceptance Criteria

| Check | Target |
|-------|--------|
| All existing tests pass | ✅ |
| No new flake8 warnings | ✅ |
| `mypy` passes with mixin protocols | ✅ |
| `grep -r "hasattr.*value" ipcraft/` returns 0 non-test hits | ✅ |
| `grep -r "yaml.safe_load" ipcraft/` only in `parser/yaml/` and `model/bus_library.py` | ✅ |
| `grep -r "ipcore" ipcraft/cli.py` returns 0 hits | ✅ |
| Bus definitions loaded only once (verify with breakpoint or logging) | ✅ |
