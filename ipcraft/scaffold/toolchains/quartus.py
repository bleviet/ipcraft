"""Quartus / Platform Designer scaffolding (port of ``QuartusToolchain.ts`` and ``platformDesignerRoles.ts``)."""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

from ..compilation_order import hdl_language_from_path, resolve_file_set_rtl_files
from ..registers import registry_normalize
from ..templates_env import to_js

TEMPLATE_TYPE_TO_ALTERA = {"axil": "axi4lite", "axi4": "axi4", "axis": "axi4stream", "avmm": "avalon",
                           "avst": "avalon_streaming"}


def _hdl_type_from_path(file_path: str) -> str:
    ext = os.path.splitext(file_path)[1].lower()
    if ext in (".sv", ".svh"):
        return "SYSTEM_VERILOG"
    if ext in (".v", ".vh"):
        return "VERILOG"
    return "VHDL"


def _hdl_type_from_file_type(type_: Optional[str], is_sv: bool) -> str:
    if type_ == "systemverilog":
        return "SYSTEM_VERILOG"
    if type_ == "vhdl":
        return "VHDL"
    if type_ == "verilog":
        return "VERILOG"
    return "SYSTEM_VERILOG" if is_sv else "VHDL"


def resolve_hw_tcl_rtl_files(rtl_files: Optional[List[str]], ip_core: dict, is_sv: bool, entity_name: str,
                             ip_core_dir: Optional[str]) -> List[dict]:
    top_exts = [".sv"] if is_sv else [".vhd", ".vhdl"]

    def to_entry(file_path: str, hdl_type: str) -> dict:
        name = os.path.basename(file_path)
        stem, ext = os.path.splitext(name)
        return {"path": file_path, "name": name, "hdl_type": hdl_type,
                "is_top": stem == entity_name and ext.lower() in top_exts}

    if rtl_files:
        return [to_entry(f, _hdl_type_from_path(f)) for f in rtl_files]
    if ip_core_dir is None:
        file_sets = ip_core.get("fileSets")
        if not isinstance(file_sets, list):
            return []
        rtl_sources = next((fs for fs in file_sets if fs.get("name") == "RTL_Sources"), None)
        if not rtl_sources or not rtl_sources.get("files"):
            return []
        return [to_entry(f"../{f['path']}", _hdl_type_from_file_type(f.get("type"), is_sv))
                for f in rtl_sources["files"] if f.get("path")]
    resolved = resolve_file_set_rtl_files(ip_core, ip_core_dir, "RTL_Sources")
    out = []
    for f in resolved:
        declared = f["type"] if f.get("type") in ("vhdl", "systemverilog", "verilog") else None
        effective = declared or hdl_language_from_path(f["path"]) or f.get("type")
        out.append(to_entry(f"../{f['path']}", _hdl_type_from_file_type(effective, is_sv)))
    return out


def detect_pll(rtl_files: Optional[List[str]], ip_core: dict) -> bool:
    paths = list(rtl_files or [])
    for fs in ip_core.get("fileSets") or []:
        for f in fs.get("files") or []:
            if f.get("path"):
                paths.append(f["path"])
    return any(re.search("pll", p, re.IGNORECASE) for p in paths)


def map_bus_type_to_altera(type_name: Optional[str], library: dict) -> str:
    if not type_name:
        return "conduit"
    return TEMPLATE_TYPE_TO_ALTERA.get(registry_normalize(type_name, library)["templateType"], "conduit")


_FAMILY_PREFIXES = [
    ("5C", "Cyclone V"), ("10CX", "Cyclone 10 LP"), ("10M", "MAX 10"), ("EP4CGX", "Cyclone IV GX"),
    ("EP4C", "Cyclone IV E"), ("EP3C", "Cyclone III"), ("EP2C", "Cyclone II"), ("5AGZ", "Arria V GZ"),
    ("5A", "Arria V"), ("EP5S", "Stratix V"), ("EP4S", "Stratix IV"), ("EP3S", "Stratix III"),
]


def quartus_device_family(device: str) -> str:
    d = device.upper()
    for prefix, family in _FAMILY_PREFIXES:
        if d.startswith(prefix):
            return family
    return "Cyclone V"


def apply_platform_designer_role_case(interfaces: List[dict], elaborate: List[dict]) -> Dict[str, List[dict]]:
    standard = {i.get("name") for i in interfaces if i.get("altera_type") != "conduit"}

    def lower_role(port: dict) -> dict:
        if isinstance(port.get("interface_role"), str):
            return {**port, "interface_role": port["interface_role"].lower()}
        return port

    return {
        "interfaces": [
            {**i, "ports": [lower_role(p) for p in i["ports"]]} if i.get("name") in standard and isinstance(i.get("ports"), list) else i
            for i in interfaces],
        "elaboratePortWidths": [lower_role(p) if p.get("iface_name") in standard else p for p in elaborate],
    }


class QuartusToolchain:
    id = "quartus"
    display_name = "Quartus (Intel/Altera)"
    output_subdir = "altera"

    def scaffold(self, ctx: dict, opts: dict) -> Dict[str, str]:
        name, tctx, templates = ctx["name"], ctx["templateContext"], ctx["templates"]
        ip_core, is_sv, library = ctx["ipCoreData"], ctx["isSv"], ctx["busLibrary"]
        files: Dict[str, str] = {}
        expanded = tctx.get("expanded_bus_interfaces")
        if isinstance(expanded, list):
            for iface in expanded:
                iface["altera_type"] = map_bus_type_to_altera(iface["type"] if isinstance(iface.get("type"), str) else None, library)
        rtl_entries = resolve_hw_tcl_rtl_files(opts.get("rtlFiles"), ip_core, is_sv, name, ctx.get("ipCoreDir"))
        roles = apply_platform_designer_role_case(expanded or [], tctx.get("elaborate_port_widths") or [])
        files[f"altera/{name}_hw.tcl"] = templates.render("altera_hw_tcl.j2", to_js({
            **tctx, "expanded_bus_interfaces": roles["interfaces"], "elaborate_port_widths": roles["elaboratePortWidths"],
            "rtl_files": rtl_entries}))
        files["altera/test.qsys"] = templates.render("altera_test_system.qsys.j2", to_js(tctx))
        if opts.get("includeProject"):
            device = opts.get("quartusDevice") or "5CSEBA6U23I7"
            family = quartus_device_family(device)
            sdc_rel = f"{name}.sdc"
            rtl_files = [e["path"] for e in rtl_entries]
            has_sv_files = any(f.endswith(".sv") or f.endswith(".svh") for f in rtl_files)
            has_vhdl_files = any(f.endswith(".vhd") or f.endswith(".vhdl") for f in rtl_files)
            q_ctx = {**tctx, "target_device": device, "device_family": family, "rtl_files": rtl_files,
                     "has_sv": has_sv_files or (not has_vhdl_files and is_sv),
                     "has_vhdl": has_vhdl_files or (not has_sv_files and not is_sv),
                     "has_pll": detect_pll(rtl_files, ip_core), "sdc_file": sdc_rel}
            files[f"altera/{name}_project.tcl"] = templates.render("quartus_project.tcl.j2", to_js(q_ctx))
            files[f"altera/{sdc_rel}"] = templates.render("quartus_sdc.j2", to_js(q_ctx))
        return files
