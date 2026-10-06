"""VHDL entity importer (port of ``parser/VhdlParser.ts``): ``.vhd`` -> ``.ip.yml``."""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from ..buscontracts import canonicalize_bus_type, port_name_candidates
from ..jsutil import js_finite_number, js_yaml_dump
from ..registers import BUS_VLNV
from ..widthexpr import collapse_vhdl_function_calls_in_expr, strip_redundant_outer_parens

IP_CORE_FORMAT_VERSION = "1.1"


def strip_comments(content: str) -> str:
    return "\n".join(re.sub(r"--.*$", "", line) for line in content.split("\n"))


def extract_entity_name(content: str) -> Optional[str]:
    m = re.search(r"\bentity\s+(\w+)\s+is\b", content, re.IGNORECASE)
    return m.group(1) if m else None


def _unquote_vhdl_string_literal(raw: str) -> Optional[str]:
    if len(raw) < 2 or raw[0] != '"' or raw[-1] != '"':
        return None
    result = ""
    i = 1
    while i < len(raw) - 1:
        if raw[i] == '"':
            if i + 1 < len(raw) and raw[i + 1] == '"':
                result += '"'
                i += 2
                continue
            return None
        result += raw[i]
        i += 1
    return result


def _unquote_vhdl_literal(raw: str, type_: str) -> str:
    if len(raw) == 3 and raw[0] == "'" and raw[2] == "'":
        return raw[1]
    if re.search(r"\bstring\b", type_, re.IGNORECASE):
        unq = _unquote_vhdl_string_literal(raw)
        return unq if unq is not None else raw
    return raw


def extract_block_content(content: str, keyword: str) -> Optional[str]:
    m = re.search(rf"\b{keyword}\b", content, re.IGNORECASE)
    if not m:
        return None
    start = content.find("(", m.start())
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(content)):
        ch = content[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return content[start + 1:i]
    return None


def split_entries(body: str) -> List[str]:
    entries: List[str] = []
    depth = 0
    current = ""
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == ";" and depth == 0:
            t = current.strip()
            if t:
                entries.append(t)
            current = ""
        else:
            current += ch
    t = current.strip()
    if t:
        entries.append(t)
    return entries


def extract_parameters(content: str) -> List[dict]:
    body = extract_block_content(content, "generic")
    if not body:
        return []
    params: List[dict] = []
    for entry in split_entries(body):
        cleaned = re.sub(r"\s+", " ", entry).strip()
        colon = cleaned.find(":")
        if colon == -1:
            continue
        names = [n.strip() for n in cleaned[:colon].split(",") if n.strip()]
        type_match = cleaned[colon + 1:].split(":=")
        type_ = type_match[0].strip()
        raw_value = type_match[1].strip() if len(type_match) > 1 else None
        value = _unquote_vhdl_literal(raw_value, type_) if raw_value is not None else None
        for name in names:
            params.append({"name": name, "type": type_, "value": value})
    return params


def _extract_first_paren_content(s: str) -> Optional[str]:
    start = s.find("(")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(s)):
        if s[i] == "(":
            depth += 1
        elif s[i] == ")":
            depth -= 1
            if depth == 0:
                return s[start + 1:i].strip()
    return None


