import json
import subprocess
import sys

from .conftest import FIXTURES, tree


def run(*args, cwd=None):
    return subprocess.run([sys.executable, "-m", "ipcraft.cli", *args], cwd=cwd, capture_output=True, text=True)


def test_generate_with_target_and_lang(led_project):
    ip, out = led_project
    r = run("generate", str(ip), "--lang", "systemverilog", "--pack", "builtin-ipcraft", "--target", "quartus,vivado", "--out", str(out))
    assert r.returncode == 0, r.stderr
    files = tree(out)
    assert "rtl/led_controller_avmm.sv" in files and "altera/led_controller_avmm_hw.tcl" in files
    assert "xilinx/component.xml" in files


def test_verify_exit_status(led_project):
    ip, out = led_project
    base = [str(ip), "--lang", "vhdl", "--pack", "builtin-ipcraft"]
    assert run("generate", *base, "--out", str(out)).returncode == 0
    assert run("verify", *base[:1], str(out), *base[1:]).returncode == 0
    (out / "rtl" / "led_controller_avmm.vhd").write_text("x")
    r = run("verify", base[0], str(out), *base[1:], "--json")
    assert r.returncode == 1
    assert json.loads(r.stdout)["staleFiles"] == ["rtl/led_controller_avmm.vhd"]


def test_dry_run_writes_nothing(led_project):
    ip, out = led_project
    r = run("generate", str(ip), "--lang", "vhdl", "--dry-run", "--out", str(out))
    assert r.returncode == 0 and "Dry run" in r.stdout and not out.exists()


def test_pack_list_and_export(tmp_path):
    r = run("pack", "list", "--json")
    names = {p["name"] for p in json.loads(r.stdout)["packs"]}
    assert {"builtin-ipcraft", "builtin-minimal"} <= names
    r = run("pack", "export", "builtin-ipcraft", str(tmp_path / "mypack"))
    assert r.returncode == 0 and (tmp_path / "mypack" / "scaffold.yml").exists()
    assert (tmp_path / "mypack" / "top.vhdl.j2").exists()
    assert run("pack", "export", "builtin-ipcraft", str(tmp_path / "mypack")).returncode == 1


def test_import_command(tmp_path):
    import shutil

    shutil.copy(FIXTURES / "import" / "t5.vhd", tmp_path / "t5.vhd")
    r = run("import", str(tmp_path / "t5.vhd"))
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "t5.ip.yml").exists()
    assert run("import", str(tmp_path / "t5.vhd"), "--json").returncode == 0
    (tmp_path / "t5.ip.yml").write_text("changed")
    assert run("import", str(tmp_path / "t5.vhd")).returncode == 1
    assert run("import", str(tmp_path / "t5.vhd"), "--force").returncode == 0


def test_migrate_upgrades_format_version(tmp_path):
    p = tmp_path / "c.ip.yml"
    p.write_text("""vlnv: {vendor: a, library: l, name: c, version: 1.0.0}
busInterfaces:
- name: S
  type: AVALON_MM
  mode: slave
  physicalPrefix: avs_
  useOptionalPorts: [read_n, readdata]
""")
    assert run("migrate", str(p), "--check").returncode == 1
    r = run("migrate", str(p))
    assert r.returncode == 0 and "1.0 -> 1.1" in r.stdout
    text = p.read_text()
    assert "apiVersion: '1.1'" in text and "portPolarityOverrides" in text
    assert run("migrate", str(p), "--check").returncode == 0
