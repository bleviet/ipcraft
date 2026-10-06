"""Small helpers that reproduce JavaScript semantics the ported code relies on."""

from __future__ import annotations

import math
import re
from typing import Any, Optional

import yaml


def js_number(s: str) -> Optional[float]:
    """``Number(s)`` for a string; ``None`` when the result is ``NaN``."""
    s = s.strip()
    if s == "":
        return 0
    try:
        if re.match(r"^[+-]?0[xX][0-9a-fA-F]+$", s) and not re.match(r"^[+-]", s):
            return int(s, 16)
        if re.match(r"^0[bB][01]+$", s):
            return int(s, 2)
        if re.match(r"^0[oO][0-7]+$", s):
            return int(s, 8)
        if not re.match(r"^[+-]?(\d+\.?\d*([eE][+-]?\d+)?|\.\d+([eE][+-]?\d+)?|Infinity)$", s):
            return None
        v = float(s.replace("Infinity", "inf"))
        return int(v) if math.isfinite(v) and v == int(v) and abs(v) < 2**53 else v
    except ValueError:
        return None


def js_finite_number(s: str) -> Optional[float]:
    n = js_number(s)
    return n if n is not None and math.isfinite(n) else None


def js_to_string(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and math.isfinite(v) and v == int(v):
        return str(int(v))
    return str(v)


class _JsYamlDumper(yaml.SafeDumper):
    """PyYAML dumper that approximates js-yaml's block style (indented sequences, no folding)."""

    def increase_indent(self, flow: bool = False, indentless: bool = False):  # noqa: D102
        return super().increase_indent(flow, False)

    def ignore_aliases(self, data: Any) -> bool:  # noqa: D102
        return True


def _represent_none(dumper: yaml.SafeDumper, _data: None):
    return dumper.represent_scalar("tag:yaml.org,2002:null", "null")


_JsYamlDumper.add_representer(type(None), _represent_none)


def js_yaml_dump(data: Any) -> str:
    """Serialize like ``js-yaml``'s ``dump(data, {noRefs: true, sortKeys: false, lineWidth: -1, indent: 2})``."""
    return yaml.dump(data, Dumper=_JsYamlDumper, sort_keys=False, width=2**31 - 1, indent=2,
                     allow_unicode=True, default_flow_style=False)