def extract_width_from_type(type_: str) -> Any:
    if re.search(r"std_logic_vector", type_, re.IGNORECASE):
        rng = _extract_first_paren_content(type_)
        if not rng:
            return None
        m = re.match(r"^(\w+)\s*-\s*1\s+downto\s+0$", rng, re.IGNORECASE)
        if m:
            return m.group(1)
        m = re.match(r"^(\d+)\s+downto\s+(\d+)$", rng, re.IGNORECASE)
        if m:
            return abs(int(m.group(1)) - int(m.group(2))) + 1
        m = re.match(r"^(\d+)\s+to\s+(\d+)$", rng, re.IGNORECASE)
        if m:
            return abs(int(m.group(1)) - int(m.group(2))) + 1
        g_down = re.match(r"^(.+?)\s*-\s*1\s+downto\s+0$", rng, re.IGNORECASE)
        g_to = re.match(r"^0\s+to\s+(.+?)\s*-\s*1$", rng, re.IGNORECASE)
        raw_expr = (g_down.group(1) if g_down else (g_to.group(1) if g_to else None))
        raw_expr = raw_expr.strip() if raw_expr else None
        if raw_expr:
            return collapse_vhdl_function_calls_in_expr(strip_redundant_outer_parens(raw_expr))
        d0 = re.match(r"^(.+?)\s+downto\s+0$", rng, re.IGNORECASE)
        z0 = re.match(r"^0\s+to\s+(.+)$", rng, re.IGNORECASE)
        bound = (d0.group(1) if d0 else (z0.group(1) if z0 else None))
        bound = re.sub(r"\s+", "", bound.strip()) if bound else None
        if not bound:
            return None
        return f"{collapse_vhdl_function_calls_in_expr(strip_redundant_outer_parens(bound))}+1"
    if re.search(r"\bstd_logic\b", type_, re.IGNORECASE):
        return 1
    return None


def extract_ports(content: str) -> List[dict]:
    body = extract_block_content(content, "port")
    if not body:
        return []
    ports: List[dict] = []
    for entry in split_entries(body):
        cleaned = re.sub(r"\s+", " ", entry).strip()
        if not cleaned or ":" not in cleaned:
            continue
        parts = cleaned.split(":")
        names_part, type_part = parts[0], parts[1]
        names = [n.strip() for n in names_part.split(",") if n.strip()]
        m = re.match(r"^(in|out|inout)\s+(.+)$", type_part.strip(), re.IGNORECASE)
        if not m:
            continue
        direction = m.group(1).lower()
        type_ = m.group(2).strip()
        width = extract_width_from_type(type_)
        for name in names:
            ports.append({"name": name, "direction": direction, "type": type_, "width": width})
    return ports


def extract_vhdl_interface(content: str) -> Dict[str, Any]:
    cleaned = strip_comments(content)
    return {"entityName": extract_entity_name(cleaned), "parameters": extract_parameters(cleaned),
            "ports": extract_ports(cleaned)}


def port_to_dict(port: dict) -> dict:
    upper = port["name"].upper()
    logical = upper
    for prefix in ("IO_", "I_", "O_"):
        if upper.startswith(prefix):
            logical = upper[len(prefix):]
            break
    result: Dict[str, Any] = {"name": port["name"], "direction": port["direction"]}
    if logical != upper:
        result["logicalName"] = logical
    w = port.get("width")
    if w is not None:
        if isinstance(w, (int, float)) and not isinstance(w, bool):
            if w > 1:
                result["width"] = w
        else:
            result["width"] = w
    return result


def normalize_param_data_type(raw: str) -> str:
    n = re.sub(r"\s+range\s+.*", "", raw, flags=re.IGNORECASE).strip().lower()
    if n == "boolean":
        return "boolean"
    if n == "string":
        return "string"
    return "integer"


def parse_parameter_value(value: Optional[str]) -> Any:
    if value is None:
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    numeric = js_finite_number(trimmed)
    if numeric is not None:
        return numeric
    return trimmed


def classify_clocks_resets(ports: List[dict]) -> Dict[str, list]:
    clocks: List[dict] = []
    resets: List[dict] = []
    for port in ports:
        name = port["name"].lower()
        if port["direction"] != "in":
            continue
        if re.search(r"(^|_)(clk|clock|aclk)$", name):
            clocks.append({"name": port["name"]})
            continue
        if re.search(r"(^|_)(rst|reset|aresetn|reset_n|rst_n)$", name):
            active_low = name.endswith("n") or "reset_n" in name or "rst_n" in name
            resets.append({"name": port["name"], "polarity": "activeLow" if active_low else "activeHigh"})
    return {"clocks": clocks, "resets": resets}


