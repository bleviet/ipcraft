"""Compilation-order utilities for VHDL / SystemVerilog file sets (port of ``compilationOrder.ts``)."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set

SV_DIRECTIVE_KEYWORDS = {
    "define", "undef", "undefineall", "include", "ifdef", "ifndef", "else", "elsif", "endif", "timescale",
    "default_nettype", "resetall", "celldefine", "endcelldefine", "unconnected_drive", "nounconnected_drive",
    "pragma", "line", "begin_keywords", "end_keywords", "__FILE__", "__LINE__",
}


def _normalize_vhdl_library(logical_name: Optional[str]) -> str:
    n = logical_name.strip().lower() if logical_name else ""
    return n or "work"


def _parse_vhdl(content: str, logical_name: Optional[str] = None):
    declared: List[dict] = []
    referenced: List[dict] = []
    source = re.sub(r'"(?:[^"]|"")*"', " ", content)
    source = re.sub(r"--[^\r\n]*", " ", source).lower()
    current = _normalize_vhdl_library(logical_name)
    resolve = lambda lib: current if lib.lower() == "work" else lib.lower()  # noqa: E731

    def declare(name: str, kind: str) -> None:
        declared.append({"name": name.lower(), "kind": kind, "library": current})

    def reference(lib: str, name: str, kind: str) -> None:
        referenced.append({"name": name.lower(), "kind": kind, "library": resolve(lib)})

    for m in re.finditer(r"\bpackage\s+(?!body\b)(\w+)\s+is\b", source):
        declare(m.group(1), "vhdl-package")
    for m in re.finditer(r"\bentity\s+(\w+)\s+is\b", source):
        declare(m.group(1), "vhdl-entity")
    for m in re.finditer(r"\bcontext\s+(\w+)\s+is\b", source):
        declare(m.group(1), "vhdl-context")
    for m in re.finditer(r"\bpackage\s+body\s+(\w+)\s+is\b", source):
        reference("work", m.group(1), "vhdl-package")
    for m in re.finditer(r"\barchitecture\s+\w+\s+of\s+(\w+)\s+is\b", source):
        reference("work", m.group(1), "vhdl-entity")
    for m in re.finditer(r"\bconfiguration\s+\w+\s+of\s+(\w+)\s+is\b", source):
        reference("work", m.group(1), "vhdl-entity")
    for m in re.finditer(r"\bpackage\s+\w+\s+is\s+new\s+(\w+)\s*\.\s*(\w+)", source):
        reference(m.group(1), m.group(2), "vhdl-package")
    for clause in re.finditer(r"\buse\s+([^;]+);", source):
        for m in re.finditer(r"(?:^|,)\s*(\w+)\s*\.\s*(\w+)", clause.group(1)):
            reference(m.group(1), m.group(2), "vhdl-package")
    for m in re.finditer(r"\bentity\s+(\w+)\s*\.\s*(\w+)", source):
        reference(m.group(1), m.group(2), "vhdl-entity")
    for m in re.finditer(r"\bcontext\s+(\w+)\s*\.\s*(\w+)\s*;", source):
        reference(m.group(1), m.group(2), "vhdl-context")
    return declared, referenced


def _parse_sv(content: str):
    declared: List[dict] = []
    referenced: List[dict] = []
    module_names: List[str] = []
    stripped = re.sub(r'"(?:\\.|[^"\\])*"', " ", content)
    stripped = re.sub(r"/\*[\s\S]*?\*/", " ", stripped)
    stripped = re.sub(r"//[^\r\n]*", " ", stripped)
    for m in re.finditer(r"\bpackage\s+(\w+)\s*(?:#\s*\([^;]*\)\s*)?;", stripped):
        declared.append({"name": m.group(1), "kind": "sv-package"})
    for m in re.finditer(r"\bmodule\s+(\w+)\b", stripped):
        module_names.append(m.group(1))
    for m in re.finditer(r"\b(?:import\s+)?(\w+)\s*::\s*(?:\w+|\*)", stripped):
        referenced.append({"name": m.group(1), "kind": "sv-package"})
    for raw_line in re.split(r"\r?\n", stripped):
        define = re.match(r"^\s*`define\s+(\w+)", raw_line)
        macro_text = raw_line
        if define:
            declared.append({"name": define.group(1), "kind": "macro"})
            macro_text = raw_line[define.end():]
        cond = re.match(r"^\s*`(?:ifdef|ifndef|elsif|undef)\s+(\w+)", raw_line)
        if cond:
            referenced.append({"name": cond.group(1), "kind": "macro"})
        for m in re.finditer(r"`(\w+)", macro_text):
            if m.group(1) not in SV_DIRECTIVE_KEYWORDS:
                referenced.append({"name": m.group(1), "kind": "macro"})
    return declared, referenced, module_names


def extract_vhdl_dependencies(content: str) -> Dict[str, Set[str]]:
    d, r = _parse_vhdl(content)
    return {"declares": {s["name"] for s in d}, "uses": {s["name"] for s in r}}


def extract_sv_dependencies(content: str) -> Dict[str, Set[str]]:
    d, r, mods = _parse_sv(content)
    return {"declares": {s["name"] for s in d} | set(mods), "uses": {s["name"] for s in r}}


def _symbol_key(s: dict) -> str:
    return f"{s['kind']}\0{s.get('library') or ''}\0{s['name']}"


def sort_by_compilation_order(items: List[dict], read_content: Callable[[str], Optional[str]]) -> List[str]:
    if len(items) <= 1:
        return [i["path"] for i in items]
    units = []
    for item in items:
        lang = item["language"]
        if lang not in ("vhdl", "systemverilog", "verilog"):
            units.append({"path": item["path"], "declared": [], "referenced": []})
            continue
        content = item.get("content")
        if content is None:
            try:
                content = read_content(item["path"]) or ""
            except Exception:  # noqa: BLE001
                content = ""
        if lang == "vhdl":
            d, r = _parse_vhdl(content, item.get("logicalName"))
        else:
            d, r, _ = _parse_sv(content)
        units.append({"path": item["path"], "declared": d, "referenced": r})
    return _topo_sort(units)


def _topo_sort(units: List[dict]) -> List[str]:
    decl: Dict[str, dict] = {}
    for u in units:
        for s in u["declared"]:
            decl[_symbol_key(s)] = u
    visited: Set[int] = set()
    visiting: Set[int] = set()
    result: List[str] = []
    cycle = [False]

    def visit(unit: dict) -> None:
        if id(unit) in visited:
            return
        if id(unit) in visiting:
            cycle[0] = True
            return
        visiting.add(id(unit))
        for ref in unit["referenced"]:
            dep = decl.get(_symbol_key(ref))
            if dep is not None and dep is not unit:
                visit(dep)
                if cycle[0]:
                    return
        visiting.discard(id(unit))
        visited.add(id(unit))
        result.append(unit["path"])

    for u in units:
        if id(u) not in visited:
            visit(u)
        if cycle[0]:
            return [x["path"] for x in units]
    return result


def hdl_language_from_path(file_path: str) -> Optional[str]:
    ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
    if ext in ("vhd", "vhdl"):
        return "vhdl"
    if ext in ("sv", "svh"):
        return "systemverilog"
    if ext in ("v", "vh"):
        return "verilog"
    return None


def resolve_file_set_rtl_files(ip_core_data: dict, ip_core_dir: str, file_set_name: str) -> List[dict]:
    file_sets = ip_core_data.get("fileSets")
    if not isinstance(file_sets, list):
        return []
    match = next((e for e in file_sets if e.get("name") == file_set_name), None)
    raw = [f for f in ((match or {}).get("files") or []) if isinstance(f.get("path"), str) and f["path"]]
    if not raw:
        return []
    items = []
    for f in raw:
        explicit = f.get("type") if f.get("type") in ("vhdl", "systemverilog", "verilog") else None
        language = explicit or hdl_language_from_path(f["path"]) or f.get("type") or "unknown"
        items.append({"relPath": f["path"], "type": f.get("type"), "logicalName": f.get("logicalName"),
                      "absPath": os.path.abspath(os.path.join(ip_core_dir, f["path"])), "language": language})
    info = {i["absPath"]: {"path": i["relPath"], "type": i["type"], "logicalName": i["logicalName"]} for i in items}

    def read(p: str) -> Optional[str]:
        try:
            return Path(p).read_text(encoding="utf-8")
        except OSError:
            return None

    sorted_abs = sort_by_compilation_order(
        [{"path": i["absPath"], "language": i["language"], "logicalName": i["logicalName"]} for i in items], read)
    return [info[p] for p in sorted_abs]
