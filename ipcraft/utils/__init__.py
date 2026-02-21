"""Shared utility helpers for ipcraft."""

import re
import sys
import warnings
from pathlib import Path
from typing import Tuple, Any
from enum import Enum

# Try to find ipcraft-spec via package resource or relative path
BUS_DEFINITIONS_PATH = None

# 1. Try importlib (if installed as package)
if sys.version_info >= (3, 9):
    import importlib.resources

    try:
        # Access 'common' directory from 'ipcraft_spec' package
        # Note: 'ipcraft_spec' is the imported package name (normalized from ipcraft-spec)
        ref = (
            importlib.resources.files("ipcraft_spec") / "common" / "bus_definitions.yml"
        )
        if ref.is_file():
            BUS_DEFINITIONS_PATH = ref
    except (ImportError, ModuleNotFoundError):
        pass

# 2. Try relative path (dev environment sibling)
if BUS_DEFINITIONS_PATH is None:
    # utils is in ipcraft/utils/__init__.py
    # Repo root is 2 levels up (ipcraft/ipcraft -> ipcraft)
    # Sibling repo ipcraft-spec is ../ipcraft-spec
    repo_root = Path(__file__).resolve().parent.parent.parent
    sibling_path = repo_root.parent / "ipcraft-spec" / "common" / "bus_definitions.yml"

    if sibling_path.exists():
        BUS_DEFINITIONS_PATH = sibling_path
    else:
        # Fallback to internal path if bundled (e.g. usage in VS Code extension context if copied)
        # or error
        BUS_DEFINITIONS_PATH = (
            repo_root / "ipcraft-spec" / "common" / "bus_definitions.yml"
        )


def parse_bit_range(bits_str: str) -> Tuple[int, int]:
    """Parse bit notation like ``[7:4]`` or ``[0]`` into ``(offset, width)``.

    Args:
        bits_str: Bit notation string.

    Returns:
        Tuple of ``(bit_offset, bit_width)``.

    Raises:
        ValueError: If notation is empty or invalid.
    """
    if not bits_str:
        raise ValueError("Empty bit range notation")

    clean = bits_str.strip().strip("[]").strip()

    match_range = re.fullmatch(r"(\d+)\s*:\s*(\d+)", clean)
    if match_range:
        msb = int(match_range.group(1))
        lsb = int(match_range.group(2))
        if msb < lsb:
            raise ValueError(f"Invalid bit range '{bits_str}': MSB must be >= LSB")
        return lsb, msb - lsb + 1

    match_single = re.fullmatch(r"(\d+)", clean)
    if match_single:
        bit = int(match_single.group(1))
        return bit, 1

    raise ValueError(f"Invalid bit range notation: '{bits_str}'")


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
    canonical = _BUS_TYPE_ALIASES.get(upper, upper)
    if upper in _BUS_TYPE_ALIASES and upper != canonical:
        warnings.warn(
            f"Bus type alias '{raw}' is deprecated. Use '{canonical}' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
    return canonical


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


def enum_value(v: Any) -> str:
    """Extract the string value from an Enum member or return str(v).

    Replaces the defensive ``v.value if hasattr(v, 'value') else str(v)``
    pattern used throughout the codebase.
    """
    return v.value if isinstance(v, Enum) else str(v)


def filter_none(data: dict) -> dict:
    """Remove keys with None values from a dictionary.

    Required for Pydantic v2 compatibility: passing None explicitly
    to fields with defaults causes validation errors. Filtering None
    values lets Pydantic use its own defaults.
    """
    return {k: v for k, v in data.items() if v is not None}
