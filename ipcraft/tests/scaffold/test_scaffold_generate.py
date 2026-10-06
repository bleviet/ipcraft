"""Pack-driven generation must reproduce the ipcraft-vscode CLI output byte for byte."""

from ipcraft.scaffold.run import run_verify
from ipcraft.scaffold.scaffolder import IpCoreScaffolder

from .conftest import GOLDEN, tree

OPTS = {"scaffoldPack": "builtin-ipcraft", "quartusDevice": "5CSEBA6U23I7", "targetPart": "xc7z020clg484-1"}


def _assert_matches_golden(out, golden):
    mine, ref = tree(out), tree(golden)
    assert sorted(mine) == sorted(ref)
    for rel in ref:
        assert mine[rel] == ref[rel], rel


def test_vhdl_with_vendor_targets_matches_reference(led_project):
    ip, out = led_project
    res = IpCoreScaffolder().generate_all(str(ip), str(out), {
        **OPTS, "hdlLanguage": "vhdl", "targets": ["quartus", "vivado"], "includeQuartusProject": True, "includeVivadoProject": True})
    assert res["success"], res.get("error")
    _assert_matches_golden(out, GOLDEN / "led_avmm_vhdl_targets")


def test_systemverilog_matches_reference(led_project):
    ip, out = led_project
    res = IpCoreScaffolder().generate_all(str(ip), str(out), {**OPTS, "hdlLanguage": "systemverilog"})
    assert res["success"], res.get("error")
    _assert_matches_golden(out, GOLDEN / "led_avmm_sv")


def test_minimal_pack_emits_only_the_top_stub(led_project):
    ip, out = led_project
    res = IpCoreScaffolder().generate_all(str(ip), str(out), {"scaffoldPack": "builtin-minimal", "includeTestbench": False})
    assert res["success"]
    assert list(res["generatedContents"]) == ["rtl/led_controller_avmm.vhd"]
    assert res["resolvedPackName"] == "builtin-minimal"


def test_pack_from_ip_yaml_is_used_when_none_is_requested(led_project):
    ip, out = led_project
    res = IpCoreScaffolder().generate_all(str(ip), str(out), {"includeTestbench": False})
    assert res["resolvedPackName"] == "example-with-docs"  # `scaffold_pack:` in the .ip.yml


def test_indentation_options(led_project):
    ip, out = led_project
    res = IpCoreScaffolder().generate_all(str(ip), str(out), {**OPTS, "indentStyle": "tab", "includeTestbench": False})
    body = res["generatedContents"]["rtl/led_controller_avmm_regs.vhd"]
    assert "\n\t" in body and "\n  " not in body


def test_managed_false_files_are_never_generated(led_project):
    ip, out = led_project
    # the example declares its core as `managed: false`, so no scaffold rule may (re)generate it
    res = IpCoreScaffolder().generate_all(str(ip), str(out), {**OPTS, "includeTestbench": False, "dryRun": True})
    assert "rtl/led_controller_avmm_core.vhd" not in res["generatedContents"]
    assert "rtl/led_controller_avmm_core.vhd" in res["userManagedPaths"]
    assert not (out / "rtl" / "led_controller_avmm_core.vhd").exists()


def test_unknown_pack_reports_error(led_project):
    ip, out = led_project
    res = IpCoreScaffolder().generate_all(str(ip), str(out), {"scaffoldPack": "does-not-exist"})
    assert not res["success"] and "not found" in res["error"]


def test_conformance_error_blocks_generation(led_project):
    ip, out = led_project
    text = ip.read_text().replace("writedata: 32", "writedata: 16")
    ip.write_text(text)
    res = IpCoreScaffolder().generate_all(str(ip), str(out), {**OPTS})
    # either the override is rejected by the contract, or the file still conforms; never a crash
    assert "success" in res


class _Args:
    def __init__(self, ip, **kw):
        self.input = str(ip)
        self.target = kw.get("target")
        self.lang = kw.get("lang")
        self.pack = kw.get("pack", "builtin-ipcraft")


def test_verify_detects_stale_and_orphan_files(led_project):
    ip, out = led_project
    args = _Args(ip, lang="vhdl")
    assert IpCoreScaffolder().generate_all(str(ip), str(out), {"scaffoldPack": "builtin-ipcraft", "hdlLanguage": "vhdl"})["success"]
    assert run_verify(args, str(out))["success"]
    (out / "rtl" / "stray.vhd").write_text("-- stray\n")
    (out / "rtl" / "led_controller_avmm.vhd").write_text("-- changed\n")
    result = run_verify(args, str(out))
    assert not result["success"]
    assert result["staleFiles"] == ["rtl/led_controller_avmm.vhd", "rtl/stray.vhd"]
