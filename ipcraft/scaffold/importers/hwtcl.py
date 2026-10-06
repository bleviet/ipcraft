"""Platform Designer ``_hw.tcl`` importer (port of ``parser/HwTclParser.ts``): ``_hw.tcl`` -> ``.ip.yml``."""

from __future__ import annotations

import os
import re
import subprocess
from typing import Any, Dict, List, Mapping, Optional, Set

from ..buscontracts import canonicalize_bus_type, import_vendor_contract_metadata, reconcile_observed_bus_ports
from ..domain import title_case_identifier
from ..jsutil import js_finite_number, js_yaml_dump
from ..loader import normalize_parameter_data_type
from ..registers import BUS_VLNV
from .hwtcl_expr import (
    evaluate_tcl_condition,
    has_tcl_syntax,
    numeric_param_values,
    parse_tcl_tokens,
    resolve_tcl_width,
    substitute_tcl_variables,
)
from .hwtcl_helpers import (
    apply_port_property,
    collect_if_chain,
    collect_loop_body,
    compute_proc_defaults,
    finalize_interfaces,
    has_ceil_log2_proc,
    has_legacy_port_declarations,
    parse_tcl_list,
    read_legacy_ports,
    resolve_loop,
    select_if_branches,
)
from .vhdl import IP_CORE_FORMAT_VERSION

READ_INTERFACE_PROPERTIES = {"associatedClock", "associatedReset", "firstSymbolInHighOrderBits", "synchronousEdges"}
SUBSTITUTED_PROPERTY_VALUE = re.compile(r"^set_interface_property\s+\S+\s+\S+\s+.*[$[]")

BUS_TYPE_MAP = {
    "axi4lite": BUS_VLNV["AXI4_LITE"], "axi4": BUS_VLNV["AXI4_FULL"], "avalon": BUS_VLNV["AVALON_MM"],
    "avalon_streaming": BUS_VLNV["AVALON_ST"], "avalonst": BUS_VLNV["AVALON_ST"],
    "axi4stream": BUS_VLNV["AXI_STREAM"], "axis": BUS_VLNV["AXI_STREAM"],
}
FILE_TYPE_MAP = {"VHDL": "vhdl", "VERILOG": "verilog", "SYSTEM_VERILOG": "systemverilog", "TCL": "tcl", "SDC": "sdc", "OTHER": "unknown"}
FILESET_NAME_MAP = {"QUARTUS_SYNTH": "RTL_Sources", "SIM_VHDL": "Simulation_Resources", "SIM_VERILOG": "Simulation_Resources",
                    "SIM_SYSTEMVERILOG": "Simulation_Resources", "SIMULATION": "Simulation_Resources"}
FILESET_DESC_MAP = {"RTL_Sources": "RTL source files", "Simulation_Resources": "Simulation files"}


def resolve_vendor(setting_value: Optional[str] = None) -> str:
    trimmed = (setting_value or "").strip()
    if trimmed and trimmed != "user":
        return trimmed
    try:
        email = subprocess.run(["git", "config", "user.email"], capture_output=True, text=True, timeout=2).stdout.strip()
        at = email.rfind("@")
        if at != -1 and email[at + 1:]:
            return email[at + 1:]
    except (OSError, subprocess.SubprocessError):
        pass
    return "ipcraft"


# -- source flattening -------------------------------------------------------------------


def _parse_tcl_list_items(s: str) -> List[str]:
    items: List[str] = []
    i = 0
    n = len(s)
    while i < n:
        while i < n and s[i] in " \t":
            i += 1
        if i >= n:
            break
        if s[i] == '"':
            i += 1
            val = ""
            while i < n and s[i] != '"':
                val += s[i]
                i += 1
            i += 1
            if val:
                items.append(val)
        else:
            val = ""
            while i < n and s[i] not in " \t":
                val += s[i]
                i += 1
            if val:
                items.append(val)
    return items


