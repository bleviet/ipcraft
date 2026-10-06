import json

import pytest

from ipcraft.scaffold import widthexpr as wx
from ipcraft.scaffold.buscontracts import resolve_bus_interface
from ipcraft.scaffold.jsutil import js_yaml_dump
from ipcraft.scaffold.loader import check_bus_conformance, load_bus_library
from ipcraft.scaffold.packs import check_pack_requirements, load_pack, resolve_scaffold_output_path
from ipcraft.scaffold.templates_env import TemplateLoader, to_js


def test_width_expressions_serialize_per_dialect():
    ast = wx.parse("clog2(DEPTH)+DW/8")
    assert wx.serialize(ast, "vhdl")[0] == "integer(ceil(log2(real(DEPTH))))+DW/8"
    assert wx.serialize(ast, "systemverilog")[0] == "$clog2(DEPTH)+DW/8"
    assert wx.eval_width_expr("DW/8", {"DW": 32}) == 4
    assert wx.serialize(wx.parse("clog2(8)"), "vhdl") == ("3", False)
    assert wx.parse("frob(1)") is None and wx.parse("1+") is None


def test_collapse_vhdl_function_calls():
    assert wx.collapse_vhdl_function_calls_in_expr("integer(ceil(log2(real(DW/2))))") == "clog2(DW/2)"


def test_axi_lite_contract_resolution():
    lib = load_bus_library()
    res = resolve_bus_interface({"name": "S", "type": "AXI4L", "mode": "slave", "physicalPrefix": "s_axi_"}, 0, [], lib)
    assert res["normalizedMode"] == "slave" and not res["diagnostics"]
    widths = {p["name"]: res["portWidths"][p["name"]].get("value") for p in res["activePorts"]}
    assert widths["AWADDR"] == 32 and widths["ACLK"] == 1


def test_polarity_override_derives_physical_names():
    lib = load_bus_library()
    bus = {"name": "S", "type": "AVALON_MM", "mode": "slave", "physicalPrefix": "avs_",
           "useOptionalPorts": ["waitrequest"], "portPolarityOverrides": {"waitrequest": "activeLow"}}
    res = resolve_bus_interface(bus, 0, [], lib)
    port = next(p for p in res["activePorts"] if p["name"] == "waitrequest")
    assert port["needsPolarityInversion"] and port["physicalSuffix"] == "waitrequest_n"


def test_conformance_reports_invalid_override():
    lib = load_bus_library()
    ip = {"busInterfaces": [{"name": "S", "type": "AXI4L", "mode": "slave", "portWidthOverrides": {"WSTRB": 3}}], "parameters": []}
    report = check_bus_conformance(ip, lib)
    assert report["hasKnownErrors"]


def test_nunjucks_emulation(tmp_path):
    (tmp_path / "t.j2").write_text("{# c #}\n{% if items %}T{% else %}F{% endif %}|{{ none_val }}|{{ flag }}|{{ 'a' ~ flag }}|{{ lst }}|{% set _ = arr.push(1) %}{{ arr | length }}\n")
    out = TemplateLoader(str(tmp_path)).render("t.j2", to_js({"items": [], "none_val": None, "flag": False, "lst": [1, 2], "arr": []}))
    assert out == "\nF||false|afalse|1,2|1\n" or out == "\nT||false|afalse|1,2|1\n"
    assert out.split("|")[0].endswith("T")  # empty arrays are truthy, like in JavaScript


def test_js_yaml_dump_matches_js_yaml_conventions():
    text = js_yaml_dump({"a": ["x", {"b": "N", "c": "1.0.0", "d": "12e3"}], "z": None})
    assert text == "a:\n  - x\n  - b: 'N'\n    c: 1.0.0\n    d: '12e3'\nz: null\n"
    folded = js_yaml_dump({"d": ("word " * 40).strip()}, line_width=60)
    assert folded.startswith("d: >-\n  word word")


def test_scaffold_output_paths_cannot_escape(tmp_path):
    for bad in ("../x", "/abs", "a/../../b", "C:/x", ""):
        with pytest.raises(ValueError):
            resolve_scaffold_output_path(str(tmp_path), bad)
    assert resolve_scaffold_output_path(str(tmp_path), "rtl/x.vhd").endswith("rtl/x.vhd")


def test_pack_requirements_are_checked():
    pack = {"name": "p", "requirements": {"hdlLanguages": ["vhdl"], "memoryMappedSlave": "required", "logicalPorts": ["WSTRB"]}}
    with pytest.raises(ValueError, match="incompatible"):
        check_pack_requirements(pack, "systemverilog", "axil", False, ["AWADDR"])
    check_pack_requirements(pack, "vhdl", "axil", True, ["WSTRB"])


def test_builtin_pack_manifest_loads():
    from ipcraft.scaffold.packs import BUILTIN_PACKS_DIR

    pack = load_pack(str(BUILTIN_PACKS_DIR / "builtin-ipcraft"))
    assert pack["fullGeneration"] and any(f["target"].endswith("_regs.vhd") for f in pack["files"])
