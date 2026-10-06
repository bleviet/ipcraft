"""Vivado IP-XACT ``component.xml`` importer (port of ``parser/ComponentXmlParser.ts``)."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Set, Tuple

from ..buscontracts import (
    canonicalize_bus_type,
    import_vendor_contract_metadata,
    is_declarative_contract,
    reconcile_observed_bus_ports,
)
from ..jsutil import js_parse_int, js_yaml_dump
from ..registers import BUS_VLNV
from .vhdl import IP_CORE_FORMAT_VERSION

SPIRIT_NS = "http://www.spiritconsortium.org/XMLSchema/SPIRIT/1685-2009"
IPCRAFT_CONTRACT_NS = "urn:ipcraft:interface-contract:1"
XILINX_NS = "http://www.xilinx.com"

AXIMM_BUS_FULL = BUS_VLNV["AXI4_FULL"]
AXIMM_BUS_LITE = BUS_VLNV["AXI4_LITE"]
AXIS_BUS = BUS_VLNV["AXI_STREAM"]
AVALON_MM_BUS = BUS_VLNV["AVALON_MM"]

Element = ET.Element


def _q(local: str, ns: str = SPIRIT_NS) -> str:
    return f"{{{ns}}}{local}"


def els(parent: Element, local: str) -> List[Element]:
    return parent.findall(f".//{_q(local)}")


def el(parent: Element, local: str) -> Optional[Element]:
    r = els(parent, local)
    return r[0] if r else None


def child_el(parent: Element, local: str) -> Optional[Element]:
    return parent.find(_q(local))


def child_els(parent: Element, local: str) -> List[Element]:
    return parent.findall(_q(local))


def _text_content(e: Element) -> str:
    return "".join(e.itertext())


def text(parent: Element, local: str) -> str:
    e = el(parent, local)
    return _text_content(e).strip() if e is not None else ""


def attr(element: Element, ns: str, name: str) -> str:
    v = element.get(_q(name, ns))
    if v is None:
        v = element.get(name)
    return v if v is not None else ""


def parse_hex_or_dec(s: str) -> int:
    if not s:
        return 0
    t = s.strip()
    if t.startswith(("0x", "0X")):
        v = js_parse_int(t, 16)
        return v if v is not None else 0  # NaN is falsy upstream where it matters
    return js_parse_int(t, 10) or 0


def logical_port_names(bus_if: Element) -> Set[str]:
    names: Set[str] = set()
    pm_el = child_el(bus_if, "portMaps")
    for port_map in child_els(pm_el if pm_el is not None else bus_if, "portMap"):
        lp = child_el(port_map, "logicalPort")
        name = text(lp, "name") if lp is not None else ""
        if name:
            names.add(name.upper())
    return names


def physical_port_names(bus_if: Element) -> List[str]:
    names: List[str] = []
    pm_el = child_el(bus_if, "portMaps")
    if pm_el is None:
        return names
    for port_map in child_els(pm_el, "portMap"):
        pp = child_el(port_map, "physicalPort")
        if pp is not None:
            n = text(pp, "name")
            if n:
                names.append(n)
    return names


def extract_port_map(bus_if: Element, attrs: Dict[str, dict]) -> List[dict]:
    result: List[dict] = []
    pm_el = child_el(bus_if, "portMaps")
    if pm_el is None:
        return result
    for port_map in child_els(pm_el, "portMap"):
        lp, pp = child_el(port_map, "logicalPort"), child_el(port_map, "physicalPort")
        log_name = text(lp if lp is not None else port_map, "name")
        phys_name = text(pp if pp is not None else port_map, "name")
        if log_name and phys_name:
            a = attrs.get(phys_name)
            result.append({"logical": log_name, "physical": phys_name,
                           "direction": a["direction"] if a else "in", "width": a["width"] if a else 1})
    return result


def extract_observed_port_map(bus_if: Element, attrs: Dict[str, dict]) -> List[dict]:
    pm_el = child_el(bus_if, "portMaps")
    if pm_el is None:
        return []
    out = []
    for port_map in child_els(pm_el, "portMap"):
        lp, pp = child_el(port_map, "logicalPort"), child_el(port_map, "physicalPort")
        logical = text(lp if lp is not None else port_map, "name")
        physical = text(pp if pp is not None else port_map, "name")
        if not logical or not physical:
            continue
        a = attrs.get(physical)
        out.append({"logicalName": logical, "physicalName": physical, "width": a["width"] if a else None})
    return out


def extract_physical_prefix(port_names: List[str]) -> Optional[str]:
    if not port_names:
        return None
    if len(port_names) == 1:
        parts = port_names[0].split("_")
        return "_".join(parts[:-1]) + "_" if len(parts) > 1 else None
    prefix = port_names[0]
    for name in port_names[1:]:
        i = 0
        while i < len(prefix) and i < len(name) and prefix[i] == name[i]:
            i += 1
        prefix = prefix[:i]
    last = prefix.rfind("_")
    if last > 0:
        return prefix[:last + 1]
    return prefix if len(prefix) > 0 else None


def get_bus_if_param(bus_if: Element, name: str) -> Optional[str]:
    params = child_el(bus_if, "parameters")
    if params is None:
        return None
    for param in child_els(params, "parameter"):
        if text(param, "name") == name:
            return text(param, "value") or None
    return None


def get_mirrored_contract_properties(bus_if: Element) -> Optional[Dict[str, str]]:
    contract = bus_if.find(f".//{_q('interfaceContract', IPCRAFT_CONTRACT_NS)}")
    if contract is None or contract.get("version") != "1":
        return None
    out: Dict[str, str] = {}
    for prop in contract.findall(f".//{_q('property', IPCRAFT_CONTRACT_NS)}"):
        name = prop.get("name") or ""
        if name:
            out[name] = prop.get("value") or ""
    return out


def read_contract_metadata(bus_if: Element, if_name: str, match: Optional[dict]) -> dict:
    if not match or not is_declarative_contract(match["contract"]):
        return {}
    location = f"component.xml busInterfaces.{if_name}"
    raw: Dict[str, str] = {}
    for name in match["contract"]["interfaceProperties"]:
        v = get_bus_if_param(bus_if, name)
        if v is not None:
            raw[name] = v
    ordering = get_bus_if_param(bus_if, "firstSymbolInHighOrderBits")
    if ordering is not None:
        raw["firstSymbolInHighOrderBits"] = ordering
    return import_vendor_contract_metadata(match["contract"], raw, get_mirrored_contract_properties(bus_if), None, None, None, location)


def find_unmapped_optional_ports(bus_def: List[dict], mapped_logical: Set[str], physical_prefix: str,
                                 model_port_attrs: Dict[str, dict], claimed: Set[str]) -> List[dict]:
    out = []
    for d in bus_def:
        physical = physical_prefix + d["name"]
        a = model_port_attrs.get(physical)
        if d["presence"] == "optional" and d["name"].upper() not in mapped_logical and a and physical not in claimed:
            out.append({"name": d["name"], "physical": physical, "width": a["width"]})
    return out


def normalize_xml_prolog(xml_text: str) -> str:
    t = xml_text[1:] if xml_text[:1] == "﻿" else xml_text
    decl = re.search(r"<\?xml\b[^>]*\?>", t, re.IGNORECASE)
    if not decl or decl.start() == 0:
        return t
    before = t[:decl.start()]
    if before.strip() == "":
        return t[decl.start():]
    return before + t[decl.end():]


def parse_component_xml_file(file_path: str, options: dict) -> dict:
    with open(file_path, encoding="utf-8") as fh:
        return parse_component_xml_text(fh.read(), options)


def _vector_width(wire: Element) -> int:
    vec = child_el(wire, "vector")
    if vec is None:
        return 1
    left = parse_hex_or_dec(text(vec, "left"))
    right = parse_hex_or_dec(text(vec, "right"))
    return abs(left - right) + 1


def parse_component_xml_text(xml_text: str, options: dict) -> dict:
    library = options["busLibrary"]
    root = ET.fromstring(normalize_xml_prolog(xml_text).encode("utf-8"))

    vendor = text(root, "vendor") or "xilinx.com"
    lib_name = options.get("library") or (text(root, "library") or "ip")
    component_name = text(root, "name") or "unnamed"
    version = text(root, "version") or "1.0"
    description = text(root, "description") or None

    bus_if_els = els(root, "busInterface")
    clock_port_map: Dict[str, str] = {}
    reset_port_map: Dict[str, dict] = {}
    for bus_if in bus_if_els:
        bt = bus_if.find(f".//{_q('busType')}")
        if bt is None:
            continue
        bt_name = attr(bt, SPIRIT_NS, "name")
        if bt_name == "clock":
            ports = physical_port_names(bus_if)
            if ports:
                clock_port_map[text(bus_if, "name")] = ports[0]
        elif bt_name == "reset":
            ports = physical_port_names(bus_if)
            pol_str = get_bus_if_param(bus_if, "POLARITY") or ""
            if ports:
                reset_port_map[text(bus_if, "name")] = {"port": ports[0], "polarity": "activeLow" if pol_str == "ACTIVE_LOW" else "activeHigh"}

    clk_assoc: Dict[str, str] = {}
    for bus_if in bus_if_els:
        bt = bus_if.find(f".//{_q('busType')}")
        if bt is None:
            continue
        if attr(bt, SPIRIT_NS, "name") == "clock":
            assoc = get_bus_if_param(bus_if, "ASSOCIATED_BUSIF") or ""
            clock_port = clock_port_map.get(text(bus_if, "name"))
            if clock_port:
                for n in [s.strip() for s in assoc.split(":") if s.strip()]:
                    clk_assoc[n] = clock_port

    clock_set: Dict[str, bool] = {}
    reset_set: Dict[str, str] = {}
    for port in clock_port_map.values():
        clock_set[port] = True
    for r in reset_port_map.values():
        reset_set[r["port"]] = r["polarity"]
    clocks = [{"name": n, "direction": "in"} for n in clock_set]
    resets = [{"name": n, "direction": "in", "polarity": p} for n, p in reset_set.items()]

    model_port_attrs: Dict[str, dict] = {}
    model_el = child_el(root, "model")
    ports_el = child_el(model_el, "ports") if model_el is not None else None
    if ports_el is not None:
        for port_el in child_els(ports_el, "port"):
            p_name = text(port_el, "name")
            if not p_name:
                continue
            wire = child_el(port_el, "wire")
            if wire is None:
                continue
            model_port_attrs[p_name] = {"direction": "out" if text(wire, "direction") == "out" else "in", "width": _vector_width(wire)}

    bus_interfaces: List[dict] = []
    claimed: Set[str] = set()
    for b in bus_if_els:
        claimed.update(physical_port_names(b))
    claimed.update(clock_port_map.values())
    claimed.update(r["port"] for r in reset_port_map.values())
    folded: Set[str] = set()

    for bus_if in bus_if_els:
        bt = bus_if.find(f".//{_q('busType')}")
        if bt is None:
            continue
        bt_name = attr(bt, SPIRIT_NS, "name")
        if bt_name in ("clock", "reset", "interrupt"):
            continue
        if_name = text(bus_if, "name")
        is_slave = bus_if.find(f".//{_q('slave')}") is not None
        bus_type: str
        bus_type_vlnv = None
        raw_port_maps = None
        contract_match: Optional[dict] = None
        if bt_name == "aximm":
            lp = logical_port_names(bus_if)
            bus_type = AXIMM_BUS_FULL if ("ARLEN" in lp or "AWLEN" in lp) else AXIMM_BUS_LITE
        elif bt_name == "axis":
            bus_type = AXIS_BUS
        elif bt_name == "avalon" and attr(bt, SPIRIT_NS, "vendor") == "xilinx.com":
            bus_type = AVALON_MM_BUS
        else:
            bt_vendor = attr(bt, SPIRIT_NS, "vendor") or "user.org"
            bt_library = attr(bt, SPIRIT_NS, "library") or "user"
            bt_version = attr(bt, SPIRIT_NS, "version") or "1.0"
            imported = f"{bt_vendor}:{bt_library}:{bt_name}:{bt_version}"
            contract_match = canonicalize_bus_type(imported, library)
            bus_type = contract_match["canonicalVlnv"] if contract_match else imported
            if not contract_match:
                bus_type_vlnv = {"vendor": bt_vendor, "library": bt_library, "name": bt_name, "version": bt_version}
                entries = extract_port_map(bus_if, model_port_attrs)
                if entries:
                    raw_port_maps = entries
        if contract_match is None:
            contract_match = canonicalize_bus_type(bus_type, library)
        if contract_match:
            mode = contract_match["contract"]["modePolicy"]["consumer" if is_slave else "producer"]
        else:
            mode = "slave" if is_slave else "master"

        phy_ports = physical_port_names(bus_if)
        physical_prefix = extract_physical_prefix(phy_ports)
        mm_ref_el = bus_if.find(f".//{_q('memoryMapRef')}")
        memory_map_ref = None
        if mm_ref_el is not None:
            memory_map_ref = attr(mm_ref_el, SPIRIT_NS, "memoryMapRef") or _text_content(mm_ref_el).strip() or None
        associated_clock = clk_assoc.get(if_name)
        associated_reset = next(iter(reset_set)) if len(reset_set) == 1 else None

        entry: Dict[str, Any] = {"name": if_name, "type": bus_type, "mode": mode}
        entry.update(read_contract_metadata(bus_if, if_name, contract_match))
        if bus_type_vlnv:
            entry["busTypeVlnv"] = bus_type_vlnv
        if raw_port_maps:
            entry["rawPortMaps"] = raw_port_maps
        if physical_prefix is not None:
            entry["physicalPrefix"] = physical_prefix
        elif phy_ports:
            entry["physicalPrefix"] = ""
        if associated_clock:
            entry["associatedClock"] = associated_clock
        if associated_reset:
            entry["associatedReset"] = associated_reset
        if memory_map_ref:
            entry["memoryMapRef"] = memory_map_ref

        canon = canonicalize_bus_type(bus_type, library)
        bus_def = canon["contract"]["ports"] if canon else None
        if bus_def:
            log_ports = logical_port_names(bus_if)
            folded_ports = find_unmapped_optional_ports(bus_def, log_ports, physical_prefix or "", model_port_attrs,
                                                        claimed | folded) if bus_type == AVALON_MM_BUS else []
            for p in folded_ports:
                folded.add(p["physical"])
            entry.update(reconcile_observed_bus_ports(
                bus_def,
                extract_observed_port_map(bus_if, model_port_attrs)
                + [{"logicalName": p["name"], "physicalName": p["physical"], "width": p["width"]} for p in folded_ports],
                physical_prefix or ""))
        bus_interfaces.append(entry)

    interrupts: List[dict] = []
    for bus_if in bus_if_els:
        bt = bus_if.find(f".//{_q('busType')}")
        if bt is None or attr(bt, SPIRIT_NS, "name") != "interrupt":
            continue
        phy = physical_port_names(bus_if)
        if not phy:
            continue
        is_slave = bus_if.find(f".//{_q('slave')}") is not None
        direction = "in" if is_slave else "out"
        sensitivity = get_bus_if_param(bus_if, "SENSITIVITY")
        for port_name in phy:
            e: Dict[str, Any] = {"name": port_name, "direction": direction}
            if sensitivity:
                e["sensitivity"] = sensitivity
            interrupts.append(e)

    internal_params = {"Component_Name"}
    choices_map: Dict[str, list] = {}
    choices_el = el(root, "choices")
    if choices_el is not None:
        for choice_el in child_els(choices_el, "choice"):
            cn = text(choice_el, "name")
            if not cn:
                continue
            enums_el = child_el(choice_el, "enumerations")
            enum_els = child_els(enums_el, "enumeration") if enums_el is not None else child_els(choice_el, "enumeration")
            values = [t for t in (_text_content(e).strip() for e in enum_els) if t]
            if values:
                choices_map[cn] = values

    parameters: List[dict] = []
    top_params = child_el(root, "parameters")
    if top_params is not None:
        for param in child_els(top_params, "parameter"):
            p_name = text(param, "name")
            if not p_name or p_name in internal_params:
                continue
            value_el = child_el(param, "value")
            raw_value = _text_content(value_el).strip() if value_el is not None else ""
            fmt = attr(value_el, SPIRIT_NS, "format") if value_el is not None else ""
            value: Any = raw_value
            data_type = "string"
            if fmt in ("long", "bitString"):
                n = js_parse_int(raw_value, 10)
                if n is not None:
                    value, data_type = n, "integer"
            elif fmt == "bool":
                value, data_type = raw_value == "true", "boolean"
            entry = {"name": p_name, "value": value, "dataType": data_type}
            min_s = attr(value_el, SPIRIT_NS, "minimum") if value_el is not None else ""
            max_s = attr(value_el, SPIRIT_NS, "maximum") if value_el is not None else ""
            choice_ref = attr(value_el, SPIRIT_NS, "choiceRef") if value_el is not None else ""
            if min_s != "":
                mv = js_parse_int(min_s, 10)
                if mv is not None:
                    entry["min"] = mv
            if max_s != "":
                mv = js_parse_int(max_s, 10)
                if mv is not None:
                    entry["max"] = mv
            if choice_ref:
                choices = choices_map.get(choice_ref)
                if choices:
                    entry["allowedValues"] = choices
            parameters.append(entry)

    assigned: Set[str] = set(clock_port_map.values()) | {r["port"] for r in reset_port_map.values()} | {i["name"] for i in interrupts}
    for bus_if in bus_if_els:
        assigned.update(physical_port_names(bus_if))
    user_ports: List[dict] = []
    model_el = child_el(root, "model")
    ports_el = child_el(model_el, "ports") if model_el is not None else None
    if ports_el is not None:
        for port_el in child_els(ports_el, "port"):
            p_name = text(port_el, "name")
            if not p_name or p_name in assigned or p_name in folded:
                continue
            wire = child_el(port_el, "wire")
            if wire is None:
                continue
            user_ports.append({"name": p_name, "direction": "out" if text(wire, "direction") == "out" else "in",
                               "width": _vector_width(wire)})

    # memory maps
    mem_maps: List[dict] = []
    mm_root = el(root, "memoryMaps")
    if mm_root is not None:
        for mm_el in child_els(mm_root, "memoryMap"):
            blocks: List[dict] = []
            for ab_el in child_els(mm_el, "addressBlock"):
                registers: List[dict] = []
                for reg_el in child_els(ab_el, "register"):
                    reg_name = text(reg_el, "name")
                    reg_desc = text(reg_el, "description") or None
                    reg_access = text(reg_el, "access") or "read-write"
                    reg_reset_el = child_el(reg_el, "reset")
                    reg_reset_str = (text(reg_reset_el, "value") or _text_content(reg_reset_el).strip()) if reg_reset_el is not None else ""
                    reg_reset = parse_hex_or_dec(reg_reset_str) if reg_reset_str else 0
                    fields: List[dict] = []
                    fields_el = child_el(reg_el, "fields")
                    field_els = child_els(fields_el, "field") if fields_el is not None else child_els(reg_el, "field")
                    for field_el in field_els:
                        field_name = text(field_el, "name")
                        field_desc = text(field_el, "description") or None
                        bit_offset = parse_hex_or_dec(text(field_el, "bitOffset"))
                        bit_width = parse_hex_or_dec(text(field_el, "bitWidth")) or 1
                        field_access = text(field_el, "access") or reg_access
                        reset_el = child_el(field_el, "reset")
                        reset_str = (text(reset_el, "value") or _text_content(reset_el).strip()) if reset_el is not None else text(field_el, "resetValue")
                        reset = parse_hex_or_dec(reset_str) if reset_str else None
                        if reset is None and reg_reset:
                            mask = 0xFFFFFFFF if bit_width >= 32 else (1 << bit_width) - 1
                            slice_ = ((reg_reset & 0xFFFFFFFF) >> (bit_offset & 31)) & mask
                            if slice_ != 0:
                                reset = slice_
                        fields.append({"name": field_name, "description": field_desc, "bitOffset": bit_offset, "bitWidth": bit_width,
                                       "access": normalize_access(field_access), "reset": reset})
                    registers.append({"name": reg_name, "description": reg_desc,
                                      "addressOffset": parse_hex_or_dec(text(reg_el, "addressOffset")),
                                      "size": parse_hex_or_dec(text(reg_el, "size")) or 32,
                                      "access": normalize_access(reg_access), "fields": fields})
                blocks.append({"name": text(ab_el, "name"), "baseAddress": parse_hex_or_dec(text(ab_el, "baseAddress")),
                               "range": parse_hex_or_dec(text(ab_el, "range")),
                               "width": parse_hex_or_dec(text(ab_el, "width")) or 32, "registers": registers})
            mem_maps.append({"name": text(mm_el, "name"), "addressBlocks": blocks})

    has_mem_maps = any(len(mm["addressBlocks"]) > 0 for mm in mem_maps)
    mm_file_name = f"{component_name}.mm.yml" if has_mem_maps else None
    ip: Dict[str, Any] = {"apiVersion": IP_CORE_FORMAT_VERSION,
                          "vlnv": {"vendor": vendor, "library": lib_name, "name": component_name, "version": version}}
    if description:
        ip["description"] = description
    if clocks:
        ip["clocks"] = clocks
    if resets:
        ip["resets"] = resets
    if interrupts:
        ip["interrupts"] = interrupts
    if bus_interfaces:
        ip["busInterfaces"] = bus_interfaces
    if mm_file_name:
        ip["memoryMaps"] = {"import": mm_file_name}
    if user_ports:
        ip["ports"] = user_ports
    if parameters:
        ip["parameters"] = parameters

    file_sets_el = child_el(root, "fileSets")
    seen: Set[str] = set()
    subcores: List[str] = []

    def extract_vlnv(sc_ref: Element) -> None:
        for tag in ("componentRef", "vlnv"):
            node = sc_ref.find(f".//{_q(tag, XILINX_NS)}")
            if node is not None:
                v, l, n, ver = (node.get(_q(k, XILINX_NS)) or "" for k in ("vendor", "library", "name", "version"))
                if v and l and n and ver:
                    vlnv = f"{v}:{l}:{n}:{ver}"
                    if vlnv not in seen:
                        seen.add(vlnv)
                        subcores.append(vlnv)
                return

    if file_sets_el is not None:
        for sc in file_sets_el.findall(f".//{_q('subCoreRef', XILINX_NS)}"):
            extract_vlnv(sc)
    vendor_ext = child_el(root, "vendorExtensions")
    if vendor_ext is not None:
        core_ext = vendor_ext.find(f".//{_q('coreExtensions', XILINX_NS)}")
        if core_ext is not None:
            for sc in core_ext.findall(f".//{_q('subCoreRef', XILINX_NS)}"):
                extract_vlnv(sc)
    if subcores:
        ip["subcores"] = subcores

    if file_sets_el is not None:
        buckets: Dict[str, dict] = {}
        for fs_el in child_els(file_sets_el, "fileSet"):
            fs_name = text(fs_el, "name")
            if not fs_name:
                continue
            canonical = vivado_fileset_canonical_name(fs_name)
            if not canonical:
                continue
            file_els = child_els(fs_el, "file")
            if not file_els:
                continue
            bucket = buckets.setdefault(canonical["name"], {"description": canonical["description"], "files": [], "seen": set()})
            for file_el in file_els:
                file_path = text(file_el, "name")
                if not file_path or file_path.startswith(("http://", "https://")):
                    continue
                if file_path in bucket["seen"]:
                    continue
                bucket["seen"].add(file_path)
                uft = [t for t in (_text_content(e).strip() for e in child_els(file_el, "userFileType")) if t]
                ftype, fversion = map_file_type_and_version(text(file_el, "fileType"), uft)
                fe: Dict[str, Any] = {"path": file_path, "type": ftype, "managed": False}
                if fversion:
                    fe["version"] = fversion
                logical_name = text(file_el, "logicalName")
                if logical_name:
                    fe["logicalName"] = logical_name
                if text(file_el, "isIncludeFile") == "true":
                    fe["isIncludeFile"] = True
                bucket["files"].append(fe)
        fs_list = []
        for name, b in buckets.items():
            if b["files"]:
                e = {"name": name, "files": b["files"]}
                if b["description"]:
                    e["description"] = b["description"]
                fs_list.append(e)
        if fs_list:
            ip["fileSets"] = fs_list

    ip_yaml_text = js_yaml_dump(ip, line_width=120)

    mm_yaml_text = None
    if has_mem_maps:
        mm_list = []
        for mm in mem_maps:
            blocks_out = []
            for ab in mm["addressBlocks"]:
                regs_out = []
                for reg in ab["registers"]:
                    ro: Dict[str, Any] = {"name": reg["name"], "offset": reg["addressOffset"], "size": reg["size"], "access": reg["access"]}
                    if reg.get("description"):
                        ro["description"] = reg["description"]
                    if reg["fields"]:
                        fl = []
                        for f in reg["fields"]:
                            msb = f["bitOffset"] + max(1, f["bitWidth"]) - 1
                            fo: Dict[str, Any] = {"name": f["name"], "bits": f"[{msb}:{f['bitOffset']}]", "access": f["access"]}
                            if f["reset"] is not None:
                                fo["resetValue"] = f["reset"]
                            if f.get("description"):
                                fo["description"] = f["description"]
                            fl.append(fo)
                        ro["fields"] = fl
                    regs_out.append(ro)
                blocks_out.append({"name": ab["name"], "baseAddress": ab["baseAddress"], "range": ab["range"], "registers": regs_out})
            if blocks_out:
                mm_list.append({"name": mm["name"] or component_name, "addressBlocks": blocks_out})
        mm_yaml_text = js_yaml_dump(mm_list, line_width=120)

    return {"componentName": component_name, "ipYamlText": ip_yaml_text, "mmYamlText": mm_yaml_text, "mmFileName": mm_file_name}


def vivado_fileset_canonical_name(name: str) -> Optional[dict]:
    if name.endswith("_ref_view_fileset"):
        return None
    if re.match(r"^xilinx_(examples|examplesscriptext|examplessimulation|examplessynthesis|productguide|upgradescripts|versioninformation)", name):
        return None
    if re.search(r"synthesis", name, re.IGNORECASE):
        return {"name": "RTL_Sources", "description": "RTL Sources"}
    if re.search(r"simulation", name, re.IGNORECASE):
        return {"name": "Simulation_Resources", "description": "Simulation Files"}
    if re.match(r"^xilinx_(xpgui|blockdiagram|implementation)_", name):
        return {"name": "Integration", "description": "Integration Files"}
    return {"name": name, "description": ""}


_VHDL_VERSION_RE = re.compile(r"^vhdlSource-(87|93|2002|2008|2019)$")
_VERILOG_VERSION_RE = re.compile(r"^verilogSource-(95|2001)$")
_LEGACY_VHDL_VERSION_RE = re.compile(r"^vhdl[ ]?(2008|2019)$", re.IGNORECASE)


def map_file_type_and_version(file_type: str, user_file_types: List[str]) -> Tuple[str, Optional[str]]:
    m = _VHDL_VERSION_RE.match(file_type)
    if m:
        return "vhdl", m.group(1)
    m = _VERILOG_VERSION_RE.match(file_type)
    if m:
        return "verilog", m.group(1)
    type_ = map_file_type(file_type)
    version: Optional[str] = None
    for uft in user_file_types:
        m = _VHDL_VERSION_RE.match(uft)
        if m:
            type_, version = "vhdl", m.group(1)
            continue
        m = _VERILOG_VERSION_RE.match(uft)
        if m:
            type_, version = "verilog", m.group(1)
            continue
        m = _LEGACY_VHDL_VERSION_RE.match(uft)
        if m:
            if type_ == "unknown":
                type_ = "vhdl"
            version = m.group(1)
    return type_, version


def map_file_type(s: str) -> str:
    return {"vhdlSource": "vhdl", "verilogSource": "verilog", "systemVerilogSource": "systemverilog", "xdcSource": "xdc",
            "sdcSource": "sdc", "ucfSource": "ucf", "tclSource": "tcl", "cSource": "cSource", "cppSource": "cppSource",
            "python": "python", "pythonSource": "python", "pdf": "pdf", "markdown": "markdown", "text": "text",
            "textSource": "text"}.get(s, "unknown")


def normalize_access(access: str) -> str:
    a = access.lower()
    if a in ("read-write", "read_write"):
        return "read-write"
    if a in ("read-only", "read_only"):
        return "read-only"
    if a in ("write-only", "write_only"):
        return "write-only"
    if a in ("writeonce", "write-once"):
        return "write-once"
    return access
