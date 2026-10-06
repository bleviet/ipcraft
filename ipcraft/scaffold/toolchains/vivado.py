"""Vivado scaffolding (port of ``VivadoToolchain.ts``)."""

from __future__ import annotations

from typing import Dict

from ..templates_env import to_js
from .vivado_bus import generate_custom_bus_defs
from .vivado_component_xml import crc32_hex, generate_component_xml, get_file_set_paths


class VivadoToolchain:
    id = "vivado"
    display_name = "Vivado (Xilinx/AMD)"
    output_subdir = "xilinx"

    def scaffold(self, ctx: dict, opts: dict) -> Dict[str, str]:
        name, tctx, templates = ctx["name"], ctx["templateContext"], ctx["templates"]
        ip_core, bus_defs, library, is_sv, memory_maps = ctx["ipCoreData"], ctx["busDefinitions"], ctx["busLibrary"], ctx["isSv"], ctx["memoryMaps"]
        files: Dict[str, str] = {}
        version = (ip_core.get("vlnv") or {}).get("version")
        version_str = str(version if version is not None else "1.0").replace(".", "_")
        xgui_file = f"xgui/{name}_v{version_str}.tcl"
        xgui_content = templates.render("amd_xgui.j2", to_js(tctx))
        xgui_checksum = crc32_hex(xgui_content)
        rtl = opts.get("rtlFiles")
        if rtl is None:
            rtl = get_file_set_paths(ip_core, "RTL_Sources", "../", ctx.get("ipCoreDir")) or []
        if templates.has_template("component.xml.j2"):
            files["xilinx/component.xml"] = templates.render("component.xml.j2", to_js({
                **tctx, "ip_core": ip_core, "bus_definitions": bus_defs, "rtl_files": rtl, "xgui_file": xgui_file,
                "xgui_checksum": xgui_checksum, "is_systemverilog": is_sv, "memory_maps": memory_maps}))
        else:
            files["xilinx/component.xml"] = generate_component_xml(ip_core, bus_defs, {
                "rtlFiles": rtl, "xguiFile": xgui_file, "xguiChecksum": xgui_checksum, "isSv": is_sv,
                "memoryMaps": memory_maps, "ipCoreDir": ctx.get("ipCoreDir"), "busLibrary": library})
        for rel, content in generate_custom_bus_defs(ip_core, library).items():
            files[f"xilinx/{rel}"] = content
        files[f"xilinx/{xgui_file}"] = xgui_content
        if opts.get("includeProject"):
            target_part = opts.get("targetPart") or "xc7z020clg484-1"
            xdc_rel = f"{name}_ooc.xdc"
            v_ctx = to_js({**tctx, "target_part": target_part, "rtl_files": rtl, "xdc_file": xdc_rel})
            files[f"xilinx/{name}_project.tcl"] = templates.render("vivado_project.tcl.j2", v_ctx)
            files[f"xilinx/{xdc_rel}"] = templates.render("vivado_ooc.xdc.j2", v_ctx)
            files[f"xilinx/{name}_run_ooc.tcl"] = templates.render("vivado_run_ooc.tcl.j2", v_ctx)
            files[f"xilinx/{name}_run_xpr.tcl"] = templates.render("vivado_run_xpr.tcl.j2", v_ctx)
        return files