def _sig(name: str, presence: str, direction: str) -> dict:
    return {"name": name, "presence": presence, "direction": direction}


def _sigs(spec: str) -> List[dict]:
    # "name:req:out ..." compact form
    out = []
    for item in spec.split():
        n, p, d = item.split(":")
        out.append(_sig(n, "required" if p == "r" else "optional", d))
    return out


BUS_DEFINITIONS: List[dict] = [
    {"id": BUS_VLNV["AXI4_FULL"], "minRequired": 8, "exclusiveSignals": ["awlen", "awburst", "wlast", "rlast"],
     "signals": _sigs("awid:r:out awaddr:r:out awlen:r:out awsize:r:out awburst:r:out awlock:r:out awcache:r:out "
                      "awprot:r:out awvalid:r:out awready:r:in wdata:r:out wstrb:r:out wlast:r:out wvalid:r:out "
                      "wready:r:in bid:r:in bresp:r:in bvalid:r:in bready:r:out arid:r:out araddr:r:out arlen:r:out "
                      "arsize:r:out arburst:r:out arlock:r:out arcache:r:out arprot:r:out arvalid:r:out arready:r:in "
                      "rid:r:in rdata:r:in rresp:r:in rlast:r:in rvalid:r:in rready:r:out")},
    {"id": BUS_VLNV["AXI4_LITE"], "minRequired": 4,
     "signals": _sigs("awaddr:r:out awprot:r:out awvalid:r:out awready:r:in wdata:r:out wstrb:r:out wvalid:r:out "
                      "wready:r:in bresp:r:in bvalid:r:in bready:r:out araddr:r:out arprot:r:out arvalid:r:out "
                      "arready:r:in rdata:r:in rresp:r:in rvalid:r:in rready:r:out")},
    {"id": BUS_VLNV["AXI_STREAM"], "minRequired": 2,
     "signals": _sigs("tdata:r:out tvalid:r:out tready:r:in tstrb:o:out tkeep:o:out tlast:o:out tid:o:out tdest:o:out tuser:o:out")},
    {"id": BUS_VLNV["AVALON_MM"], "minRequired": 3,
     "signals": _sigs("address:r:out read:r:out write:r:out writedata:r:out readdata:r:in byteenable:o:out "
                      "chipselect:o:out readdatavalid:o:in waitrequest:o:in burstcount:o:out beginbursttransfer:o:out "
                      "response:o:in")},
    {"id": BUS_VLNV["AVALON_ST"], "minRequired": 2,
     "signals": _sigs("data:r:out valid:r:out ready:o:in startofpacket:o:out endofpacket:o:out empty:o:out "
                      "channel:o:out error:o:out")},
]

DIRECTION_TAGS = {"i", "o", "in", "out"}


def _is_boundary_char(c: Optional[str]) -> bool:
    return c is None or c == "" or c == "_" or c.isdigit()


def declared_role_candidates(bus_type: str, signal: dict, library: Optional[dict]) -> List[dict]:
    contract_port = None
    if library:
        match = canonicalize_bus_type(bus_type, library)
        if match:
            contract_port = next((p for p in match["contract"]["ports"] if p["name"].lower() == signal["name"]), None)
    if not contract_port:
        return [{"suffix": signal["name"], "roleSuffix": signal["name"]}]
    return port_name_candidates(contract_port)


def _match_signal_at(sorted_signals: List[dict], rest: str, bus_type: str, library: Optional[dict]):
    for sig in sorted_signals:
        candidates = sorted(declared_role_candidates(bus_type, sig, library), key=lambda r: -len(r["suffix"]))
        for role in candidates:
            suffix = role["suffix"].lower()
            nxt = rest[len(suffix)] if len(rest) > len(suffix) else None
            if rest.startswith(suffix) and _is_boundary_char(nxt):
                return {"sig": sig, "role": role, "decoration": rest[len(suffix):]}
    return None


def _instance_key_from_decoration(decoration: str) -> str:
    tokens = [t for t in decoration.split("_") if t]
    return "_".join(t for t in tokens if t not in DIRECTION_TAGS)


