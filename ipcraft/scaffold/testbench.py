"""Testbench generation: simulation engines, frameworks and the verification manifest.

Port of ``generator/testbench/*`` and ``generator/verificationManifest.ts``.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .templates_env import to_js

DEFAULT_FRAMEWORK = "cocotb"
DEFAULT_ENGINE = "ghdl"

RTL_HDL_TYPES = {"vhdl", "systemverilog", "verilog"}
SIM_PREFIXES = ("tb/", "sim/", "simulation/", "testbench/", "test/")


class Engine:
    def __init__(self, id_: str, display_name: str, sim_var: str, top_level_lang: str, compile_args: List[str],
                 wave_ext: str, vunit_sim_option_key: str, vunit_compile_option_key: str, cocotb_compile_var: str,
                 cocotb_run_args_var: Optional[str], sim_args, wave_args, wave_viewer):
        self.id = id_
        self.display_name = display_name
        self.sim_var = sim_var
        self.top_level_lang = top_level_lang
        self.compile_args = compile_args
        self.wave_ext = wave_ext
        self.vunit_sim_option_key = vunit_sim_option_key
        self.vunit_compile_option_key = vunit_compile_option_key
        self.cocotb_compile_var = cocotb_compile_var
        self.cocotb_run_args_var = cocotb_run_args_var
        self._sim_args, self._wave_args, self._wave_viewer = sim_args, wave_args, wave_viewer

    def sim_args(self, entity: str) -> List[str]:
        return self._sim_args(entity)

    def wave_args(self, entity: str) -> List[str]:
        return self._wave_args(entity)

    def wave_viewer_cmd(self, entity: str) -> str:
        return self._wave_viewer(entity)


ENGINES = [
    Engine("ghdl", "GHDL", "ghdl", "vhdl", ["--std=08", "-frelaxed"], "ghw", "ghdl.elab_flags", "ghdl.a_flags",
           "COMPILE_ARGS", "EXTRA_ARGS", lambda n: [f"--wave={n}.ghw"], lambda n: [f"--wave={n}.ghw"],
           lambda n: f"gtkwave {n}.ghw &"),
    Engine("icarus", "Icarus Verilog", "icarus", "verilog", ["-g2012"], "vcd", "ghdl.elab_flags", "ghdl.a_flags",
           "COMPILE_ARGS", None, lambda n: [], lambda n: [f"-vcd {n}.vcd"], lambda n: f"gtkwave {n}.vcd &"),
    Engine("verilator", "Verilator", "verilator", "verilog", ["--sv", "-Wno-fatal", "--trace-fst"], "fst",
           "ghdl.elab_flags", "ghdl.a_flags", "COMPILE_ARGS", None, lambda n: [],
           lambda n: ["--trace-fst", f"--trace-file {n}.fst"], lambda n: f"gtkwave {n}.fst &"),
    Engine("questa", "Questa / ModelSim", "questa", "vhdl", ["-2008"], "wlf", "modelsim.vsim_flags",
           "modelsim.vcom_flags", "VCOM_ARGS", None, lambda n: ["-do", "run -all; quit"],
           lambda n: ["-wlf", f"{n}.wlf"], lambda n: f"vsim -view {n}.wlf &"),
]


def get_engine(id_: str) -> Engine:
    return next((e for e in ENGINES if e.id == id_), ENGINES[0])


def _is_sim_path(p: str) -> bool:
    return p.startswith(SIM_PREFIXES)


def _include_dirs(file_sets: Optional[list]) -> List[str]:
    dirs: List[str] = []
    for fs in file_sets or []:
        for f in fs.get("files") or []:
            if f.get("type") in RTL_HDL_TYPES and f.get("isIncludeFile") and not _is_sim_path(f["path"]):
                d = f["path"][: f["path"].rfind("/")] if "/" in f["path"] else "."
                if d not in dirs:
                    dirs.append(d)
    return dirs


def _build_avalon_transport_context(ctx: dict) -> dict:
    prefix = str(ctx.get("bus_prefix") or "")
    ports = ctx.get("bus_ports") if isinstance(ctx.get("bus_ports"), list) else []

    def resolve(logical: str) -> dict:
        port = next((p for p in ports if str(p.get("logical_name") or "").lower() == logical.lower()), None)
        active_low = bool(port) and port.get("effective_polarity") == "activeLow"
        name = port["name"] if port and isinstance(port.get("name"), str) else (f"{prefix}_{logical}" if prefix else logical)
        return {"name": name, "asserted": 0 if active_low else 1, "deasserted": 1 if active_low else 0,
                "active_low": active_low}

    return {
        "address": resolve("address"), "byte_enable": resolve("byteenable"), "read": resolve("read"),
        "read_data": resolve("readdata"), "read_data_valid": resolve("readdatavalid"),
        "wait_request": resolve("waitrequest"), "write": resolve("write"), "write_data": resolve("writedata"),
    }


def generate_cocotb(ctx: dict, engine: Engine) -> Dict[str, str]:
    name, tctx, templates, is_sv, has_mm = ctx["name"], ctx["templateContext"], ctx["templates"], ctx["isSv"], ctx["hasMmSlave"]
    top_level = ctx.get("topLevel") or name
    extra_compile = ctx.get("extraCompileArgs") or []
    extra_sim = ctx.get("extraSimArgs") or []
    extra_env = ctx.get("extraEnv") or {}
    files: Dict[str, str] = {}
    rtl_sources = ctx.get("rtlSourceFiles") or []
    cocotb_ctx = {**tctx, "is_sv": is_sv, "rtl_source_files": rtl_sources,
                  "rtl_include_dirs": _include_dirs(ctx.get("fileSets")), "top_level": top_level}
    test_ctx = {**cocotb_ctx, "avmm_signals": _build_avalon_transport_context(tctx)}
    make_ctx = {
        **cocotb_ctx,
        "engine_sim_var": engine.sim_var,
        "engine_display_name": engine.display_name,
        "engine_compile_args": " ".join(engine.compile_args),
        "engine_cocotb_compile_var": engine.cocotb_compile_var,
        "engine_cocotb_run_args_var": engine.cocotb_run_args_var,
        "engine_wave_ext": engine.wave_ext,
        "engine_wave_args": engine.wave_args(name),
        "engine_wave_viewer_cmd": engine.wave_viewer_cmd(name),
        "engine_top_level_lang": engine.top_level_lang,
        "engine_extra_compile_args": " ".join(extra_compile),
        "engine_extra_sim_args": " ".join(extra_sim),
        "engine_extra_env": [{"key": k, "value": v} for k, v in extra_env.items()],
    }
    if has_mm:
        bus_ports = tctx.get("bus_ports") if isinstance(tctx.get("bus_ports"), list) else []
        byte_enable = any(str(p.get("logical_name")) in ("WSTRB", "byteenable") for p in bus_ports)
        manifest = build_verification_manifest(ctx.get("memoryMaps") or [], {
            "busType": str(tctx.get("bus_type") or ""), "dataWidth": tctx.get("data_width") if tctx.get("data_width") is not None else 32,
            "byteEnableSupported": byte_enable})
        files["tb/verification_manifest.json"] = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
        files["tb/register_model.py"] = templates.render("register_model.py.j2", to_js(tctx))
    files[f"tb/{name}_test.py"] = templates.render("cocotb_test.py.j2", to_js(test_ctx))
    files["tb/conftest.py"] = templates.render("cocotb_conftest.py.j2", to_js(cocotb_ctx))
    files[f"tb/test_{name}_sim.py"] = templates.render("cocotb_pytest.py.j2", to_js(tctx))
    files["tb/Makefile"] = templates.render("cocotb_makefile.sv.j2" if is_sv else "cocotb_makefile.j2", to_js(make_ctx))
    if is_sv:
        files["tb/dump.v"] = templates.render("cocotb_dump.v.j2", to_js(tctx))
    files[".vscode/settings.json"] = templates.render("vscode_settings.json.j2", to_js(tctx))
    return files


def generate_vunit(ctx: dict, engine: Engine) -> Dict[str, str]:
    name, tctx, templates, is_sv, has_mm = ctx["name"], ctx["templateContext"], ctx["templates"], ctx["isSv"], ctx["hasMmSlave"]
    extra_compile = ctx.get("extraCompileArgs") or []
    extra_sim = ctx.get("extraSimArgs") or []
    extra_env = ctx.get("extraEnv") or {}
    vctx = {
        **tctx,
        "is_sv": is_sv,
        "engine_sim_var": engine.sim_var,
        "engine_compile_args": [*engine.compile_args, *extra_compile],
        "engine_extra_sim_args": extra_sim,
        "engine_extra_env": [{"key": k, "value": v} for k, v in extra_env.items()],
        "engine_vunit_sim_option_key": engine.vunit_sim_option_key,
        "engine_vunit_compile_option_key": engine.vunit_compile_option_key,
        "has_memory_mapped_slave": has_mm,
        "rtl_source_files": ctx.get("rtlSourceFiles") or [],
        "rtl_include_dirs": _include_dirs(ctx.get("fileSets")),
    }
    tb_file = f"tb/{name}_tb.sv" if is_sv else f"tb/{name}_tb.vhd"
    tb_template = "vunit_tb.sv.j2" if is_sv else "vunit_tb.vhd.j2"
    return {
        "tb/run.py": templates.render("vunit_run.py.j2", to_js(vctx)),
        tb_file: templates.render(tb_template, to_js(vctx)),
        ".vscode/settings.json": templates.render("vscode_settings.json.j2", to_js(tctx)),
    }


FRAMEWORKS = {"cocotb": generate_cocotb, "vunit": generate_vunit}


def generate_testbench_files(framework_id: str, engine_id: str, ctx: dict) -> Dict[str, str]:
    framework = FRAMEWORKS.get(framework_id, generate_cocotb)
    return framework(ctx, get_engine(engine_id))


# ---------------------------------------------------------------------------
# Verification manifest
# ---------------------------------------------------------------------------

READABLE_ACCESS = {"read-write", "rw", "read-only", "ro", "read-write-1-to-clear", "read-write-self-clearing"}
WRITABLE_ACCESS = {"read-write", "rw", "write-only", "wo", "write-1-to-clear", "read-write-1-to-clear",
                   "write-self-clearing", "read-write-self-clearing"}
U32 = 0xFFFFFFFF


def _i32(v: int) -> int:
    v &= U32
    return v - (1 << 32) if v & 0x80000000 else v


def _width_mask(width: int) -> int:
    return U32 if width >= 32 else 2 ** width - 1


def _normalize_access(access: Optional[str]) -> str:
    return (access if access is not None else "read-write").lower().replace("_", "-")


def _field_mask(field: dict, reg_width: int) -> int:
    available = max(0, min(field["width"], reg_width - field["offset"]))
    if available == 0:
        return 0
    return (_i32(_width_mask(available) << (field["offset"] & 31))) & U32


def _write_effect(access: str) -> str:
    if access in ("write-1-to-clear", "read-write-1-to-clear"):
        return "clearOnOne"
    if access in ("write-self-clearing", "read-write-self-clearing"):
        return "setOnOne"
    return "replace" if access in WRITABLE_ACCESS else "none"


def _project_field(field: dict, reg_width: int) -> dict:
    access = _normalize_access(field.get("access"))
    effect = _write_effect(access)
    hw_priority = "hardwareSet" if effect == "clearOnOne" else "hardwareClear" if effect == "setOnOne" else None
    out: Dict[str, Any] = {
        "name": field["name"], "bitOffset": field["offset"], "bitWidth": field["width"],
        "mask": _field_mask(field, reg_width), "access": access, "resetValue": field["resetValue"],
        "readable": access in READABLE_ACCESS, "writable": access in WRITABLE_ACCESS, "writeEffect": effect,
    }
    if hw_priority:
        out["hardwareSoftwarePriority"] = hw_priority
    prov = {"layout": "spec", "access": "spec", "resetValue": "spec", "writeEffect": "generatorPolicy"}
    if hw_priority:
        prov["hardwareSoftwarePriority"] = "generatorPolicy"
    out["provenance"] = prov
    return out


def _compose_reset_value(reg: dict, fields: List[dict], reg_width: int) -> int:
    if not fields or reg["resetValue"] != 0:
        return (int(reg["resetValue"]) & _width_mask(reg_width)) & U32
    value = 0
    for f in fields:
        field_value = _i32(f["resetValue"] << (f["bitOffset"] & 31)) & f["mask"]
        value = ((value & ~f["mask"]) | field_value) & U32
    return value


def _project_leaf(reg: dict, offset: int, name: str, default_width: int, dims: List[dict]) -> dict:
    reg_width = reg["size"] if reg["size"] > 0 else default_width
    if reg.get("fields"):
        fields = [_project_field(f, reg_width) for f in reg["fields"]]
    else:
        fields = [_project_field({"name": reg["name"], "offset": 0, "width": reg_width, "access": reg.get("access"),
                                  "resetValue": reg["resetValue"]}, reg_width)]
    readable = 0
    writable = 0
    for f in fields:
        if f["readable"]:
            readable = (readable | f["mask"]) & U32
        if f["writable"]:
            writable = (writable | f["mask"]) & U32
    prov = {"identity": "spec", "layout": "spec", "resetValue": "spec", "masks": "generatorPolicy"}
    if dims:
        prov["arrayBounds"] = "spec"
    return {"name": name, "offset": offset, "width": reg_width,
            "resetValue": _compose_reset_value(reg, fields, reg_width), "readableMask": readable & U32,
            "writableMask": writable & U32, "fields": fields, "arrayDimensions": dims, "provenance": prov}


def _expand_register(reg: dict, base_offset: int, prefix: str, default_width: int, dims: List[dict], out: List[dict]) -> None:
    current = base_offset + reg["offset"]
    count = reg.get("count") if reg.get("count") is not None else 1
    stride = reg.get("stride") if reg.get("stride") is not None else max(1, default_width / 8)
    if stride == int(stride):
        stride = int(stride)
    if reg.get("registers"):
        for index in range(count):
            child_prefix = f"{prefix}{reg['name']}_{index}_" if count > 1 else f"{prefix}{reg['name']}_"
            child_dims = dims + [{"name": reg["name"], "index": index, "lowerBound": 0, "upperBound": count - 1,
                                  "stride": stride}] if count > 1 else dims
            for child in reg["registers"]:
                _expand_register(child, current + index * stride, child_prefix, default_width, child_dims, out)
        return
    for index in range(count):
        is_array = count > 1
        adims = dims + [{"name": reg["name"], "index": index, "lowerBound": 0, "upperBound": count - 1,
                         "stride": stride}] if is_array else dims
        name = f"{prefix}{reg['name']}_{index}" if is_array else f"{prefix}{reg['name']}"
        out.append(_project_leaf(reg, current + index * stride, name, default_width, adims))


def build_verification_manifest(maps: List[dict], binding: dict) -> dict:
    registers: List[dict] = []
    for m in maps:
        for block in m["addressBlocks"]:
            for reg in block["registers"]:
                _expand_register(reg, block["baseAddress"], "", block["defaultRegWidth"], [], registers)
    dw = binding["dataWidth"]
    return {
        "schemaVersion": 1,
        "source": {"model": "normalizedMemoryMap", "provenance": "spec"},
        "bus": {
            "type": {"value": binding["busType"], "provenance": "busBinding"},
            "dataWidth": {"value": dw, "provenance": "busBinding"},
            "byteEnable": {"value": {
                "supported": binding["byteEnableSupported"], "laneCount": -(-int(dw) // 8),
                "behavior": "perByteWriteMask" if binding["byteEnableSupported"] else "allBytesEnabled"},
                "provenance": "busBinding"},
        },
        "policies": {
            "reservedBitsReadAsZero": {"value": True, "provenance": "generatorPolicy"},
            "unmappedReadsReturnZero": {"value": True, "provenance": "generatorPolicy"},
            "writeOneToClearPriority": {"value": "hardwareSet", "provenance": "generatorPolicy"},
            "selfClearingPriority": {"value": "hardwareClear", "provenance": "generatorPolicy"},
        },
        "registers": sorted(registers, key=lambda r: r["offset"]),
    }