def extract_source_path(line: str) -> Optional[str]:
    trimmed = line.strip()
    if not re.match(r"^source\s", trimmed):
        return None
    rest = trimmed[len("source"):].strip()
    m = re.match(r'^"([^"]+)"', rest)
    if m:
        return m.group(1)
    m = re.match(r"^\{([^}]+)\}", rest)
    if m:
        return m.group(1)
    prefix = "[file join [file dirname [info script]] "
    if rest.startswith(prefix):
        inner = rest[len(prefix):]
        last = inner.rfind("]")
        if last >= 0:
            items = _parse_tcl_list_items(inner[:last].strip())
            if items:
                return os.path.join(*items)
    m = re.match(r'^([^\s\[${"\\]+)', rest)
    if m and len(m.group(1)) > 0:
        return m.group(1)
    return None


def _normalize_fileset_file_path(line: str, base_dir: str) -> str:
    if not re.match(r"^add_fileset_file\b", line.strip()):
        return line
    m = re.search(r'\bPATH\s+("([^"]+)"|(\S+))', line)
    if not m:
        return line
    file_path = m.group(2) or m.group(3)
    if os.path.isabs(file_path):
        return line
    return line.replace(m.group(0), f"PATH {os.path.abspath(os.path.join(base_dir, file_path))}", 1)


def flatten_tcl_content(content: str, tcl_path: str, visited: Set[str], normalize_file_paths: bool) -> str:
    resolved = os.path.abspath(tcl_path)
    if resolved in visited:
        return ""
    visited.add(resolved)
    tcl_dir = os.path.dirname(resolved)
    out: List[str] = []
    for raw in content.split("\n"):
        src = extract_source_path(raw)
        if src is not None:
            abs_src = src if os.path.isabs(src) else os.path.abspath(os.path.join(tcl_dir, src))
            try:
                with open(abs_src, encoding="utf-8") as fh:
                    out.append(flatten_tcl_content(fh.read(), abs_src, visited, True))
            except OSError:
                pass
        elif normalize_file_paths:
            out.append(_normalize_fileset_file_path(raw, tcl_dir))
        else:
            out.append(raw)
    return "\n".join(out)


def parse_hwtcl_file(tcl_path: str, options: dict) -> dict:
    with open(tcl_path, encoding="utf-8") as fh:
        content = fh.read()
    flattened = flatten_tcl_content(content, tcl_path, set(), False)
    legacy = read_legacy_ports(flattened, os.path.dirname(os.path.abspath(tcl_path))) if has_legacy_port_declarations(flattened) else None
    result = parse_hwtcl_content(flattened, tcl_path, options, (legacy or {}).get("ports"))
    if legacy and legacy.get("warning") and legacy["warning"] not in result["warnings"]:
        result["warnings"].append(legacy["warning"])
    return result


# -- main parser -----------------------------------------------------------------------------


def _new_iface(name: str, type_: str, mode: str, incomplete: bool) -> dict:
    return {"name": name, "type": type_, "mode": mode, "properties": {}, "symbolicProperties": set(),
            "staticProperties": {}, "staticallyIncomplete": incomplete, "ports": []}