def _find_occurrences(name: str, sig_name: str) -> List[int]:
    out: List[int] = []
    start = 0
    while True:
        idx = name.find(sig_name, start)
        if idx == -1:
            break
        out.append(idx)
        start = idx + 1
    return out


def detect_bus_interfaces(ports: List[dict], clock_reset: dict, library: Optional[dict] = None) -> dict:
    port_map: Dict[str, dict] = {}
    for p in ports:
        port_map[p["name"].lower()] = p

    candidate_prefixes: List[str] = [""]
    seen_prefix = {""}
    for bus_def in BUS_DEFINITIONS:
        for sig in bus_def["signals"]:
            for role in declared_role_candidates(bus_def["id"], sig, library):
                suffix = role["suffix"].lower()
                for lower_name in port_map:
                    for i in _find_occurrences(lower_name, suffix):
                        before = None if i == 0 else lower_name[i - 1]
                        after = lower_name[i + len(suffix)] if i + len(suffix) < len(lower_name) else None
                        if (i == 0 or before == "_") and _is_boundary_char(after):
                            prefix = lower_name[:i]
                            if (prefix == "" or prefix.endswith("_")) and prefix not in seen_prefix:
                                seen_prefix.add(prefix)
                                candidate_prefixes.append(prefix)

    candidates: List[dict] = []
    for bus_def in BUS_DEFINITIONS:
        sorted_signals = sorted(bus_def["signals"], key=lambda s: -len(s["name"]))
        for prefix in candidate_prefixes:
            groups: Dict[str, dict] = {}
            for lower_name, port in port_map.items():
                if not lower_name.startswith(prefix):
                    continue
                rest = lower_name[len(prefix):]
                match = _match_signal_at(sorted_signals, rest, bus_def["id"], library)
                if not match:
                    continue
                key = _instance_key_from_decoration(match["decoration"])
                group = groups.setdefault(key, {"sigByName": {}, "matchedPorts": set(), "_order": []})
                existing = group["sigByName"].get(match["sig"]["name"])
                is_default = match["role"].get("isDefaultRole") is True
                existing_default = existing is not None and existing["role"].get("isDefaultRole") is True
                if existing is None or (is_default and not existing_default):
                    if existing is not None:
                        group["matchedPorts"].discard(existing["port"]["name"])
                    group["sigByName"][match["sig"]["name"]] = {"port": port, "role": match["role"]}
                    group["matchedPorts"].add(port["name"])
            for instance_key, group in groups.items():
                if bus_def.get("exclusiveSignals") and not any(s in group["sigByName"] for s in bus_def["exclusiveSignals"]):
                    continue
                required = total = master = slave = 0
                for sig in bus_def["signals"]:
                    matched = group["sigByName"].get(sig["name"])
                    if not matched:
                        continue
                    total += 1
                    if sig["presence"] == "required":
                        required += 1
                    if matched["port"]["direction"] == sig["direction"]:
                        master += 1
                    elif matched["port"]["direction"] != "inout":
                        slave += 1
                if required < bus_def["minRequired"]:
                    continue
                if prefix:
                    relevant = []
                    for k in port_map:
                        if not k.startswith(prefix):
                            continue
                        index_tokens = re.findall(r"\d+", k[len(prefix):])
                        if (len(index_tokens) == 0) if instance_key == "" else (instance_key in index_tokens):
                            relevant.append(k)
                    if len(relevant) - len(group["matchedPorts"]) >= len(group["matchedPorts"]):
                        continue
                candidates.append({"prefix": prefix, "busDef": bus_def, "instanceKey": instance_key,
                                   "requiredCount": required, "totalCount": total,
                                   "mode": "slave" if slave >= master else "master",
                                   "matchedPorts": group["matchedPorts"], "sigByName": group["sigByName"]})

    by_key: Dict[str, dict] = {}
    for c in candidates:
        dedup = f"{c['prefix']} {c['instanceKey']}"
        existing = by_key.get(dedup)
        if (existing is None or c["requiredCount"] > existing["requiredCount"]
                or (c["requiredCount"] == existing["requiredCount"] and c["totalCount"] > existing["totalCount"])):
            by_key[dedup] = c

    import functools

    def cmp(a: dict, b: dict) -> int:
        if len(b["prefix"]) != len(a["prefix"]):
            return len(b["prefix"]) - len(a["prefix"])
        if b["requiredCount"] != a["requiredCount"]:
            return b["requiredCount"] - a["requiredCount"]
        return (a["instanceKey"] > b["instanceKey"]) - (a["instanceKey"] < b["instanceKey"])

    ordered = sorted(by_key.values(), key=functools.cmp_to_key(cmp))
    claimed: Set[str] = set()
    bus_interfaces: List[dict] = []
    bus_port_names: Set[str] = set()
    for c in ordered:
        prefix, bus_def, instance_key, matched_ports, mode, sig_by_name = (
            c["prefix"], c["busDef"], c["instanceKey"], c["matchedPorts"], c["mode"], c["sigByName"])
        overlap = len([n for n in matched_ports if n in claimed])
        if overlap * 2 > len(matched_ports):
            continue
        for n in matched_ports:
            claimed.add(n)
            bus_port_names.add(n)
        base = re.sub(r"_+$", "", prefix) or bus_def["id"].split(":")[2] or "bus"
        bus_name = f"{base}_{instance_key}" if instance_key else base
        assoc_clock = next((cl["name"] for cl in clock_reset["clocks"] if cl["name"].lower().startswith(prefix)), None)
        if assoc_clock is None and len(clock_reset["clocks"]) == 1:
            assoc_clock = clock_reset["clocks"][0]["name"]
        assoc_reset = next((r["name"] for r in clock_reset["resets"] if r["name"].lower().startswith(prefix)), None)
        if assoc_reset is None and len(clock_reset["resets"]) == 1:
            assoc_reset = clock_reset["resets"][0]["name"]
        original_prefix = prefix
        if len(prefix) > 0 and sig_by_name:
            any_port = next(iter(sig_by_name.values()))
            original_prefix = any_port["port"]["name"][:len(prefix)]
        canon_def = None
        if library:
            m = canonicalize_bus_type(bus_def["id"], library)
            canon_def = m["contract"]["ports"] if m else None
        canon_by_lower = {d["name"].lower(): d["name"] for d in (canon_def or [])}

        def canonical_key(sig_name: str) -> str:
            if sig_name in canon_by_lower:
                return canon_by_lower[sig_name]
            if bus_def["id"] in (BUS_VLNV["AVALON_MM"], BUS_VLNV["AVALON_ST"]):
                return sig_name
            return sig_name.upper()

        width_ov: Dict[str, Any] = {}
        name_ov: Dict[str, str] = {}
        pol_ov: Dict[str, str] = {}
        absent: List[str] = []
        use_optional: List[str] = []
        for sig in bus_def["signals"]:
            matched = sig_by_name.get(sig["name"])
            if not matched:
                if sig["presence"] == "required":
                    absent.append(sig["name"].upper())
                continue
            key = canonical_key(sig["name"])
            port = matched["port"]
            if isinstance(port.get("width"), str):
                width_ov[key] = port["width"]
            actual_suffix = port["name"][len(prefix):]
            if actual_suffix != matched["role"]["roleSuffix"]:
                name_ov[key] = actual_suffix
            if matched["role"].get("polarity") and not matched["role"].get("isDefaultRole"):
                pol_ov[key] = matched["role"]["polarity"]
            if sig["presence"] == "optional":
                use_optional.append(key)
        entry: Dict[str, Any] = {"name": bus_name, "type": bus_def["id"], "mode": mode, "physicalPrefix": original_prefix,
                                 "associatedClock": assoc_clock, "associatedReset": assoc_reset}
        entry["portWidthOverrides"] = width_ov or None
        entry["portNameOverrides"] = name_ov or None
        entry["portPolarityOverrides"] = pol_ov or None
        entry["absentPorts"] = absent or None
        entry["useOptionalPorts"] = use_optional or None
        bus_interfaces.append(entry)
    return {"busInterfaces": bus_interfaces, "busPortNames": bus_port_names}


