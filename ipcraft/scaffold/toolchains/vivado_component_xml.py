"""IP-XACT ``component.xml`` generation for Vivado (port of ``VivadoComponentXmlGenerator.ts``)."""

from __future__ import annotations

import math
import re
import subprocess
from typing import Any, Dict, List, Optional

from .. import widthexpr as wx
from ..buscontracts import (
    data_lane_kind,
    is_declarative_contract,
    parameter_expression,
    resolve_bus_interface,
    resolve_data_lane,
)
from ..compilation_order import resolve_file_set_rtl_files
from ..registers import (
    expand_bus_interfaces,
    get_active_bus_ports_from_definition,
    project_resolved_bus_ports,
)
from .vivado_bus import (
    custom_bus_info_from_contract,
    find_custom_bus_def,
    resolve_vivado_bus_type_for_interface,
)

U32 = 0xFFFFFFFF


def x(s: Any) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def js_str(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and math.isfinite(v) and v == int(v):
        return str(int(v))
    if v is None:
        return "null"
    return str(v)


def crc32_hex(content: str) -> str:
    crc = 0xFFFFFFFF
    for b in content.encode("utf-8"):
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xEDB88320 if crc & 1 else crc >> 1
    return format((~crc) & U32, "x").rjust(8, "0")


def detect_vivado_version() -> str:
    try:
        out = subprocess.run(["vivado", "-version"], capture_output=True, text=True, timeout=2).stdout
        m = re.search(r"vivado v(\d+\.\d+)", out, re.IGNORECASE)
        if m:
            return m.group(1)
    except (OSError, subprocess.SubprocessError):
        pass
    return "2024.2"


def parse_vlnv(vlnv: str) -> dict:
    parts = vlnv.split(":")
    if len(parts) != 4 or any(not p for p in parts):
        raise ValueError(f'Invalid VLNV "{vlnv}": expected vendor:library:name:version')
    return dict(zip(("vendor", "library", "name", "version"), parts))


def is_valid_vlnv(vlnv: str) -> bool:
    return bool(re.match(r"^[^:]+:[^:]+:[^:]+:[^:]+$", vlnv))


def parse_size_string(val: str) -> Optional[float]:
    cleaned = val.strip()
    direct = _js_number(cleaned)
    if direct is not None:
        return direct
    m = re.match(r"^(\d+(?:\.\d+)?)\s*([kmgKMG])$", cleaned)
    if m:
        mult = {"K": 1024, "M": 1024**2, "G": 1024**3}[m.group(2).upper()]
        return math.floor(float(m.group(1)) * mult)
    return None


def _js_number(s: str) -> Optional[float]:
    if s == "":
        return 0
    try:
        if re.match(r"^[+-]?0[xX][0-9a-fA-F]+$", s):
            return int(s, 16)
        if re.match(r"^0[bB][01]+$", s):
            return int(s, 2)
        if re.match(r"^0[oO][0-7]+$", s):
            return int(s, 8)
        v = float(s)
        if not math.isfinite(v) and s.lstrip("+-").lower() != "infinity":
            return None
        return int(v) if math.isfinite(v) and v == int(v) else v
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Bus interface planning
# ---------------------------------------------------------------------------


def _render_port_maps(port_maps: List[dict]) -> List[str]:
    if not port_maps:
        return []
    lines = ["      <spirit:portMaps>"]
    for pm in port_maps:
        lines += ["        <spirit:portMap>", "          <spirit:logicalPort>",
                  f"            <spirit:name>{x(pm['logical'])}</spirit:name>", "          </spirit:logicalPort>",
                  "          <spirit:physicalPort>", f"            <spirit:name>{x(pm['physical'])}</spirit:name>",
                  "          </spirit:physicalPort>", "        </spirit:portMap>"]
    lines.append("      </spirit:portMaps>")
    return lines


def _filter_to_declared_logical_ports(port_maps: List[dict], vivado_type: Optional[dict], custom: Optional[dict]) -> List[dict]:
    if vivado_type:
        declared: Optional[List[str]] = list(vivado_type["logicalPorts"])
    elif custom:
        declared = [r for p in custom["ports"] for r in (p.get("interfaceRoles") or [p["name"]])]
    else:
        declared = None
    if declared is None:
        return list(port_maps)
    by_upper = {n.upper(): n for n in declared}
    out = []
    for pm in port_maps:
        logical = by_upper.get(pm["logical"].upper())
        if logical:
            out.append({"logical": logical, "physical": pm["physical"]})
    return out


def _bus_def_port_maps(ports: List[dict], iface: dict, mode: str, effective_directions: Optional[dict]) -> List[dict]:
    active = get_active_bus_ports_from_definition(
        ports, iface.get("useOptionalPorts") or [], str(iface.get("physicalPrefix") or ""), mode,
        iface.get("portWidthOverrides") or {}, None, iface.get("portNameOverrides"), iface.get("absentPorts"),
        effective_directions)
    return [{"logical": str(p["logical_name"]), "physical": str(p["name"])} for p in active]


def plan_bus_interface(iface: dict, library: dict, parameters: List[dict]) -> dict:
    iface_type = str(iface.get("type") or "")
    mode = str(iface.get("mode") or "slave").lower()
    resolution = resolve_bus_interface(iface, 0, parameters, library)
    vivado_type = resolve_vivado_bus_type_for_interface(iface_type, library, resolution)
    if vivado_type:
        custom = None
    elif resolution["match"]:
        custom = custom_bus_info_from_contract(resolution["match"]["contract"])
    else:
        custom = find_custom_bus_def(iface_type, library)
    eff = {p["name"]: p["effectiveDirection"] for p in resolution["activePorts"] if p.get("effectiveDirection")}
    plan = {"iface": iface, "resolution": resolution, "vivadoType": vivado_type, "customBus": custom,
            "effectiveDirections": eff}
    raw_port_maps = iface.get("rawPortMaps") or []
    if not vivado_type and not custom and not raw_port_maps:
        return {**plan, "portMaps": []}
    conduit_ports = iface.get("conduitPorts")
    if conduit_ports:
        return {**plan, "portMaps": _filter_to_declared_logical_ports(
            _bus_def_port_maps(conduit_ports, iface, mode, eff), vivado_type, custom)}
    if (vivado_type or custom) and resolution["match"]:
        lane = resolve_data_lane(resolution, iface)
        projected = project_resolved_bus_ports(
            resolution["activePorts"], str(iface.get("physicalPrefix") or ""), parameters,
            {"endianness": "big" if iface.get("endianness") == "big" else "little",
             "laneWidth": lane["width"], "laneKind": lane["kind"]})
        maps = [{"logical": p["interfaceRole"], "physical": p["name"]} for p in projected]
        return {**plan, "portMaps": _filter_to_declared_logical_ports(maps, vivado_type, None)}
    return {**plan, "portMaps": raw_port_maps}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_file_set_paths(ip_core: dict, file_set_name: str, prefix: str, ip_core_dir: Optional[str]) -> Optional[List[str]]:
    file_sets = ip_core.get("fileSets")
    if not isinstance(file_sets, list):
        return None
    match = next((fs for fs in file_sets if fs.get("name") == file_set_name), None)
    if not match or not match.get("files"):
        return None
    if ip_core_dir is None:
        return [f"{prefix}{f.get('path') or ''}" for f in match["files"]]
    return [f"{prefix}{f['path']}" for f in resolve_file_set_rtl_files(ip_core, ip_core_dir, file_set_name)]


def generate_component_xml(ip_core: dict, bus_definitions: dict, options: dict) -> str:
    file_path_prefix = options.get("filePathPrefix") or "../"
    rtl_files, sim_files = options.get("rtlFiles"), options.get("simFiles")
    xgui_file, xgui_checksum = options.get("xguiFile"), options.get("xguiChecksum")
    is_sv = options.get("isSv", False)
    memory_maps = options.get("memoryMaps")
    ip_core_dir = options.get("ipCoreDir")
    library = options["busLibrary"]

    vlnv = ip_core.get("vlnv") or {}
    vendor = str(vlnv.get("vendor") if vlnv.get("vendor") is not None else "user")
    lib = str(vlnv.get("library") if vlnv.get("library") is not None else "ip")
    name = str(vlnv.get("name") if vlnv.get("name") is not None else "ip_core")
    version = str(vlnv.get("version") if vlnv.get("version") is not None else "1.0.0")
    description = str(ip_core.get("description") or "")
    clocks = ip_core.get("clocks") or []
    resets = ip_core.get("resets") or []
    all_buses = expand_bus_interfaces(ip_core)
    parameters = ip_core.get("parameters") or []
    plans = [p for p in (plan_bus_interface(i, library, parameters) for i in all_buses) if p["portMaps"]]
    bus_interfaces = [p["iface"] for p in plans]
    user_ports = ip_core.get("ports") or []
    interrupts = ip_core.get("interrupts") or []
    derived_display = options.get("displayName") or re.sub(r"\b\w", lambda m: m.group(0).upper(), name.replace("_", " "))
    version_str = version.replace(".", "_")
    derived_xgui = xgui_file or f"xgui/{name}_v{version_str}.tcl"

    fallback = get_file_set_paths(ip_core, "RTL_Sources", file_path_prefix, ip_core_dir) if rtl_files is None else None
    resolved_rtl = rtl_files if rtl_files is not None else (fallback or [])
    resolved_sim = sim_files if sim_files is not None else (rtl_files if rtl_files is not None else (fallback or []))

    lines: List[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<spirit:component xmlns:xilinx="http://www.xilinx.com"',
        '  xmlns:spirit="http://www.spiritconsortium.org/XMLSchema/SPIRIT/1685-2009"',
        '  xmlns:ipcraft="urn:ipcraft:interface-contract:1"',
        '  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">',
        f"  <spirit:vendor>{x(vendor)}</spirit:vendor>",
        f"  <spirit:library>{x(lib)}</spirit:library>",
        f"  <spirit:name>{x(name)}</spirit:name>",
        f"  <spirit:version>{x(version)}</spirit:version>",
    ]
    bus_if_lines: List[str] = []
    parameter_names = [str(p.get("name") or "") for p in parameters]
    for plan in plans:
        bus_if_lines += render_bus_interface(plan, parameter_names)
    for clock in clocks:
        if not clock.get("name"):
            continue
        assoc = ":".join(str(bi.get("name")).upper() for bi in bus_interfaces if bi.get("associatedClock") == clock["name"])
        assoc_reset = clock.get("associatedReset")
        if assoc_reset is None:
            cands = [bi.get("associatedReset") for bi in bus_interfaces
                     if bi.get("associatedClock") == clock["name"] and bi.get("associatedReset")]
            assoc_reset = cands[0] if cands else None
        bus_if_lines += render_clock_interface(clock["name"], assoc, assoc_reset)
    for reset in resets:
        if not reset.get("name"):
            continue
        bus_if_lines += render_reset_interface(reset["name"], reset.get("polarity") or "activeHigh")
    for intr in interrupts:
        if not intr.get("name"):
            continue
        bus_if_lines += render_interrupt_interface(intr)
    if bus_if_lines:
        lines.append("  <spirit:busInterfaces>")
        lines += bus_if_lines
        lines.append("  </spirit:busInterfaces>")
    if memory_maps and any(len(m.get("addressBlocks") or []) > 0 for m in memory_maps):
        lines += render_memory_maps(memory_maps)

    lines.append("  <spirit:model>")
    lines += render_views(name, ip_core.get("subcores") or [], is_sv, xgui_checksum)
    lines += render_ports(clocks, resets, all_buses, user_ports, interrupts, library, is_sv, parameters)
    lines += render_model_parameters(parameters)
    lines.append("  </spirit:model>")

    has_param_choices = any(isinstance(p.get("allowedValues"), list) and len(p["allowedValues"]) > 0 for p in parameters)
    if resets or has_param_choices:
        lines += render_choices(len(resets), parameters)
    lines += render_file_sets(resolved_rtl, resolved_sim, derived_xgui, ip_core.get("subcores") or [], is_sv,
                              xgui_checksum, build_vhdl_version_lookup(ip_core))
    if description:
        lines.append(f"  <spirit:description>{x(description)}</spirit:description>")
    lines += render_parameters(f"{name}_v{version_str}", parameters)
    lines += render_vendor_extensions(derived_display, detect_vivado_version())
    lines.append("</spirit:component>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def build_ipxact_dependency(expression: str, param_names: List[str]) -> str:
    upper = [p.upper() for p in param_names]
    ast = wx.parse(expression)
    if not ast:
        return wx.IPXACT_UNSUPPORTED

    def param_ref(name: str) -> str:
        u = name.upper()
        return f"spirit:decode(id(&apos;MODELPARAM_VALUE.{u}&apos;))" if u in upper else name

    return wx.serialize(ast, "ipxact", param_ref)[0]


def mode_to_xml_tag(mode: str) -> str:
    return {"master": "master", "source": "master", "sink": "slave"}.get(mode, "slave")


def render_bus_interface(plan: dict, param_names: List[str]) -> List[str]:
    iface, res, vivado_type, custom, port_maps = plan["iface"], plan["resolution"], plan["vivadoType"], plan["customBus"], plan["portMaps"]
    iface_name = str(iface.get("name") or "")
    iface_type = str(iface.get("type") or "")
    mode = str(iface.get("mode") or "slave").lower()
    lines = ["    <spirit:busInterface>", f"      <spirit:name>{x(iface_name)}</spirit:name>"]
    if vivado_type:
        v = vivado_type
        lines.append(f'      <spirit:busType spirit:vendor="{v["vendor"]}" spirit:library="{v["library"]}" spirit:name="{v["name"]}" spirit:version="1.0" />')
        lines.append(f'      <spirit:abstractionType spirit:vendor="{v["vendor"]}" spirit:library="{v["library"]}" spirit:name="{v["abstraction"]}" spirit:version="1.0" />')
    elif custom:
        c = custom
        lines.append(f'      <spirit:busType spirit:vendor="{x(c["vendor"])}" spirit:library="{x(c["library"])}" spirit:name="{x(c["name"])}" spirit:version="{x(c["version"])}" />')
        lines.append(f'      <spirit:abstractionType spirit:vendor="{x(c["vendor"])}" spirit:library="{x(c["library"])}" spirit:name="{x(c["name"])}_rtl" spirit:version="{x(c["version"])}" />')
    else:
        vlnv = iface.get("busTypeVlnv")
        parsed = parse_vlnv(iface_type) if (not vlnv and is_valid_vlnv(iface_type)) else None
        fv = (vlnv or {}).get("vendor") or (parsed or {}).get("vendor") or "user.org"
        fl = (vlnv or {}).get("library") or (parsed or {}).get("library") or "user"
        fn = (vlnv or {}).get("name") or (parsed or {}).get("name") or iface_type
        fver = (vlnv or {}).get("version") or (parsed or {}).get("version") or "1.0"
        lines.append(f'      <spirit:busType spirit:vendor="{x(fv)}" spirit:library="{x(fl)}" spirit:name="{x(fn)}" spirit:version="{x(fver)}" />')
        lines.append(f'      <spirit:abstractionType spirit:vendor="{x(fv)}" spirit:library="{x(fl)}" spirit:name="{x(fn)}_rtl" spirit:version="{x(fver)}" />')

    contract = res["match"]["contract"] if res["match"] else None
    if contract:
        xml_mode = "master" if res["normalizedMode"] == contract["modePolicy"]["producer"] else "slave"
    else:
        xml_mode = mode_to_xml_tag(mode)
    memory_map_ref = iface.get("memoryMapRef") if isinstance(iface.get("memoryMapRef"), str) else None
    if xml_mode == "slave" and memory_map_ref:
        lines += ["      <spirit:slave>", f'        <spirit:memoryMapRef spirit:memoryMapRef="{x(memory_map_ref)}" />', "      </spirit:slave>"]
    else:
        lines.append(f"      <spirit:{xml_mode} />")
    lines += _render_port_maps(port_maps)

    has_symbol = data_lane_kind(contract) == "symbol"
    semantic = []
    for name in sorted((contract or {}).get("interfaceProperties", {})):
        resolved = res["properties"].get(name)
        if not resolved or resolved.get("value") is None:
            continue
        expr = parameter_expression(resolved)
        dependency = build_ipxact_dependency(wx.serialize(expr, "canonical")[0], param_names) if expr else wx.IPXACT_UNSUPPORTED
        entry = {"name": name, "value": resolved["value"]}
        if dependency != wx.IPXACT_UNSUPPORTED:
            entry["dependency"] = dependency
        semantic.append(entry)
    authored = iface.get("interfaceProperties") or {}
    mirrored_semantic = [p for p in semantic if p["name"] in authored]
    mirrors_contract = is_declarative_contract(contract) and custom is not None

    if (vivado_type and vivado_type.get("protocol")) or semantic or has_symbol:
        up = iface_name.upper()
        lines.append("      <spirit:parameters>")
        if vivado_type and vivado_type.get("protocol"):
            lines += ["        <spirit:parameter>", "          <spirit:name>PROTOCOL</spirit:name>",
                      f'          <spirit:value spirit:id="BUSIFPARAM_VALUE.{x(up)}.PROTOCOL">{x(vivado_type["protocol"])}</spirit:value>',
                      "        </spirit:parameter>"]
        for prop in semantic:
            lines.append("        <spirit:parameter>")
            lines.append(f"          <spirit:name>{x(prop['name'])}</spirit:name>")
            dep = f' spirit:format="long" spirit:resolve="dependent" spirit:dependency="{prop["dependency"]}"' if prop.get("dependency") else ""
            lines.append(f'          <spirit:value{dep} spirit:id="BUSIFPARAM_VALUE.{x(up)}.{x(prop["name"])}">{x(js_str(prop["value"]))}</spirit:value>')
            lines.append("        </spirit:parameter>")
        if has_symbol:
            lines += ["        <spirit:parameter>", "          <spirit:name>firstSymbolInHighOrderBits</spirit:name>",
                      f'          <spirit:value spirit:id="BUSIFPARAM_VALUE.{x(up)}.firstSymbolInHighOrderBits">{"true" if iface.get("endianness") == "big" else "false"}</spirit:value>',
                      "        </spirit:parameter>"]
        lines.append("      </spirit:parameters>")

    mirrored: List[dict] = []
    if mirrors_contract:
        mirrored = list(mirrored_semantic)
        if iface.get("endianness") in ("little", "big"):
            mirrored.append({"name": "endianness", "value": iface["endianness"]})
        mirrored.sort(key=lambda p: _locale_key(p["name"]))
    if mirrors_contract and (mirrored or semantic or has_symbol):
        lines += ["      <spirit:vendorExtensions>", '        <ipcraft:interfaceContract version="1">']
        for p in mirrored:
            lines.append(f'          <ipcraft:property name="{x(p["name"])}" value="{x(js_str(p["value"]))}" />')
        lines += ["        </ipcraft:interfaceContract>", "      </spirit:vendorExtensions>"]
    lines.append("    </spirit:busInterface>")
    return lines


def _locale_key(s: str):
    # approximates String.prototype.localeCompare for identifiers (case-insensitive first)
    return (s.lower(), s)


def render_clock_interface(clock_port: str, assoc_bus_ifs: str, assoc_reset: Optional[str]) -> List[str]:
    up = clock_port.upper()
    lines = ["    <spirit:busInterface>", f"      <spirit:name>{x(clock_port)}</spirit:name>",
             '      <spirit:busType spirit:vendor="xilinx.com" spirit:library="signal" spirit:name="clock" spirit:version="1.0" />',
             '      <spirit:abstractionType spirit:vendor="xilinx.com" spirit:library="signal" spirit:name="clock_rtl" spirit:version="1.0" />',
             "      <spirit:slave />", "      <spirit:portMaps>", "        <spirit:portMap>", "          <spirit:logicalPort>",
             "            <spirit:name>CLK</spirit:name>", "          </spirit:logicalPort>", "          <spirit:physicalPort>",
             f"            <spirit:name>{x(clock_port)}</spirit:name>", "          </spirit:physicalPort>",
             "        </spirit:portMap>", "      </spirit:portMaps>", "      <spirit:parameters>"]
    if len(assoc_bus_ifs) > 0:
        lines += ["        <spirit:parameter>", "          <spirit:name>ASSOCIATED_BUSIF</spirit:name>",
                  f'          <spirit:value spirit:id="BUSIFPARAM_VALUE.{x(up)}.ASSOCIATED_BUSIF">{x(assoc_bus_ifs)}</spirit:value>',
                  "        </spirit:parameter>"]
    if assoc_reset:
        lines += ["        <spirit:parameter>", "          <spirit:name>ASSOCIATED_RESET</spirit:name>",
                  f'          <spirit:value spirit:id="BUSIFPARAM_VALUE.{x(up)}.ASSOCIATED_RESET">{x(str(assoc_reset))}</spirit:value>',
                  "        </spirit:parameter>"]
    lines += ["        <spirit:parameter>", "          <spirit:name>FREQ_HZ</spirit:name>",
              f'          <spirit:value spirit:format="long" spirit:resolve="user" spirit:id="BUSIFPARAM_VALUE.{x(up)}.FREQ_HZ">100000000</spirit:value>',
              "        </spirit:parameter>", "      </spirit:parameters>", "    </spirit:busInterface>"]
    return lines


def render_reset_interface(reset_port: str, polarity: str) -> List[str]:
    up = reset_port.upper()
    value = "ACTIVE_LOW" if "low" in polarity.lower() else "ACTIVE_HIGH"
    return ["    <spirit:busInterface>", f"      <spirit:name>{x(reset_port)}</spirit:name>",
            '      <spirit:busType spirit:vendor="xilinx.com" spirit:library="signal" spirit:name="reset" spirit:version="1.0" />',
            '      <spirit:abstractionType spirit:vendor="xilinx.com" spirit:library="signal" spirit:name="reset_rtl" spirit:version="1.0" />',
            "      <spirit:slave />", "      <spirit:portMaps>", "        <spirit:portMap>", "          <spirit:logicalPort>",
            "            <spirit:name>RST</spirit:name>", "          </spirit:logicalPort>", "          <spirit:physicalPort>",
            f"            <spirit:name>{x(reset_port)}</spirit:name>", "          </spirit:physicalPort>",
            "        </spirit:portMap>", "      </spirit:portMaps>", "      <spirit:parameters>", "        <spirit:parameter>",
            "          <spirit:name>POLARITY</spirit:name>",
            f'          <spirit:value spirit:id="BUSIFPARAM_VALUE.{x(up)}.POLARITY" spirit:choiceRef="choice_list_9d8b0d81">{value}</spirit:value>',
            "        </spirit:parameter>", "      </spirit:parameters>", "    </spirit:busInterface>"]


def render_interrupt_interface(intr: dict) -> List[str]:
    up = intr["name"].upper()
    mode_tag = "slave" if intr.get("direction") == "in" else "master"
    sensitivity = intr.get("sensitivity") or "LEVEL_HIGH"
    return ["    <spirit:busInterface>", f"      <spirit:name>{x(intr['name'])}</spirit:name>",
            '      <spirit:busType spirit:vendor="xilinx.com" spirit:library="signal" spirit:name="interrupt" spirit:version="1.0" />',
            '      <spirit:abstractionType spirit:vendor="xilinx.com" spirit:library="signal" spirit:name="interrupt_rtl" spirit:version="1.0" />',
            f"      <spirit:{mode_tag} />", "      <spirit:portMaps>", "        <spirit:portMap>", "          <spirit:logicalPort>",
            "            <spirit:name>INTERRUPT</spirit:name>", "          </spirit:logicalPort>", "          <spirit:physicalPort>",
            f"            <spirit:name>{x(intr['name'])}</spirit:name>", "          </spirit:physicalPort>",
            "        </spirit:portMap>", "      </spirit:portMaps>", "      <spirit:parameters>", "        <spirit:parameter>",
            "          <spirit:name>SENSITIVITY</spirit:name>",
            f'          <spirit:value spirit:id="BUSIFPARAM_VALUE.{x(up)}.SENSITIVITY">{x(sensitivity)}</spirit:value>',
            "        </spirit:parameter>", "      </spirit:parameters>", "    </spirit:busInterface>"]


# -- memory maps ---------------------------------------------------------------


def to_spirit_access(access: Optional[str]) -> str:
    a = (access if access is not None else "read-write").lower()
    if a in ("read-only", "ro"):
        return "read-only"
    if a in ("write-only", "wo", "write-self-clearing"):
        return "write-only"
    if a in ("write-once", "writeonce"):
        return "writeOnce"
    if a in ("read-writeonce", "read-write-once"):
        return "read-writeOnce"
    return "read-write"


def register_spirit_access(reg: dict) -> str:
    if reg.get("access"):
        return to_spirit_access(reg["access"])
    accesses = [to_spirit_access(f.get("access")) for f in reg["fields"]]
    if not accesses:
        return "read-write"
    if all(a == "read-only" for a in accesses):
        return "read-only"
    if all(a == "write-only" for a in accesses):
        return "write-only"
    return "read-write"


def flatten_registers(registers: List[dict], base_offset: int, prefix: str, default_reg_bytes: int, out: List[dict]) -> None:
    for reg in registers:
        reg_name = reg.get("name") or "REG"
        reg_offset = base_offset + reg["offset"]
        if reg.get("__kind") == "array":
            count = max(1, reg.get("count") if reg.get("count") is not None else 1)
            stride = reg.get("stride") if reg.get("stride") is not None else default_reg_bytes
            children = reg.get("registers") or []
            for i in range(count):
                inst = reg_offset + i * stride
                if children:
                    flatten_registers(children, inst, f"{prefix}{reg_name}_{i}_" if count > 1 else f"{prefix}{reg_name}_",
                                      default_reg_bytes, out)
                else:
                    out.append({"name": f"{prefix}{reg_name}_{i}", "offset": inst, "size": reg["size"], "access": reg.get("access"),
                                "resetValue": reg["resetValue"], "description": reg["description"], "fields": reg["fields"]})
            continue
        out.append({"name": f"{prefix}{reg_name}", "offset": reg_offset, "size": reg["size"], "access": reg.get("access"),
                    "resetValue": reg["resetValue"], "description": reg["description"], "fields": reg["fields"]})


def resolve_block_range(block: dict, flat: List[dict], default_reg_bytes: int):
    rng = block.get("range")
    if isinstance(rng, (int, float)) and not isinstance(rng, bool) and rng > 0:
        return rng
    if isinstance(rng, str):
        parsed = parse_size_string(rng)
        if parsed is not None and parsed > 0:
            return parsed
    extent = 0
    for reg in flat:
        reg_bytes = max(1, reg["size"] // 8) if reg["size"] > 0 else default_reg_bytes
        extent = max(extent, reg["offset"] + reg_bytes)
    return extent if extent > 0 else default_reg_bytes


def render_memory_maps(maps: List[dict]) -> List[str]:
    lines = ["  <spirit:memoryMaps>"]
    for m in maps:
        if not (m.get("addressBlocks") or []):
            continue
        lines += ["    <spirit:memoryMap>", f"      <spirit:name>{x(m['name'])}</spirit:name>"]
        for block in m["addressBlocks"]:
            lines += render_address_block(block)
        lines.append("    </spirit:memoryMap>")
    lines.append("  </spirit:memoryMaps>")
    return lines


def render_address_block(block: dict) -> List[str]:
    reg_width = block["defaultRegWidth"] if block["defaultRegWidth"] > 0 else 32
    default_reg_bytes = max(1, reg_width // 8)
    flat: List[dict] = []
    flatten_registers(block.get("registers") or [], 0, "", default_reg_bytes, flat)
    rng = resolve_block_range(block, flat, default_reg_bytes)
    lines = ["      <spirit:addressBlock>", f"        <spirit:name>{x(block['name'])}</spirit:name>",
             f'        <spirit:baseAddress spirit:format="long">{js_str(block["baseAddress"])}</spirit:baseAddress>',
             f'        <spirit:range spirit:format="long">{js_str(rng)}</spirit:range>',
             f'        <spirit:width spirit:format="long">{reg_width}</spirit:width>',
             f"        <spirit:usage>{x(block.get('usage') or 'register')}</spirit:usage>"]
    for reg in flat:
        lines += render_register(reg, reg_width)
    lines.append("      </spirit:addressBlock>")
    return lines


def compose_register_reset(reg: dict) -> int:
    reset = int(reg["resetValue"]) & U32 if reg["resetValue"] > 0 else 0
    for f in reg["fields"]:
        if f["resetValue"]:
            sh = int(f["resetValue"]) << (f["offset"] & 31)
            sh = (sh & U32) - (1 << 32) if sh & 0x80000000 else sh & U32  # int32 wrap
            reset = (reset | sh) & U32
    return reset


def render_register(reg: dict, reg_width: int) -> List[str]:
    size = reg["size"] if reg["size"] > 0 else reg_width
    lines = ["        <spirit:register>", f"          <spirit:name>{x(reg['name'])}</spirit:name>"]
    if reg.get("description"):
        lines.append(f"          <spirit:description>{x(reg['description'])}</spirit:description>")
    lines.append(f"          <spirit:addressOffset>0x{format(int(reg['offset']), 'X')}</spirit:addressOffset>")
    lines.append(f'          <spirit:size spirit:format="long">{js_str(size)}</spirit:size>')
    lines.append(f"          <spirit:access>{register_spirit_access(reg)}</spirit:access>")
    reset = compose_register_reset(reg)
    if reset != 0:
        lines += ["          <spirit:reset>", f'            <spirit:value spirit:format="long">0x{format(reset, "X")}</spirit:value>',
                  "          </spirit:reset>"]
    for f in reg["fields"]:
        lines += render_field(f)
    lines.append("        </spirit:register>")
    return lines


def render_field(field: dict) -> List[str]:
    width = field["width"] if field["width"] > 0 else 1
    lines = ["          <spirit:field>", f"            <spirit:name>{x(field['name'])}</spirit:name>"]
    if field.get("description"):
        lines.append(f"            <spirit:description>{x(field['description'])}</spirit:description>")
    lines += [f"            <spirit:bitOffset>{js_str(field['offset'])}</spirit:bitOffset>",
              f'            <spirit:bitWidth spirit:format="long">{js_str(width)}</spirit:bitWidth>',
              f"            <spirit:access>{to_spirit_access(field.get('access'))}</spirit:access>",
              "          </spirit:field>"]
    return lines


# -- views / ports / parameters / filesets -----------------------------------------


def make_ref_file_set_suffix(v: dict) -> str:
    return "_".join(re.sub(r"[^a-zA-Z0-9]", "_", s) for s in (v["vendor"], v["library"], v["name"], v["version"]))


def render_views(entity_name: str, subcores: List[dict], is_sv: bool, xgui_checksum: Optional[str]) -> List[str]:
    def view(view_name, display, env_id, main_ref, language=None, extra=None, checksum=None) -> List[str]:
        out = ["      <spirit:view>", f"        <spirit:name>{x(view_name)}</spirit:name>",
               f"        <spirit:displayName>{x(display)}</spirit:displayName>",
               f"        <spirit:envIdentifier>{x(env_id)}</spirit:envIdentifier>"]
        if language:
            out += [f"        <spirit:language>{x(language)}</spirit:language>", f"        <spirit:modelName>{x(entity_name)}</spirit:modelName>"]
        for ref in extra or []:
            out += ["        <spirit:fileSetRef>", f"          <spirit:localName>{x(ref)}</spirit:localName>", "        </spirit:fileSetRef>"]
        out += ["        <spirit:fileSetRef>", f"          <spirit:localName>{x(main_ref)}</spirit:localName>", "        </spirit:fileSetRef>"]
        if checksum:
            out += ["        <spirit:parameters>", "          <spirit:parameter>", "            <spirit:name>viewChecksum</spirit:name>",
                    f"            <spirit:value>{x(checksum)}</spirit:value>", "          </spirit:parameter>", "        </spirit:parameters>"]
        out.append("      </spirit:view>")
        return out

    synth, sim = "xilinx_anylanguagesynthesis", "xilinx_anylanguagebehavioralsimulation"
    language = "verilog" if is_sv else "VHDL"
    synth_refs = [f"{synth}_{make_ref_file_set_suffix(parse_vlnv(r['vlnv']))}__ref_view_fileset" for r in subcores]
    sim_refs = [f"{sim}_{make_ref_file_set_suffix(parse_vlnv(r['vlnv']))}__ref_view_fileset" for r in subcores]
    lines = ["    <spirit:views>"]
    lines += view(synth, "Synthesis", ":vivado.xilinx.com:synthesis", f"{synth}_view_fileset", language, synth_refs)
    lines += view(sim, "Simulation", ":vivado.xilinx.com:simulation", f"{sim}_view_fileset", language, sim_refs)
    lines += view("xilinx_xpgui", "UI Layout", ":vivado.xilinx.com:xgui.ui", "xilinx_xpgui_view_fileset", None, [], xgui_checksum)
    lines.append("    </spirit:views>")
    return lines


def resolve_width(width: Any, parameters: List[dict]) -> int:
    if isinstance(width, (int, float)) and not isinstance(width, bool):
        return width
    if isinstance(width, str):
        defaults: Dict[str, float] = {}
        for p in parameters:
            if p.get("name"):
                v = p.get("value") if p.get("value") is not None else p.get("defaultValue")
                try:
                    n = float(v)  # Number(undefined) is NaN
                except (TypeError, ValueError):
                    continue
                if not math.isnan(n):
                    defaults[str(p["name"])] = n
        result = wx.eval_width_expr(width, defaults)
        if result is not None and result > 0:
            return result
    return 1


def render_ports(clocks, resets, bus_interfaces, user_ports, interrupts, library, is_sv, parameters) -> List[str]:
    port_lines: List[str] = []
    param_names = [str(p.get("name") or "") for p in parameters]
    for c in clocks:
        if c.get("name"):
            port_lines += render_model_port(c["name"], "in", 1, is_sv)
    for r in resets:
        if r.get("name"):
            port_lines += render_model_port(r["name"], "in", 1, is_sv)
    for iface in bus_interfaces:
        typed = [{"name": p["name"], "value": (p.get("value") if p.get("value") is not None else p.get("defaultValue"))
                  if isinstance(p.get("value") if p.get("value") is not None else p.get("defaultValue"), (int, float, str)) else None}
                 for p in parameters if isinstance(p.get("name"), str)]
        res = resolve_bus_interface(iface, 0, parameters, library)
        if iface.get("conduitPorts"):
            ports = get_active_bus_ports_from_definition(
                iface["conduitPorts"], iface.get("useOptionalPorts") or [], str(iface.get("physicalPrefix") or ""),
                str(iface.get("mode") or "conduit").lower(), iface.get("portWidthOverrides") or {}, typed,
                iface.get("portNameOverrides"), iface.get("absentPorts"))
            for p in ports:
                port_lines += render_model_port(str(p["name"]), str(p["direction"]), p["width"], is_sv,
                                                str(p["width_expr"]) if p.get("width_expr") else None, param_names)
            continue
        lane = resolve_data_lane(res, iface)
        projected = project_resolved_bus_ports(
            res["activePorts"], str(iface.get("physicalPrefix") or ""), parameters,
            {"endianness": "big" if iface.get("endianness") == "big" else "little", "laneWidth": lane["width"], "laneKind": lane["kind"]})
        if not projected and not res["match"]:
            for pm in iface.get("rawPortMaps") or []:
                port_lines += render_model_port(pm["physical"], pm["direction"], pm["width"], is_sv)
            continue
        for p in projected:
            port_lines += render_model_port(str(p["name"]), str(p["direction"]), p["width"], is_sv,
                                            str(p["widthExpr"]) if p.get("widthExpr") else None, param_names)
    for port in user_ports:
        if not port.get("name"):
            continue
        raw = port.get("width")
        resolved = resolve_width(raw, parameters)
        width_param = raw if isinstance(raw, str) else None
        port_lines += render_model_port(str(port["name"]), str(port.get("direction") or "in"), resolved, is_sv, width_param, param_names)
    for intr in interrupts:
        if intr.get("name"):
            port_lines += render_model_port(intr["name"], "in" if intr.get("direction") == "in" else "out", 1, is_sv)
    if not port_lines:
        return []
    return ["    <spirit:ports>", *port_lines, "    </spirit:ports>"]


def render_model_port(name: str, direction: str, width: Any, is_sv: bool = False,
                      width_param_name: Optional[str] = None, param_names: Optional[List[str]] = None) -> List[str]:
    param_names = param_names or []
    is_vector = width_param_name is not None or width > 1
    lines = ["      <spirit:port>", f"        <spirit:name>{x(name)}</spirit:name>", "        <spirit:wire>",
             f"          <spirit:direction>{x(direction)}</spirit:direction>"]
    if is_vector:
        lines.append("          <spirit:vector>")
        if width_param_name:
            if re.match(r"^\w+$", width_param_name):
                up = width_param_name.upper()
                lines.append(f'            <spirit:left spirit:format="long" spirit:resolve="dependent" spirit:dependency="(spirit:decode(id(&apos;MODELPARAM_VALUE.{up}&apos;)) - 1)">{js_str(width - 1)}</spirit:left>')
            else:
                dep = build_ipxact_dependency(width_param_name, param_names)
                if dep == wx.IPXACT_UNSUPPORTED:
                    lines.append(f'            <spirit:left spirit:format="long">{js_str(width - 1)}</spirit:left>')
                else:
                    lines.append(f'            <spirit:left spirit:format="long" spirit:resolve="dependent" spirit:dependency="({dep} - 1)">{js_str(width - 1)}</spirit:left>')
        else:
            lines.append(f'            <spirit:left spirit:format="long">{js_str(width - 1)}</spirit:left>')
        lines.append('            <spirit:right spirit:format="long">0</spirit:right>')
        lines.append("          </spirit:vector>")
    type_name = "wire" if is_sv else "std_logic_vector" if is_vector else "std_logic"
    lines += ["          <spirit:wireTypeDefs>", "            <spirit:wireTypeDef>", f"              <spirit:typeName>{type_name}</spirit:typeName>",
              "              <spirit:viewNameRef>xilinx_anylanguagesynthesis</spirit:viewNameRef>",
              "              <spirit:viewNameRef>xilinx_anylanguagebehavioralsimulation</spirit:viewNameRef>",
              "            </spirit:wireTypeDef>", "          </spirit:wireTypeDefs>", "        </spirit:wire>", "      </spirit:port>"]
    return lines


def to_ipxact_data_type(p_type: str) -> str:
    return "integer" if p_type in ("natural", "positive") else p_type


def param_spirit_format(p_type: str) -> Dict[str, str]:
    if p_type in ("integer", "natural", "positive"):
        return {"format": "long", "defaultValue": "0"}
    if p_type == "boolean":
        return {"format": "bool", "defaultValue": "false"}
    if p_type == "real":
        return {"format": "float", "defaultValue": "0.0"}
    return {"format": "string", "defaultValue": ""}


def render_model_parameters(parameters: List[dict]) -> List[str]:
    if not parameters:
        return []
    lines = ["    <spirit:modelParameters>"]
    for p in parameters:
        if not p.get("name"):
            continue
        name = str(p["name"])
        p_type = str(p.get("dataType") or "integer").lower()
        fmt = param_spirit_format(p_type)
        value = js_str(p["value"]) if p.get("value") is not None else fmt["defaultValue"]
        is_int = fmt["format"] == "long"
        display = str(p["displayName"]) if p.get("displayName") else name
        lines.append(f'      <spirit:modelParameter xsi:type="spirit:nameValueTypeType" spirit:dataType="{x(to_ipxact_data_type(p_type))}">')
        lines.append(f"        <spirit:name>{x(name)}</spirit:name>")
        lines.append(f"        <spirit:displayName>{x(display)}</spirit:displayName>")
        has_choices = isinstance(p.get("allowedValues"), list) and len(p["allowedValues"]) > 0
        if is_int:
            rt = "" if has_choices else ' spirit:rangeType="long"'
            lines.append(f'        <spirit:value spirit:format="{fmt["format"]}" spirit:resolve="generated" spirit:id="MODELPARAM_VALUE.{x(name.upper())}"{rt}>{x(value)}</spirit:value>')
        else:
            lines.append(f'        <spirit:value spirit:format="{fmt["format"]}" spirit:resolve="generated" spirit:id="MODELPARAM_VALUE.{x(name.upper())}">{x(value)}</spirit:value>')
        lines.append("      </spirit:modelParameter>")
    lines.append("    </spirit:modelParameters>")
    return lines


def render_file_sets(rtl_files, sim_files, xgui_file, subcores, is_sv, xgui_checksum, get_vhdl_version) -> List[str]:
    synth, sim = "xilinx_anylanguagesynthesis", "xilinx_anylanguagebehavioralsimulation"
    render_file = render_sv_file if is_sv else (lambda f: render_vhdl_file(f, get_vhdl_version(f) if get_vhdl_version else None))
    lines = ["  <spirit:fileSets>", "    <spirit:fileSet>", f"      <spirit:name>{synth}_view_fileset</spirit:name>"]
    for f in rtl_files:
        lines += render_file(f)
    lines += ["    </spirit:fileSet>", "    <spirit:fileSet>", f"      <spirit:name>{sim}_view_fileset</spirit:name>"]
    for f in sim_files:
        lines += render_file(f)
    lines += ["    </spirit:fileSet>", "    <spirit:fileSet>", "      <spirit:name>xilinx_xpgui_view_fileset</spirit:name>",
              "      <spirit:file>", f"        <spirit:name>{x(xgui_file)}</spirit:name>", "        <spirit:fileType>tclSource</spirit:fileType>"]
    if xgui_checksum:
        lines.append(f"        <spirit:userFileType>CHECKSUM_{xgui_checksum}</spirit:userFileType>")
    lines += ["        <spirit:userFileType>XGUI_VERSION_2</spirit:userFileType>", "      </spirit:file>", "    </spirit:fileSet>"]
    for ref in subcores:
        v = parse_vlnv(ref["vlnv"])
        suffix = make_ref_file_set_suffix(v)
        for prefix in (synth, sim):
            lines += ["    <spirit:fileSet>", f"      <spirit:name>{prefix}_{suffix}__ref_view_fileset</spirit:name>",
                      "      <spirit:vendorExtensions>", "        <xilinx:subCoreRef>",
                      f'          <xilinx:componentRef xilinx:vendor="{x(v["vendor"])}" xilinx:library="{x(v["library"])}" xilinx:name="{x(v["name"])}" xilinx:version="{x(v["version"])}">',
                      '            <xilinx:mode xilinx:name="create_mode"/>', "          </xilinx:componentRef>",
                      "        </xilinx:subCoreRef>", "      </spirit:vendorExtensions>", "    </spirit:fileSet>"]
    lines.append("  </spirit:fileSets>")
    return lines


def render_vhdl_file(file_path: str, version: Optional[str] = None) -> List[str]:
    lines = ["      <spirit:file>", f"        <spirit:name>{x(file_path)}</spirit:name>"]
    if version in ("93", "87"):
        lines.append("        <spirit:fileType>vhdlSource</spirit:fileType>")
    else:
        lines.append(f"        <spirit:userFileType>vhdlSource-{version if version is not None else '2008'}</spirit:userFileType>")
    lines.append("      </spirit:file>")
    return lines


def render_sv_file(file_path: str) -> List[str]:
    return ["      <spirit:file>", f"        <spirit:name>{x(file_path)}</spirit:name>",
            "        <spirit:fileType>systemVerilogSource</spirit:fileType>", "      </spirit:file>"]


def render_parameters(entity_name: str, parameters: List[dict]) -> List[str]:
    lines = ["  <spirit:parameters>"]
    for p in parameters:
        if not p.get("name"):
            continue
        name = str(p["name"])
        p_type = str(p.get("dataType") or "integer").lower()
        fmt = param_spirit_format(p_type)
        value = js_str(p["value"]) if p.get("value") is not None else fmt["defaultValue"]
        pid = f"PARAM_VALUE.{name.upper()}"
        is_int = fmt["format"] == "long"
        display = str(p["displayName"]) if p.get("displayName") else name
        lines += ["    <spirit:parameter>", f"      <spirit:name>{x(name)}</spirit:name>", f"      <spirit:displayName>{x(display)}</spirit:displayName>"]
        if p.get("description"):
            lines.append(f"      <spirit:description>{x(p['description'])}</spirit:description>")
        choices = p.get("allowedValues")
        has_choices = isinstance(choices, list) and len(choices) > 0
        choice_ref = f' spirit:choiceRef="choice_{name}"' if has_choices else ""
        min_attr = f' spirit:minimum="{js_str(p["min"])}"' if not has_choices and p.get("min") is not None else ""
        max_attr = f' spirit:maximum="{js_str(p["max"])}"' if not has_choices and p.get("max") is not None else ""
        range_attr = ' spirit:rangeType="long"' if is_int and not has_choices else ""
        if is_int:
            lines.append(f'      <spirit:value spirit:format="{fmt["format"]}" spirit:resolve="user" spirit:id="{x(pid)}"{min_attr}{max_attr}{range_attr}{choice_ref}>{x(value)}</spirit:value>')
        else:
            lines.append(f'      <spirit:value spirit:format="{fmt["format"]}" spirit:resolve="user" spirit:id="{x(pid)}"{choice_ref}>{x(value)}</spirit:value>')
        lines.append("    </spirit:parameter>")
    lines += ["    <spirit:parameter>", "      <spirit:name>Component_Name</spirit:name>",
              f'      <spirit:value spirit:resolve="user" spirit:id="PARAM_VALUE.Component_Name" spirit:order="1">{x(entity_name)}</spirit:value>',
              "    </spirit:parameter>", "  </spirit:parameters>"]
    return lines


def render_choices(resets_count: int, parameters: List[dict]) -> List[str]:
    lines = ["  <spirit:choices>"]
    if resets_count > 0:
        lines += ["    <spirit:choice>", "      <spirit:name>choice_list_9d8b0d81</spirit:name>",
                  "      <spirit:enumeration>ACTIVE_HIGH</spirit:enumeration>", "      <spirit:enumeration>ACTIVE_LOW</spirit:enumeration>",
                  "    </spirit:choice>"]
    for p in parameters:
        choices = p.get("allowedValues")
        if isinstance(choices, list) and choices:
            lines += ["    <spirit:choice>", f"      <spirit:name>choice_{p.get('name')}</spirit:name>"]
            for v in choices:
                lines.append(f"      <spirit:enumeration>{js_str(v)}</spirit:enumeration>")
            lines.append("    </spirit:choice>")
    lines.append("  </spirit:choices>")
    return lines


_FAMILIES = ["virtex7", "qvirtex7", "versal", "kintex7", "kintex7l", "qkintex7", "qkintex7l", "akintex7", "artix7", "artix7l",
             "aartix7", "qartix7", "zynq", "qzynq", "azynq", "spartan7", "aspartan7", "virtexu", "zynquplus", "virtexuplus",
             "virtexuplusHBM", "virtexuplus58g", "kintexuplus", "artixuplus", "kintexu"]


def render_vendor_extensions(display_name: str, xilinx_version: str) -> List[str]:
    lines = ["  <spirit:vendorExtensions>", "    <xilinx:coreExtensions>", "      <xilinx:supportedFamilies>"]
    for fam in _FAMILIES:
        lines.append(f'        <xilinx:family xilinx:lifeCycle="Production">{x(fam)}</xilinx:family>')
    lines += ["      </xilinx:supportedFamilies>", "      <xilinx:taxonomies>", "        <xilinx:taxonomy>/UserIP</xilinx:taxonomy>",
              "      </xilinx:taxonomies>", f"      <xilinx:displayName>{x(display_name)}</xilinx:displayName>",
              "      <xilinx:coreRevision>1</xilinx:coreRevision>", "    </xilinx:coreExtensions>", "    <xilinx:packagingInfo>",
              f"      <xilinx:xilinxVersion>{x(xilinx_version)}</xilinx:xilinxVersion>", "    </xilinx:packagingInfo>",
              "  </spirit:vendorExtensions>"]
    return lines


def _normalize_file_path(p: str) -> str:
    return re.sub(r"^(\.\.?/)+", "", p)


def build_vhdl_version_lookup(ip_core: dict):
    by_path: Dict[str, str] = {}
    for fs in ip_core.get("fileSets") or []:
        for f in fs.get("files") or []:
            if f.get("type") == "vhdl" and f.get("path") and f.get("version"):
                by_path[_normalize_file_path(f["path"])] = str(f["version"])
    return lambda file_path: by_path.get(_normalize_file_path(file_path))
