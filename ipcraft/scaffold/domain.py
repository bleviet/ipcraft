"""IP-core / memory-map normalization and loading (port of ``domain/parse.ts`` etc.).

Reads canonical camelCase ``.ip.yml`` / ``.mm.yml`` content.  Legacy snake_case input is
converted ahead of time with ``ipcraft migrate``.
"""

from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml




def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def parse_number(value: Any, fallback: float = 0) -> float:
    if _is_num(value):
        return value
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return fallback
        try:
            n = float(int(s, 0)) if re.match(r"^[+-]?(0[xXbBoO])", s) else float(s)
        except ValueError:
            return fallback
        return int(n) if n == int(n) else n
    return fallback


def _num(v: Any, fallback: float = 0) -> Any:
    n = parse_number(v, fallback)
    return int(n) if isinstance(n, float) and n == int(n) else n


def _str(v: Any, default: str = "") -> str:
    return default if v is None else (str(v) if not isinstance(v, bool) else str(v).lower())


def _parse_bits(bits: Any) -> Dict[str, int]:
    if not bits or not isinstance(bits, str):
        return {"offset": 0, "width": 1}
    m = re.search(r"\[(\d+)(?::(\d+))?\]", bits)
    if m:
        high = int(m.group(1))
        low = int(m.group(2)) if m.group(2) else high
        return {"offset": min(low, high), "width": abs(high - low) + 1}
    return {"offset": 0, "width": 1}


def _first(*vals: Any) -> Any:
    for v in vals:
        if v is not None:
            return v
    return None


def normalize_field(raw: dict) -> dict:
    offset = _num(_first(raw.get("offset"), raw.get("bitOffset")), 0)
    width = _num(_first(raw.get("width"), raw.get("bitWidth")), 1)
    if raw.get("bits") and isinstance(raw["bits"], str):
        parsed = _parse_bits(raw["bits"])
        offset, width = parsed["offset"], parsed["width"]
    msb = offset + width - 1
    bits = raw.get("bits") if raw.get("bits") is not None else (f"[{msb}:{offset}]" if width > 1 else f"[{offset}]")
    out = {
        "name": _str(raw.get("name")),
        "bits": str(bits),
        "offset": offset,
        "width": width,
        "access": str(raw["access"]) if raw.get("access") is not None else None,
        "resetValue": _num(_first(raw.get("resetValue"), raw.get("reset")), 0),
        "description": _str(raw.get("description")),
        "enumeratedValues": raw.get("enumeratedValues"),
        "monitorChangeOf": raw.get("monitorChangeOf"),
    }
    return out