def parse_vhdl_text(content: str, vhdl_path: str, options: Optional[dict] = None) -> dict:
    options = options or {}
    cleaned = strip_comments(content)
    entity = extract_entity_name(cleaned)
    if not entity:
        raise ValueError("No VHDL entity found in file")
    parameters = extract_parameters(cleaned)
    ports = extract_ports(cleaned)
    clock_reset = classify_clocks_resets(ports)
    detect_bus = options.get("detectBus") is not False
    bus_detection = detect_bus_interfaces(ports, clock_reset, options.get("busLibrary")) if detect_bus else None
    excluded: Set[str] = set()
    if bus_detection:
        excluded |= bus_detection["busPortNames"]
    excluded |= {c["name"] for c in clock_reset["clocks"]}
    excluded |= {r["name"] for r in clock_reset["resets"]}
    user_ports = [p for p in ports if p["name"] not in excluded]
    output_dir = options.get("outputDir") or os.path.dirname(os.path.abspath(vhdl_path))

    data: Dict[str, Any] = {
        "apiVersion": IP_CORE_FORMAT_VERSION,
        "vlnv": {"vendor": options.get("vendor") or "user", "library": options.get("library") or "ip",
                 "name": entity, "version": options.get("version") or "1.0.0"},
        "description": f"Generated from {os.path.basename(vhdl_path)}",
    }
    sole_reset = clock_reset["resets"][0]["name"] if len(clock_reset["resets"]) == 1 else None
    sole_clock = clock_reset["clocks"][0]["name"] if len(clock_reset["clocks"]) == 1 else None
    if clock_reset["clocks"]:
        clocks = []
        for c in clock_reset["clocks"]:
            e: Dict[str, Any] = {"name": c["name"], "direction": "in"}
            if sole_reset:
                e["associatedReset"] = sole_reset
            clocks.append(e)
        data["clocks"] = clocks
    if clock_reset["resets"]:
        resets = []
        for r in clock_reset["resets"]:
            e = {"name": r["name"], "direction": "in", "polarity": r["polarity"]}
            if sole_clock:
                e["associatedClock"] = sole_clock
            resets.append(e)
        data["resets"] = resets
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
            for key in ("portWidthOverrides", "portNameOverrides", "portPolarityOverrides", "absentPorts", "useOptionalPorts"):
                if bus.get(key):
                    e[key] = bus[key]
            buses.append(e)
        data["busInterfaces"] = buses
    warnings: List[str] = []
    if parameters:
        plist = []
        for p in parameters:
            if re.search(r"std_logic_vector|bit_vector", p["type"], re.IGNORECASE):
                warnings.append(f"Warning: std_logic_vector generic detected on generic '{p['name']}'. "
                                f"Convert to integer for cross-vendor GUI compatibility.")
            e = {"name": p["name"]}
            v = parse_parameter_value(p.get("value"))
            if v is not None:
                e["value"] = v
            e["dataType"] = normalize_param_data_type(p["type"])
            plist.append(e)
        data["parameters"] = plist
    rel = os.path.relpath(os.path.abspath(vhdl_path), output_dir)
    data["fileSets"] = [{"name": "RTL_Sources", "description": "RTL source files",
                         "files": [{"path": rel, "type": "vhdl", "managed": False}]}]
    return {"entityName": entity, "yamlText": js_yaml_dump(data), "warnings": warnings}


def parse_vhdl_file(vhdl_path: str, options: Optional[dict] = None) -> dict:
    with open(vhdl_path, encoding="utf-8") as fh:
        return parse_vhdl_text(fh.read(), vhdl_path, options)