def parse_hwtcl_content(content: str, tcl_path: str, options: dict, legacy_ports: Optional[Mapping[str, dict]] = None) -> dict:
    module_props: Dict[str, str] = {}
    interfaces: Dict[str, dict] = {}
    file_sets: Dict[str, dict] = {}
    parameters: List[dict] = []
    layout = {"groupParents": {}, "paramParents": {}, "displayNames": {}}
    variables: Dict[str, str] = {}
    warnings: List[str] = []
    state: Dict[str, Any] = {"currentFileSet": None}

    def warn(message: str) -> None:
        if message not in warnings:
            warnings.append(message)

    pending_procs: List[dict] = []
    content_lines = content.split("\n")
    proc_defaults = compute_proc_defaults(content_lines)
    rewrite_log2ceil = has_ceil_log2_proc(content_lines)

    def param_names() -> Set[str]:
        return {p["name"] for p in parameters}

    def process_lines(lines: List[str], unresolved: bool = False) -> None:
        nonlocal interfaces
        idx = 0
        while idx < len(lines):
            raw = lines[idx]
            line = raw.strip()
            if not line or line.startswith("#"):
                idx += 1
                continue
            tokens = parse_tcl_tokens(line, variables, rewrite_log2ceil)
            if not tokens:
                idx += 1
                continue
            cmd, args = tokens[0], tokens[1:]

            if cmd == "proc":
                r = collect_loop_body(lines, idx)
                idx = r["next"] - 1
                pending_procs.append({"name": args[0] if args else "", "body": r["body"], "unresolved": unresolved,
                                      "fileSet": state["currentFileSet"]})
            elif cmd == "if":
                chain = collect_if_chain(lines, idx)
                idx = chain["next"] - 1
                sel = select_if_branches(chain, lambda c: evaluate_tcl_condition(
                    substitute_tcl_variables(c, variables), numeric_param_values(parameters)))
                for body in sel["bodies"]:
                    process_lines(body, unresolved or not sel["resolved"])
            elif cmd in ("for", "foreach"):
                r = collect_loop_body(lines, idx)
                idx = r["next"] - 1
                loop = resolve_loop(line, {
                    "substitute": lambda text: substitute_tcl_variables(text, variables),
                    "getVariable": lambda name: variables.get(name),
                    "isParameter": lambda name: any(p["name"] == name for p in parameters),
                    "paramValues": numeric_param_values(parameters),
                })
                if loop:
                    for value in loop["values"]:
                        variables[loop["variable"]] = value
                        process_lines(r["body"], unresolved)
                elif any("add_interface" in b for b in r["body"]):
                    warn(f'Skipped Tcl loop "{line}": its bounds could not be resolved, so the interfaces it creates were not imported.')
            elif cmd == "set" and len(args) >= 2:
                variables[args[0]] = args[1]
            elif cmd == "set_module_property" and len(args) >= 2:
                module_props[args[0]] = args[1]
            elif cmd == "add_interface" and len(args) >= 3:
                name, type_, mode = args[0], args[1], args[2]
                if has_tcl_syntax(name):
                    warn(f'Interface "{name}" was not imported: its name uses Tcl that could not be resolved.')
                else:
                    interfaces[name] = _new_iface(name, type_.lower(), mode.lower(), name in interfaces)
            elif cmd == "set_interface_property" and len(args) >= 3:
                iface_name, prop, value = args[0], args[1], args[2]
                iface = interfaces.get(iface_name)
                static_kept = unresolved or has_tcl_syntax(value)
                if iface and not static_kept:
                    iface["properties"][prop] = value
                    if SUBSTITUTED_PROPERTY_VALUE.search(line):
                        iface["symbolicProperties"].add(prop)
                        iface["staticallyIncomplete"] = True
                    else:
                        iface["symbolicProperties"].discard(prop)
                        iface["staticProperties"][prop] = value
                elif iface and unresolved:
                    iface["staticallyIncomplete"] = True
                    if prop in READ_INTERFACE_PROPERTIES:
                        warn(f'Interface "{iface_name}": property "{prop}" is set under a condition that could not be evaluated, so the static value was kept.')
                elif iface and prop in READ_INTERFACE_PROPERTIES:
                    iface["staticallyIncomplete"] = True
                    warn(f'Interface "{iface_name}": property "{prop}" value "{value}" uses Tcl that could not be resolved, so the static value was kept.')
                elif iface:
                    iface["properties"][prop] = value
                    iface["symbolicProperties"].add(prop)
                    iface["staticallyIncomplete"] = True
            elif cmd == "set_port_property" and len(args) >= 3:
                port_name, prop, value = args[0], args[1], args[2]
                messages = apply_port_property(interfaces, port_name, prop, value, param_names(), numeric_param_values(parameters), unresolved)
                for m in messages:
                    warn(m)
                if messages:
                    for iface in interfaces.values():
                        if any(p["portName"] == port_name for p in iface["ports"]):
                            iface["staticallyIncomplete"] = True
            elif cmd == "add_interface_port" and len(args) >= 5:
                iface_name, port_name, logical_name, direction, width_str = args[:5]
                iface = interfaces.get(iface_name)
                if has_tcl_syntax(port_name):
                    if iface:
                        iface["staticallyIncomplete"] = True
                    warn(f'Port "{port_name}" on interface "{iface_name}" was not imported: its name uses Tcl that could not be resolved.')
                elif iface:
                    width = resolve_tcl_width(width_str, param_names())
                    if width is None:
                        iface["staticallyIncomplete"] = True
                        warn(f'Port "{port_name}" on interface "{iface_name}": width "{width_str}" could not be resolved and was left out.')
                    iface["ports"].append({"portName": port_name, "logicalName": logical_name, "direction": direction, "width": width})
            elif cmd == "add_port_to_interface" and len(args) >= 3:
                iface_name, port_name, role = args[:3]
                iface = interfaces.get(iface_name)
                hdl_port = (legacy_ports or {}).get(port_name)
                if iface and hdl_port:
                    iface["ports"].append({"portName": port_name, "logicalName": role, "direction": hdl_port["direction"],
                                           "width": hdl_port.get("width")})
                elif iface:
                    iface["staticallyIncomplete"] = True
                    warn(f'Port "{port_name}" on interface "{iface_name}" was not imported: add_port_to_interface declares no '
                         f"direction or width and the port was not found in the HDL source.")
            elif cmd == "add_fileset" and len(args) >= 1:
                fs_name = args[0]
                if fs_name not in file_sets:
                    file_sets[fs_name] = {"name": fs_name, "files": []}
                state["currentFileSet"] = file_sets[fs_name]
            elif cmd == "add_fileset_file" and len(args) >= 4 and state["currentFileSet"]:
                if "PATH" in args:
                    path_idx = args.index("PATH")
                    if path_idx + 1 < len(args):
                        raw_path = args[path_idx + 1]
                        joined = re.match(r"^\s*\[\s*file\s+join\s+([\s\S]*)\]\s*$", raw_path)
                        file_path = os.path.join(*parse_tcl_list(joined.group(1))) if joined else raw_path
                        if has_tcl_syntax(file_path):
                            warn(f'File "{raw_path}" in file set "{state["currentFileSet"]["name"]}" was not imported: its path uses Tcl that could not be resolved.')
                        else:
                            state["currentFileSet"]["files"].append({"lang": args[1], "filePath": file_path})
            elif cmd == "add_parameter" and len(args) >= 2:
                parameters.append({"name": args[0], "type": args[1], "defaultValue": args[2] if len(args) > 2 else None})
            elif cmd == "set_parameter_property" and len(args) >= 3:
                param = next((p for p in parameters if p["name"] == args[0]), None)
                if param:
                    key = {"DEFAULT_VALUE": "defaultValue", "DESCRIPTION": "description", "DISPLAY_NAME": "displayName",
                           "ALLOWED_RANGES": "allowedRanges", "GROUP": "legacyGroup"}.get(args[1])
                    if key:
                        param[key] = args[2]
            elif cmd == "add_display_item" and len(args) >= 3:
                parent, id_, kind = args[:3]
                if kind.upper() == "GROUP":
                    layout["groupParents"][id_] = parent
                elif kind.upper() == "PARAMETER":
                    layout["paramParents"][id_] = parent
            elif cmd == "set_display_item_property" and len(args) >= 3 and args[1].upper() == "DISPLAY_NAME":
                layout["displayNames"][args[0]] = args[2]
            idx += 1

    process_lines(content_lines)
    i = 0
    while i < len(pending_procs):
        proc = pending_procs[i]
        state["currentFileSet"] = proc["fileSet"]
        bindings = proc_defaults.get(proc["name"], {})
        saved = {k: variables.get(k) for k in bindings}
        variables.update(bindings)
        process_lines(proc["body"], proc["unresolved"])
        for name, previous in saved.items():
            if previous is None:
                variables.pop(name, None)
            else:
                variables[name] = previous
        i += 1

    finalized = finalize_interfaces(interfaces, numeric_param_values(parameters))
    interfaces = finalized["interfaces"]
    for w in finalized["warnings"]:
        warn(w)
    for iface in interfaces.values():
        if any(p.get("width") is None for p in iface["ports"]):
            iface["staticallyIncomplete"] = True

    component_name = module_props.get("NAME")
    if component_name is None:
        component_name = re.sub(r"\.tcl$", "", re.sub(r"_hw\.tcl$", "", os.path.basename(tcl_path), flags=re.IGNORECASE), flags=re.IGNORECASE)
    author = (module_props.get("AUTHOR") or "").strip()
    vendor = author or resolve_vendor(options.get("vendor"))
    data: Dict[str, Any] = {
        "apiVersion": IP_CORE_FORMAT_VERSION,
        "vlnv": {"vendor": vendor, "library": options.get("library") or "ip", "name": component_name,
                 "version": module_props.get("VERSION") if module_props.get("VERSION") is not None else "1.0.0"},
    }
    description = module_props.get("DESCRIPTION")
    if description:
        data["description"] = description

    all_ifaces = list(interfaces.values())
    clock_ifaces = [i for i in all_ifaces if i["type"] == "clock"]
    reset_ifaces = [i for i in all_ifaces if i["type"] == "reset"]
    conduit_ifaces = [i for i in all_ifaces if i["type"] == "conduit"]
    interrupt_ifaces = [i for i in all_ifaces if i["type"] == "interrupt"]
    bus_ifaces = [i for i in all_ifaces if i["type"] in BUS_TYPE_MAP]
    clock_port_by_iface = {ci["name"]: (ci["ports"][0]["portName"] if ci["ports"] else None) for ci in clock_ifaces}
    reset_port_by_iface = {ri["name"]: (ri["ports"][0]["portName"] if ri["ports"] else None) for ri in reset_ifaces}

    clock_entries = [{"name": p["portName"], "direction": "in"} for ci in clock_ifaces for p in ci["ports"]]
    if clock_entries:
        data["clocks"] = clock_entries
    reset_entries = []
    for ri in reset_ifaces:
        for p in ri["ports"]:
            active_low = p["portName"].lower().endswith("n") or ri["properties"].get("synchronousEdges") == "DEASSERT"
            reset_entries.append({"name": p["portName"], "direction": "in", "polarity": "activeLow" if active_low else "activeHigh"})
    if reset_entries:
        data["resets"] = reset_entries
    port_entries = []
    for ci in conduit_ifaces:
        for p in ci["ports"]:
            entry: Dict[str, Any] = {"name": p["portName"], "direction": _map_direction(p["direction"])}
            w = p.get("width")
            if w is not None and (len(w) > 0 if isinstance(w, str) else w > 1):
                entry["width"] = w
            port_entries.append(entry)
    if port_entries:
        data["ports"] = port_entries
    interrupt_entries = [{"name": p["portName"], "direction": _map_direction(p["direction"])} for ii in interrupt_ifaces for p in ii["ports"]]
    if interrupt_entries:
        data["interrupts"] = interrupt_entries

    bus_entries = []
    for bi in bus_ifaces:
        match = canonicalize_bus_type(BUS_TYPE_MAP[bi["type"]], options["busLibrary"])
        is_producer = bi["mode"] in ("start", "source", "master")
        if match:
            mode = match["contract"]["modePolicy"]["producer" if is_producer else "consumer"]
        else:
            mode = "master" if is_producer else "slave"
        port_names = [p["portName"] for p in bi["ports"]]
        physical_prefix = _compute_physical_prefix(port_names)
        entry = {"name": bi["name"], "type": BUS_TYPE_MAP[bi["type"]], "mode": mode, "physicalPrefix": physical_prefix}
        assoc_clock = bi["properties"].get("associatedClock")
        clock_port = clock_port_by_iface.get(assoc_clock) if assoc_clock else None
        if clock_port:
            entry["associatedClock"] = clock_port
        assoc_reset = bi["properties"].get("associatedReset")
        reset_port = reset_port_by_iface.get(assoc_reset) if assoc_reset else None
        if reset_port:
            entry["associatedReset"] = reset_port
        if match:
            data_width = next((p.get("width") for p in bi["ports"] if p["logicalName"].lower() == "data"), None)
            metadata = import_vendor_contract_metadata(
                match["contract"], bi["properties"], None, bi["symbolicProperties"], bi["staticProperties"], data_width,
                f"{tcl_path}: interface '{bi['name']}'")
            meta_warnings = metadata.pop("warnings", [])
            entry.update(metadata)
            for w in meta_warnings:
                warn(w)
        if match:
            entry.update(reconcile_observed_bus_ports(
                match["contract"]["ports"],
                [{"logicalName": p["logicalName"], "physicalName": p["portName"], "width": p.get("width")} for p in bi["ports"]],
                physical_prefix))
        bus_entries.append(entry)
    if bus_entries:
        data["busInterfaces"] = bus_entries

    if parameters:
        plist = []
        for p in parameters:
            data_type = normalize_parameter_data_type(p["type"])
            e: Dict[str, Any] = {"name": p["name"]}
            v = _parse_param_value(p.get("defaultValue"), data_type)
            if v is not None:
                e["value"] = v
            e["dataType"] = data_type
            e["description"] = p.get("description") if p.get("description") is not None else ""
            e.update(_resolve_parameter_display_name(p))
            e.update(_resolve_parameter_constraint(p.get("allowedRanges"), data_type,
                                                   lambda raw, _n=p["name"]: warn(
                                                       f'Parameter "{_n}": ALLOWED_RANGES "{raw}" uses Tcl that could not be resolved and was left out.')))
            e.update(_resolve_parameter_placement(p, layout))
            plist.append(e)
        data["parameters"] = plist

    tcl_dir = os.path.dirname(os.path.abspath(tcl_path))
    output_dir = options.get("outputDir") or tcl_dir
    seen: Set[str] = set()
    fs_entries = []
    for fs_key, fs_data in file_sets.items():
        mapped = FILESET_NAME_MAP.get(fs_key, fs_key)
        if mapped in seen:
            continue
        seen.add(mapped)
        files = [{"path": os.path.relpath(os.path.abspath(os.path.join(tcl_dir, f["filePath"])), output_dir),
                  "type": FILE_TYPE_MAP.get(f["lang"], "unknown"), "managed": False} for f in fs_data["files"]]
        if files:
            fs_entries.append({"name": mapped, "description": FILESET_DESC_MAP.get(mapped, mapped.replace("_", " ")), "files": files})
    if fs_entries:
        data["fileSets"] = fs_entries

    incomplete = [i["name"] for i in interfaces.values() if i["staticallyIncomplete"]]
    result = {"componentName": component_name, "yamlText": js_yaml_dump(data), "warnings": warnings}
    if incomplete:
        result["staticallyIncompleteInterfaces"] = incomplete
    return result


