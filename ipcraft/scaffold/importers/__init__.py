"""Importers that convert vendor / HDL sources into ``.ip.yml`` (and ``.mm.yml``) files.

``import_source`` is the entry point behind ``ipcraft import``; it mirrors the "Import from VHDL /
Platform Designer / Xilinx component.xml" commands of the ipcraft-vscode extension.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

import yaml

from ..loader import (
    SchemaValidationError,
    blocks_generation,
    check_bus_conformance,
    load_bus_library,
    load_ip_core_data,
    normalize_parameter_data_type,  # noqa: F401  (re-exported)
)
from .component_xml import parse_component_xml_file
from .hwtcl import parse_hwtcl_file, resolve_vendor
from .verilog import parse_verilog_file
from .vhdl import parse_vhdl_file

VENDOR_SUBDIRS = {"xilinx", "altera"}


def detect_source_kind(path: str) -> Optional[str]:
    low = os.path.basename(path).lower()
    ext = os.path.splitext(low)[1]
    if ext in (".vhd", ".vhdl"):
        return "vhdl"
    if ext in (".v", ".sv", ".vh", ".svh"):
        return "verilog"
    if low.endswith("_hw.tcl") or ext == ".tcl":
        return "hwtcl"
    if low == "component.xml" or ext == ".xml":
        return "componentxml"
    return None


def rebase_ip_yaml_paths(ip_yaml_text: str, from_dir: str, to_dir: str) -> str:
    """Rewrite ``fileSets[].files[].path`` so each path is relative to ``to_dir`` instead of ``from_dir``."""
    if os.path.abspath(from_dir) == os.path.abspath(to_dir):
        return ip_yaml_text
    data = yaml.safe_load(ip_yaml_text)
    file_sets = data.get("fileSets") if isinstance(data, dict) else None
    if not isinstance(file_sets, list):
        return ip_yaml_text
    changed = False
    for fs in file_sets:
        for f in fs.get("files") or []:
            if f.get("path"):
                abs_path = os.path.abspath(os.path.join(from_dir, f["path"]))
                new_path = os.path.relpath(abs_path, to_dir).replace("\\", "/")
                if new_path != f["path"]:
                    f["path"] = new_path
                    changed = True
    if not changed:
        return ip_yaml_text
    from ..jsutil import js_yaml_dump

    return js_yaml_dump(data, line_width=120)


def check_imported_ip_core(source_path: str, yaml_text: str, library: dict,
                           statically_incomplete: Optional[List[str]] = None) -> Dict[str, Any]:
    """Conformance check of importer output (port of ``importedIpCoreCheck.ts``)."""
    schema_issues: List[dict] = []
    try:
        ip_core = load_ip_core_data(source_path, yaml_text)
    except SchemaValidationError as exc:
        schema_issues = list(exc.issues)
        ip_core = yaml.safe_load(yaml_text)
    report = check_bus_conformance(ip_core, library)
    incomplete = set(statically_incomplete or [])
    has_known_errors = report["hasKnownErrors"]
    if has_known_errors and incomplete:
        filtered = {**ip_core, "busInterfaces": [b for b in (ip_core.get("busInterfaces") or []) if b.get("name", "") not in incomplete]}
        has_known_errors = check_bus_conformance(filtered, library)["hasKnownErrors"]
    return {**report, "hasKnownErrors": has_known_errors, "issues": schema_issues + report["issues"]}


def import_source(source_path: str, options: Optional[dict] = None) -> Dict[str, Any]:
    """Convert ``source_path`` to ``.ip.yml`` text (+ optional ``.mm.yml``).

    Returns ``{"kind", "files": [{"name", "dir", "content"}], "warnings", "report", "summary"}``.
    ``files[*].dir`` is the directory the file belongs in (the source directory, except for a
    ``component.xml`` inside ``xilinx/`` or ``altera/`` which goes one level up).
    """
    options = dict(options or {})
    kind = detect_source_kind(source_path)
    if kind is None:
        raise ValueError(f"Unsupported source file '{source_path}': expected .vhd/.vhdl, .v/.sv, *_hw.tcl or component.xml")
    src_dir = os.path.dirname(os.path.abspath(source_path))
    library = load_bus_library(source_path, {}, options.get("busLibraryDirs"))
    vendor, lib_name, version = options.get("vendor"), options.get("library"), options.get("version")
    warnings: List[str] = []
    incomplete: Optional[List[str]] = None
    files: List[dict] = []

    if kind in ("vhdl", "verilog"):
        parse = parse_vhdl_file if kind == "vhdl" else parse_verilog_file
        result = parse(source_path, {"detectBus": options.get("detectBus", True), "busLibrary": library, "vendor": vendor,
                                     "library": lib_name, "version": version, "outputDir": options.get("outputDir") or src_dir})
        warnings.extend(result.get("warnings") or [])
        name = result.get("entityName") or result.get("moduleName")
        base = os.path.splitext(os.path.basename(source_path))[0]
        files.append({"name": f"{base}.ip.yml", "dir": options.get("outputDir") or src_dir, "content": result["yamlText"]})
    elif kind == "hwtcl":
        result = parse_hwtcl_file(source_path, {"busLibrary": library, "library": lib_name, "vendor": resolve_vendor(vendor),
                                                "outputDir": options.get("outputDir") or src_dir})
        warnings.extend(result.get("warnings") or [])
        incomplete = result.get("staticallyIncompleteInterfaces")
        base = re.sub(r"\.tcl$", "", re.sub(r"_hw\.tcl$", "", os.path.basename(source_path), flags=re.IGNORECASE), flags=re.IGNORECASE)
        files.append({"name": f"{base}.ip.yml", "dir": options.get("outputDir") or src_dir, "content": result["yamlText"]})
    else:
        result = parse_component_xml_file(source_path, {"busLibrary": library, "library": lib_name})
        is_vendor_subdir = os.path.basename(src_dir).lower() in VENDOR_SUBDIRS
        out_dir = options.get("outputDir") or (os.path.dirname(src_dir) if is_vendor_subdir else src_dir)
        ip_text = rebase_ip_yaml_paths(result["ipYamlText"], src_dir, out_dir) if os.path.abspath(out_dir) != src_dir else result["ipYamlText"]
        files.append({"name": f"{result['componentName']}.ip.yml", "dir": out_dir, "content": ip_text})
        if result.get("mmYamlText") and result.get("mmFileName"):
            files.append({"name": result["mmFileName"], "dir": out_dir, "content": result["mmYamlText"]})

    report = check_imported_ip_core(source_path, files[0]["content"], library, incomplete)
    return {"kind": kind, "files": files, "warnings": warnings, "report": report, "summary": build_parse_summary(files[0]["content"])}


def build_parse_summary(yaml_text: str) -> str:
    try:
        data = yaml.safe_load(yaml_text)
        name = str((data.get("name") or "") if isinstance(data, dict) else "")
        parts = []
        for key, label in (("ports", "port"), ("parameters", "parameter"), ("busInterfaces", "bus interface")):
            n = len(data.get(key)) if isinstance(data.get(key), list) else 0
            if n > 0:
                parts.append(f"{n} {label}{'s' if n != 1 else ''}")
        detail = ", ".join(parts) if parts else "no items detected"
        return f"{name}: {detail}" if name else detail
    except Exception:  # noqa: BLE001
        return ""
