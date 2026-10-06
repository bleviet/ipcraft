"""Verilog / SystemVerilog module importer (port of ``parser/VerilogParser.ts``)."""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

from ..jsutil import js_yaml_dump
from ..widthexpr import parse as parse_width_expr
from ..widthexpr import strip_redundant_outer_parens
from .vhdl import (
    IP_CORE_FORMAT_VERSION,
    classify_clocks_resets,
    detect_bus_interfaces,
    parse_parameter_value,
    port_to_dict,
)

_TYPE_KW = re.compile(
    r"^(?:(?:wire|reg|logic|bit|tri|supply0|supply1|wand|wor|triand|trior|tri0|tri1|trireg|integer|real|realtime|"
    r"time|shortint|int|longint|byte|shortreal|signed|unsigned|automatic|var)\s+)+", re.IGNORECASE)


def strip_comments(content: str) -> str:
    result = re.sub(r"/\*[\s\S]*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), content)
    return "\n".join(re.sub(r"//.*$", "", line) for line in result.split("\n"))


def extract_module_name(content: str) -> Optional[str]:
    m = re.search(r"\bmodule\s+(\w+)", content, re.IGNORECASE)
    return m.group(1) if m else None


def extract_paren_block(content: str, open_idx: int) -> Optional[str]:
    if open_idx >= len(content) or content[open_idx] != "(":
        return None
    depth = 0
    for i in range(open_idx, len(content)):
        if content[i] == "(":
            depth += 1
        elif content[i] == ")":
            depth -= 1
            if depth == 0:
                return content[open_idx + 1:i]
    return None


def split_by_comma(block: str) -> List[str]:
    entries: List[str] = []
    depth = 0
    current = ""
    for ch in block:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            if current.strip():
                entries.append(current.strip())
            current = ""
        else:
            current += ch
    if current.strip():
        entries.append(current.strip())
    return entries


def _unquote_verilog_string_literal(raw: str) -> Optional[str]:
    if len(raw) < 2 or raw[0] != '"' or raw[-1] != '"':
        return None
    result = ""
    i = 1
    while i < len(raw) - 1:
        if raw[i] == "\\" and i + 1 < len(raw) - 1:
            nxt = raw[i + 1]
            result += nxt if nxt in ('"', "\\") else f"\\{nxt}"
            i += 2
            continue
        if raw[i] == '"':
            return None
        result += raw[i]
        i += 1
    return result


def _unquote_verilog_value(raw: str) -> str:
    u = _unquote_verilog_string_literal(raw)
    return u if u is not None else raw


def _parse_parameter_block(block: str) -> List[dict]:
    params: List[dict] = []
    seen = set()
    for entry in split_by_comma(block):
        trimmed = entry.strip()
        if not trimmed:
            continue
        rest = re.sub(r"^\s*(parameter|localparam)\s+", "", trimmed, flags=re.IGNORECASE)
        eq = rest.find("=")
        before_eq = rest if eq == -1 else rest[:eq]
        is_vector = bool(re.search(r"\[[^\]]+\]", before_eq))
        name = re.sub(r"^(?:(?:int|integer|logic|bit|reg|wire|real|realtime|time|string|byte|shortint|longint|signed|unsigned)\s+)+",
                      "", before_eq, flags=re.IGNORECASE)
        name = re.sub(r"^\s*\[[^\]]*\]\s*", "", name).strip()
        raw_value = None if eq == -1 else (rest[eq + 1:].strip() or None)
        value = _unquote_verilog_value(raw_value) if raw_value is not None else None
        if not name or not re.match(r"^\w+$", name) or name in seen:
            continue
        seen.add(name)
        params.append({"name": name, "type": "integer", "value": value, "isVector": is_vector})
    return params


def _extract_hash_parameters(content: str) -> List[dict]:
    mod = re.search(r"\bmodule\s+\w+", content, re.IGNORECASE)
    if not mod:
        return []
    after = content[mod.end():]
    hm = re.match(r"^[^(;]*#\s*\(", after)
    if not hm:
        return []
    block = extract_paren_block(after, len(hm.group(0)) - 1)
    if not block:
        return []
    return _parse_parameter_block(block)


def _extract_body_parameters(content: str) -> List[dict]:
    params: List[dict] = []
    seen = set()
    rx = re.compile(r"\bparameter\b\s+((?:(?:int|integer|logic|bit|reg|wire|real|signed|unsigned|byte|shortint|longint)\s+)*"
                    r"(?:\[[^\]]*\]\s*)?)(\w+)\s*=\s*([^;,)]+)", re.IGNORECASE)
    for m in rx.finditer(content):
        type_dims, name = m.group(1), m.group(2)
        val = _unquote_verilog_value(m.group(3).strip())
        if name not in seen:
            seen.add(name)
            params.append({"name": name, "type": "integer", "value": val,
                           "isVector": bool(re.search(r"\[[^\]]+\]", type_dims))})
    return params


def extract_parameters(content: str) -> List[dict]:
    hashed = _extract_hash_parameters(content)
    return hashed if hashed else _extract_body_parameters(content)


def _extract_width(range_str: str) -> Any:
    s = range_str.strip()
    m = re.match(r"^(\d+)\s*:\s*(\d+)$", s)
    if m:
        return abs(int(m.group(1)) - int(m.group(2))) + 1
    m1 = re.match(r"^(.+?)\s*-\s*1\s*:\s*0$", s)
    m2 = re.match(r"^(.+?)\s*:\s*0$", s)
    prefix = (m1.group(1) if m1 else (m2.group(1) if m2 else None))
    prefix = prefix.strip() if prefix else None
    if not prefix:
        return None
    unwrapped = strip_redundant_outer_parens(prefix)
    clog2 = re.match(r"^\$clog2\s*\(", unwrapped, re.IGNORECASE)
    if clog2:
        inner = extract_paren_block(unwrapped, len(clog2.group(0)) - 1)
        fully = inner is not None and len(clog2.group(0)) + len(inner) + 1 == len(unwrapped)
        if fully:
            inner_expr = inner.strip()
            if parse_width_expr(inner_expr):
                return f"clog2({inner_expr})"
        return None
    return unwrapped if parse_width_expr(unwrapped) else None


def extract_ports(content: str) -> List[dict]:
    ports: List[dict] = []
    seen = set()
    hits = [(m.start(), m.group(1)) for m in re.finditer(r"\b(input|output|inout)\b", content, re.IGNORECASE)]
    for i, (start, d) in enumerate(hits):
        end = hits[i + 1][0] if i + 1 < len(hits) else len(content)
        segment = content[start:end]
        direction = "out" if d.lower() == "output" else "inout" if d.lower() == "inout" else "in"
        rest = re.sub(r"^(input|output|inout)\s+", "", segment, flags=re.IGNORECASE)
        rest = _TYPE_KW.sub("", rest, count=1)
        width: Any = 1
        dim = re.match(r"^\s*(\[([^\]]*)\])\s*", rest)
        if dim:
            width = _extract_width(dim.group(2))
            rest = rest[len(dim.group(0)):]
        chunk_m = re.match(r"^([^;)\n]*)", rest)
        name_chunk = chunk_m.group(1) if chunk_m else ""
        for part in name_chunk.split(","):
            nm = re.match(r"^\s*(\w+)", part)
            if nm and nm.group(1) and nm.group(1) not in seen:
                seen.add(nm.group(1))
                ports.append({"name": nm.group(1), "direction": direction, "type": "wire", "width": width})
    return ports


def extract_verilog_interface(content: str) -> Dict[str, Any]:
    cleaned = strip_comments(content)
    return {"moduleName": extract_module_name(cleaned), "parameters": extract_parameters(cleaned),
            "ports": extract_ports(cleaned)}


def _normalize_param_type(type_: str) -> str:
    t = type_.lower().strip()
    return t if t in ("string", "boolean") else "integer"


def parse_verilog_text(content: str, file_path: str, options: Optional[dict] = None) -> dict:
    options = options or {}
    cleaned = strip_comments(content)
    module = extract_module_name(cleaned)
    if not module:
        raise ValueError("No Verilog/SystemVerilog module declaration found in file")
    file_type = "systemverilog" if file_path.endswith(".sv") else "verilog"
    parameters = extract_parameters(cleaned)
    ports = extract_ports(cleaned)
    clock_reset = classify_clocks_resets(ports)
    bus_detection = detect_bus_interfaces(ports, clock_reset, options.get("busLibrary")) if options.get("detectBus") is not False else None
    excluded = set()
    if bus_detection:
        excluded |= bus_detection["busPortNames"]
    excluded |= {c["name"] for c in clock_reset["clocks"]}
    excluded |= {r["name"] for r in clock_reset["resets"]}
    user_ports = [p for p in ports if p["name"] not in excluded]
    output_dir = options.get("outputDir") or os.path.dirname(os.path.abspath(file_path))
    data: Dict[str, Any] = {
        "apiVersion": IP_CORE_FORMAT_VERSION,
        "vlnv": {"vendor": options.get("vendor") or "user", "library": options.get("library") or "ip",
                 "name": module, "version": options.get("version") or "1.0.0"},
        "description": f"Generated from {os.path.basename(file_path)}",
    }
    sole_reset = clock_reset["resets"][0]["name"] if len(clock_reset["resets"]) == 1 else None
    sole_clock = clock_reset["clocks"][0]["name"] if len(clock_reset["clocks"]) == 1 else None
    if clock_reset["clocks"]:
        data["clocks"] = [({"name": c["name"], "direction": "in", **({"associatedReset": sole_reset} if sole_reset else {})})
                          for c in clock_reset["clocks"]]
    if clock_reset["resets"]:
        data["resets"] = [({"name": r["name"], "direction": "in", "polarity": r["polarity"],
                            **({"associatedClock": sole_clock} if sole_clock else {})}) for r in clock_reset["resets"]]
    if user_ports:
        data["ports"] = [port_to_dict(p) for p in user_ports]
    if bus_detection and bus_detection["busInterfaces"]:
        buses = []
        for bus in bus_detection["busInterfaces"]:
            e = {"name": bus["name"], "type": bus["type"], "mode": bus["mode"], "physicalPrefix": bus["physicalPrefix"]}
            if bus.get("associatedClock"):
                e["associatedClock"] = bus["associatedClock"]
            if bus.get("associatedReset"):
                e["associatedReset"] = bus["associatedReset"]
            for key in ("portWidthOverrides", "portNameOverrides", "portPolarityOverrides"):
                if bus.get(key):
                    e[key] = bus[key]
            buses.append(e)
        data["busInterfaces"] = buses
    warnings: List[str] = []
    if parameters:
        plist = []
        for p in parameters:
            if p.get("isVector"):
                warnings.append(f"Warning: vector parameter detected on parameter '{p['name']}'. "
                                f"Convert to integer for cross-vendor GUI compatibility.")
            e = {"name": p["name"]}
            v = parse_parameter_value(p.get("value"))
            if v is not None:
                e["value"] = v
            e["dataType"] = _normalize_param_type(p["type"])
            plist.append(e)
        data["parameters"] = plist
    rel = os.path.relpath(os.path.abspath(file_path), output_dir)
    data["fileSets"] = [{"name": "RTL_Sources", "description": "RTL source files",
                         "files": [{"path": rel, "type": file_type, "managed": False}]}]
    return {"moduleName": module, "yamlText": js_yaml_dump(data), "warnings": warnings}


def parse_verilog_file(file_path: str, options: Optional[dict] = None) -> dict:
    with open(file_path, encoding="utf-8") as fh:
        return parse_verilog_text(fh.read(), file_path, options)