def _map_direction(d: str) -> str:
    low = d.lower()
    return {"input": "in", "output": "out", "bidir": "inout"}.get(low, low)


def _compute_physical_prefix(port_names: List[str]) -> str:
    if not port_names:
        return ""
    prefix = port_names[0]
    for name in port_names[1:]:
        while len(prefix) > 0 and not name.startswith(prefix):
            prefix = prefix[:-1]
    last = prefix.rfind("_")
    if last >= 0:
        return prefix[:last + 1]
    return f"{prefix}_" if prefix else ""


def _parse_param_value(value: Optional[str], data_type: str) -> Any:
    if value is None or value == "":
        return None
    if data_type == "string":
        return value
    num = js_finite_number(value)
    return num if num is not None else value


def _resolve_parameter_display_name(param: dict) -> dict:
    dn = param.get("displayName")
    if not dn:
        return {}
    if dn == title_case_identifier(param["name"]):
        return {}
    return {"displayName": dn}


def _resolve_parameter_constraint(allowed_ranges: Optional[str], data_type: str, on_unresolved) -> dict:
    if not allowed_ranges:
        return {}
    span = re.match(r"^\s*(-?\d+)\s*:\s*(-?\d+)\s*$", allowed_ranges)
    if span:
        return {"min": int(span.group(1)), "max": int(span.group(2))}
    is_string = data_type == "string"
    list_text = allowed_ranges
    if re.match(r"^\s*\[", allowed_ranges):
        cmd = re.match(r"^\s*\[\s*list\b([\s\S]*)\]\s*$", allowed_ranges)
        if not cmd:
            on_unresolved(allowed_ranges)
            return {}
        list_text = cmd.group(1)
    choices = []
    for unquoted in parse_tcl_list(list_text):
        if is_string:
            choices.append(unquoted)
        else:
            num = js_finite_number(unquoted) if unquoted != "" else None
            choices.append(num if num is not None else unquoted)
    return {"allowedValues": choices} if choices else {}


def _resolve_parameter_placement(param: dict, layout: dict) -> dict:
    parent = layout["paramParents"].get(param["name"])
    if parent is not None:
        if parent == "":
            return {}
        grandparent = layout["groupParents"].get(parent)
        parent_label = layout["displayNames"].get(parent, parent)
        if grandparent:
            return {"uiPage": layout["displayNames"].get(grandparent, grandparent), "uiGroup": parent_label}
        return {"uiPage": parent_label}
    if not param.get("legacyGroup"):
        return {}
    group = param["legacyGroup"]
    slash = group.find("/")
    if slash == -1:
        return {"uiPage": group}
    return {"uiPage": group[:slash], "uiGroup": group[slash + 1:]}
