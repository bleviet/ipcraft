"""Importers must reproduce the ipcraft-vscode importer output exactly."""

import json
import shutil

import pytest

from ipcraft.scaffold.importers import import_source
from ipcraft.scaffold.importers.hwtcl import parse_hwtcl_file
from ipcraft.scaffold.importers.component_xml import parse_component_xml_file
from ipcraft.scaffold.importers.verilog import parse_verilog_file
from ipcraft.scaffold.importers.vhdl import parse_vhdl_file
from ipcraft.scaffold.instance import build_instance
from ipcraft.scaffold.loader import load_bus_library

from .conftest import FIXTURES, GOLDEN_IMPORT

IMPORT = FIXTURES / "import"


def _golden(name):
    return (GOLDEN_IMPORT / f"{name}.ip.yml").read_text(), json.loads((GOLDEN_IMPORT / f"{name}.meta.json").read_text())


@pytest.fixture(scope="module")
def library():
    return load_bus_library("/tmp/x/a.ip.yml", {})


@pytest.mark.parametrize("name", ["t1.vhd", "t2.vhd", "t5.vhd"])
def test_vhdl_import(name, library):
    result = parse_vhdl_file(str(IMPORT / name), {"detectBus": True, "busLibrary": library, "outputDir": str(IMPORT)})
    text, meta = _golden(name)
    assert result["yamlText"] == text
    assert result["warnings"] == meta["warnings"]


@pytest.mark.parametrize("name", ["a.sv", "b.v"])
def test_verilog_import(name, library):
    result = parse_verilog_file(str(IMPORT / name), {"detectBus": True, "busLibrary": library, "outputDir": str(IMPORT)})
    text, meta = _golden(name)
    assert result["yamlText"] == text and result["warnings"] == meta["warnings"]


def test_hw_tcl_import(library):
    name = "trivial_default_avalon_slave_hw.tcl"
    result = parse_hwtcl_file(str(IMPORT / name), {"busLibrary": library, "library": "ip", "vendor": "acme", "outputDir": str(IMPORT)})
    text, meta = _golden(name)
    assert result["yamlText"] == text and result["warnings"] == meta["warnings"]


def test_component_xml_import(library):
    result = parse_component_xml_file(str(IMPORT / "pwm_component.xml"), {"busLibrary": library, "library": "ip"})
    text, _meta = _golden("pwm_component.xml")
    assert result["ipYamlText"] == text
    assert result["mmYamlText"] == (GOLDEN_IMPORT / "pwm_component.xml.mm.yml").read_text()
    assert result["mmFileName"] == "PWM.mm.yml"


def test_import_source_writes_vendor_subdir_one_level_up(tmp_path):
    (tmp_path / "xilinx").mkdir()
    shutil.copy(IMPORT / "pwm_component.xml", tmp_path / "xilinx" / "component.xml")
    result = import_source(str(tmp_path / "xilinx" / "component.xml"))
    assert {f["name"] for f in result["files"]} == {"PWM.ip.yml", "PWM.mm.yml"}
    assert all(f["dir"] == str(tmp_path) for f in result["files"])
    assert not result["report"]["hasKnownErrors"]


def test_import_rejects_unknown_extension(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("hi")
    with pytest.raises(ValueError, match="Unsupported"):
        import_source(str(p))


def test_instance_snippets():
    vhdl = build_instance(str(IMPORT / "t1.vhd"))
    assert vhdl.startswith("u_Fancy_Core : entity work.Fancy_Core\n  generic map (")
    assert "    DATA_W => DATA_W," in vhdl and vhdl.endswith("  );")
    sv = build_instance(str(IMPORT / "a.sv"))
    assert sv.startswith("fancy #(\n  .DATA_W (DATA_W),") and sv.endswith(");")