def normalize_register(raw: dict, default_reg_width: int) -> dict:
    is_array = raw.get("count") is not None
    size = _num(raw.get("size"), 32)
    reg_width = size if size > 0 else default_reg_width
    fields = [normalize_field(f) for f in raw["fields"]] if isinstance(raw.get("fields"), list) else []
    base = {
        "name": _str(raw.get("name")),
        "offset": _num(_first(raw.get("offset"), raw.get("addressOffset")), 0),
        "size": size,
        "access": str(raw["access"]) if raw.get("access") is not None else None,
        "resetValue": _num(raw.get("resetValue"), 0),
        "description": _str(raw.get("description")),
        "fields": fields,
    }
    if is_array:
        nested = [normalize_register(r, reg_width) for r in raw["registers"]] if isinstance(raw.get("registers"), list) else []
        base.update({
            "__kind": "array",
            "count": max(1, _num(raw.get("count"), 1)),
            "stride": max(1, _num(raw.get("stride"), max(1, reg_width // 8))),
            "registers": nested,
        })
    return base


def normalize_block(raw: dict) -> dict:
    default_reg_width = _num(raw.get("defaultRegWidth"), 32)
    default_reg_bytes = max(1, default_reg_width // 8)
    raw_regs = raw["registers"] if isinstance(raw.get("registers"), list) else []
    regs0 = [normalize_register(r, default_reg_width) for r in raw_regs]
    current = 0
    registers = []
    for idx, reg in enumerate(regs0):
        raw_reg = raw_regs[idx]
        explicit = _first(raw_reg.get("offset"), raw_reg.get("addressOffset"))
        if explicit is not None:
            current = _num(explicit, current)
        offset = current
        if reg.get("__kind") == "array":
            current = offset + reg.get("count", 1) * reg.get("stride", default_reg_bytes)
        else:
            reg_bytes = max(1, reg["size"] // 8) if reg["size"] > 0 else default_reg_bytes
            current = offset + reg_bytes
        registers.append({**reg, "offset": offset})
    return {
        "name": _str(raw.get("name")),
        "baseAddress": _num(_first(raw.get("baseAddress"), raw.get("offset")), 0),
        "range": raw.get("range"),
        "usage": _str(raw.get("usage"), "register") if raw.get("usage") is not None else "register",
        "access": str(raw["access"]) if raw.get("access") is not None else None,
        "description": _str(raw.get("description")),
        "defaultRegWidth": default_reg_width,
        "registers": registers,
    }


def normalize_memory_map(raw_map: dict) -> dict:
    raw_blocks = raw_map["addressBlocks"] if isinstance(raw_map.get("addressBlocks"), list) else []
    return {
        "name": _str(raw_map.get("name")),
        "description": _str(raw_map.get("description")),
        "addressBlocks": [normalize_block(b) for b in raw_blocks],
    }


def normalize_ip_core(root: dict) -> dict:
    def lst(key: str) -> list:
        return root[key] if isinstance(root.get(key), list) else []

    buses = []
    for bus in lst("busInterfaces"):
        pol = bus.get("portPolarityOverrides")
        mode = _str(bus.get("mode")).lower()
        nb: Dict[str, Any] = {
            "name": _str(bus.get("name")),
            "type": _str(bus.get("type")),
            "mode": mode,
            "physicalPrefix": "" if "physicalPrefix" in bus and bus["physicalPrefix"] is None else _str(bus.get("physicalPrefix")),
            "useOptionalPorts": bus.get("useOptionalPorts") if bus.get("useOptionalPorts") is not None else [],
            "portWidthOverrides": bus.get("portWidthOverrides") if bus.get("portWidthOverrides") is not None else {},
        }
        ip_ = bus.get("interfaceProperties")
        if isinstance(ip_, dict):
            nb["interfaceProperties"] = ip_
        if bus.get("portNameOverrides") is not None:
            nb["portNameOverrides"] = bus["portNameOverrides"]
        if isinstance(pol, dict):
            nb["portPolarityOverrides"] = pol
        if bus.get("absentPorts") is not None:
            nb["absentPorts"] = bus["absentPorts"]
        if bus.get("conduitPorts") is not None:
            nb["conduitPorts"] = bus["conduitPorts"]
        nb["associatedClock"] = _str(bus.get("associatedClock"))
        nb["associatedReset"] = _str(bus.get("associatedReset"))
        if bus.get("endianness") in ("big", "little"):
            nb["endianness"] = bus["endianness"]
        arr = bus.get("array")
        if arr:
            nb["array"] = {
                "count": _num(arr.get("count"), 1),
                "indexStart": _num(arr.get("indexStart"), 0),
                "namingPattern": _str(arr.get("namingPattern")),
                "physicalPrefixPattern": _str(arr.get("physicalPrefixPattern")),
            }
        if bus.get("memoryMapRef"):
            nb["memoryMapRef"] = str(bus["memoryMapRef"])
        if isinstance(bus.get("ports"), list):
            nb["ports"] = bus["ports"]
        if bus.get("busTypeVlnv"):
            nb["busTypeVlnv"] = bus["busTypeVlnv"]
        if bus.get("rawPortMaps"):
            nb["rawPortMaps"] = bus["rawPortMaps"]
        buses.append(nb)

    out = dict(root)
    out["vlnv"] = root.get("vlnv") if root.get("vlnv") is not None else {}
    out["description"] = _str(root.get("description"))
    out["author"] = _str(root.get("author"))

    params = []
    for p in lst("parameters"):
        q: Dict[str, Any] = {
            "name": _str(p.get("name")),
            "displayName": str(p["displayName"]) if p.get("displayName") else None,
            "value": _first(p.get("value"), p.get("defaultValue")),
            "dataType": _str(p.get("dataType")),
            "description": str(p["description"]) if p.get("description") else None,
            "min": float_or_int(p["min"]) if p.get("min") is not None else None,
            "max": float_or_int(p["max"]) if p.get("max") is not None else None,
            "allowedValues": p["allowedValues"] if isinstance(p.get("allowedValues"), list) else None,
            "uiPage": str(p["uiPage"]) if p.get("uiPage") else None,
            "uiGroup": str(p["uiGroup"]) if p.get("uiGroup") else None,
        }
        params.append(q)
    out["parameters"] = params

    ports = []
    for p in lst("ports"):
        q = {
            "name": _str(p.get("name")),
            "direction": _str(p.get("direction")),
            "width": p["width"] if p.get("width") is not None else 1,
            "presence": _str(p.get("presence")),
        }
        if p.get("endianness") in ("big", "little"):
            q["endianness"] = p["endianness"]
        ports.append(q)
    out["ports"] = ports
    out["busInterfaces"] = buses

    clocks = []
    for c in lst("clocks"):
        q = {"name": _str(c.get("name"))}
        if "frequency" in c:
            q["frequency"] = c["frequency"]
        if c.get("associatedReset"):
            q["associatedReset"] = str(c["associatedReset"])
        clocks.append(q)
    out["clocks"] = clocks
    resets = []
    for r in lst("resets"):
        q = {"name": _str(r.get("name")), "polarity": _str(r.get("polarity"))}
        if r.get("associatedClock"):
            q["associatedClock"] = str(r["associatedClock"])
        resets.append(q)
    out["resets"] = resets
    out["memoryMaps"] = root.get("memoryMaps")
    subs = []
    for s in lst("subcores"):
        if isinstance(s, str):
            subs.append({"vlnv": s})
        else:
            q = {"vlnv": _str(s.get("vlnv"))}
            if s.get("path"):
                q["path"] = str(s["path"])
            subs.append(q)
    out["subcores"] = subs
    return out


def float_or_int(v: Any) -> Any:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return math.nan
    return int(n) if n == int(n) else n


def resolve_memory_map_imports(memory_maps: Any, base_dir: str) -> Tuple[List[dict], List[str]]:
    """Resolve ``memoryMaps`` imports (port of ``resolveMemoryMapImports``)."""
    errors: List[str] = []
    resolved: List[dict] = []
    if not memory_maps:
        return resolved, errors

    def has_import(v: Any) -> bool:
        return isinstance(v, dict) and isinstance(v.get("import"), str)

    def read(rel: str) -> Any:
        return yaml.safe_load(Path(os.path.abspath(os.path.join(base_dir, rel))).read_text(encoding="utf-8"))

    if not isinstance(memory_maps, list) and has_import(memory_maps):
        rel = memory_maps["import"]
        try:
            parsed = read(rel)
            if isinstance(parsed, list):
                loaded = parsed
            elif isinstance(parsed, dict):
                loaded = [parsed]
            else:
                loaded = []
            return loaded, errors
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Failed to load memory map from {rel}: {exc}")
            return [memory_maps], errors

    entries = memory_maps if isinstance(memory_maps, list) else [memory_maps]
    for entry in entries:
        if has_import(entry):
            rel = entry["import"]
            try:
                parsed = read(rel)
                loaded = (parsed[0] if parsed else {}) if isinstance(parsed, list) else (parsed or {})
                rest = {k: v for k, v in entry.items() if k != "import"}
                resolved.append({**loaded, **rest})
            except Exception as exc:  # noqa: BLE001
                errors.append(f"Failed to load memory map from {rel}: {exc}")
                resolved.append(entry)
        elif entry and isinstance(entry, dict):
            resolved.append(entry)
    return resolved, errors


def title_case_identifier(name: str) -> str:
    s = name.replace("_", " ").lower()
    return re.sub(r"\b\w", lambda m: m.group(0).upper(), s)
