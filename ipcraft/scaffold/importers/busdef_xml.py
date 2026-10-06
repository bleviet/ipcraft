"""IP-XACT bus / abstraction definition importer (port of ``VivadoInterfaceXmlParser.ts`` and the
``vivadoInterfaceToBusDefEntry`` conversion used by the Vivado interface and workspace scanners)."""

from __future__ import annotations

import math
import os
import re
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

from ..jsutil import js_number, js_yaml_dump

SPIRIT_NS = "http://www.spiritconsortium.org/XMLSchema/SPIRIT/1685-2009"


def _q(local: str) -> str:
    return f"{{{SPIRIT_NS}}}{local}"


def _child(parent: ET.Element, local: str) -> Optional[ET.Element]:
    return parent.find(_q(local))


def _children(parent: ET.Element, local: str) -> List[ET.Element]:
    return parent.findall(_q(local))


def _text(parent: ET.Element, local: str) -> str:
    c = _child(parent, local)
    return "".join(c.itertext()).strip() if c is not None else ""


def _attr(element: ET.Element, name: str) -> str:
    v = element.get(_q(name))
    if v is None:
        v = element.get(name)
    return v if v is not None else ""


def _vlnv_key(v: dict) -> str:
    return f"{v['vendor']}:{v['library']}:{v['name']}:{v['version']}"


def _parse_bus_definition(root: ET.Element) -> Optional[dict]:
    vendor, library, name, version = (_text(root, k) for k in ("vendor", "library", "name", "version"))
    if not (vendor and library and name and version):
        return None
    return {"busType": {"vendor": vendor, "library": library, "name": name, "version": version},
            "description": _text(root, "description") or None}


def _parse_abstraction_definition(root: ET.Element) -> Optional[dict]:
    bus_type_el = _child(root, "busType")
    if bus_type_el is None:
        return None
    bus_type = {k: _attr(bus_type_el, k) for k in ("vendor", "library", "name", "version")}
    if not all(bus_type.values()):
        return None
    ports_el = _child(root, "ports")
    if ports_el is None:
        return None
    ports: List[dict] = []
    for port_el in _children(ports_el, "port"):
        logical = _text(port_el, "logicalName")
        wire = _child(port_el, "wire")
        if not logical or wire is None:
            continue
        on_master = _child(wire, "onMaster")
        if on_master is None:
            continue
        presence, width_text, direction = _text(on_master, "presence"), _text(on_master, "width"), _text(on_master, "direction")
        port: Dict[str, object] = {"name": logical}
        if width_text:
            w = js_number(width_text)
            if w is not None and math.isfinite(w):
                port["width"] = w
        if direction in ("in", "out"):
            port["direction"] = direction
        if presence in ("required", "optional"):
            port["presence"] = presence
        ports.append(port)
    if not ports:
        return None
    return {"busTypeKey": _vlnv_key(bus_type), "ports": ports}


def _parse_single_file(xml_text: str) -> Optional[dict]:
    try:
        root = ET.fromstring(xml_text.encode("utf-8"))
    except ET.ParseError:
        return None
    if not root.tag.startswith(f"{{{SPIRIT_NS}}}"):
        return None
    local = root.tag[len(SPIRIT_NS) + 2:]
    if local == "busDefinition":
        parsed = _parse_bus_definition(root)
        return {"kind": "busDefinition", "value": parsed} if parsed else None
    if local == "abstractionDefinition":
        parsed = _parse_abstraction_definition(root)
        return {"kind": "abstractionDefinition", "value": parsed} if parsed else None
    return None


def parse_interface_files(file_contents: List[str]) -> List[dict]:
    """Pair ``busDefinition`` and RTL ``abstractionDefinition`` files into interface definitions."""
    bus_defs: Dict[str, dict] = {}
    abstractions: List[dict] = []
    for content in file_contents:
        parsed = _parse_single_file(content)
        if not parsed:
            continue
        if parsed["kind"] == "busDefinition":
            bus_defs[_vlnv_key(parsed["value"]["busType"])] = parsed["value"]
        else:
            abstractions.append(parsed["value"])
    results: List[dict] = []
    seen = set()
    for a in abstractions:
        if a["busTypeKey"] in seen:
            continue
        bus_def = bus_defs.get(a["busTypeKey"])
        if not bus_def:
            continue
        seen.add(a["busTypeKey"])
        results.append({"busType": bus_def["busType"], "description": bus_def["description"], "ports": a["ports"]})
    return results


def vlnv_to_file_stem(bus_type: dict) -> str:
    s = f"{bus_type['vendor']}_{bus_type['library']}_{bus_type['name']}_{bus_type['version']}".lower()
    return re.sub(r"^_+|_+$", "", re.sub(r"[^a-z0-9]+", "_", s))


def interface_to_bus_def_entry(iface: dict, source: str) -> dict:
    stem = vlnv_to_file_stem(iface["busType"])
    bus_type = dict(iface["busType"])
    if iface.get("description"):
        bus_type["description"] = iface["description"]
    return {"key": stem.upper(), "record": {"busType": bus_type, "source": source, "ports": iface["ports"]}}


def convert_interfaces(xml_paths: List[str], source: str = "workspace") -> Dict[str, str]:
    """``{file name: bus-definition YAML}`` for every interface found in the given XML files / directories."""
    contents: List[str] = []

    def collect(p: str) -> None:
        if os.path.isdir(p):
            for entry in sorted(os.scandir(p), key=lambda e: e.name):
                collect(entry.path)
        elif p.endswith(".xml"):
            try:
                with open(p, encoding="utf-8") as fh:
                    contents.append(fh.read())
            except OSError:
                pass

    for p in xml_paths:
        collect(p)
    out: Dict[str, str] = {}
    for iface in parse_interface_files(contents):
        entry = interface_to_bus_def_entry(iface, source)
        out[f"{entry['key'].lower()}.yml"] = js_yaml_dump({entry["key"]: entry["record"]}, line_width=80)
    return out
