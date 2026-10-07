"""Tests for the ``migrate`` and ``verify`` CLI commands."""

import subprocess
import sys

import pytest

from ipcraft.migrate import migrate_ip_core_yaml, migrate_memory_map_yaml

LEGACY_MM = """\
- name: M
  address_blocks:
  - name: b
    base_address: 0
    registers:
    - name: A
      address_offset: 4 # keep me
      reset_value: 1
      fields:
      - name: f
        bit_offset: 0
        bit_width: 1
"""


def test_memory_map_keys_renamed_preserving_comments():
    res = migrate_memory_map_yaml(LEGACY_MM)
    assert res.changed and res.mutation_count == 6
    assert "offset: 4 # keep me" in res.text
    assert "addressBlocks:" in res.text and "resetValue: 1" in res.text
    assert "_" not in res.text.replace("# keep me", "").replace("-", "")


def test_migrate_is_idempotent():
    once = migrate_memory_map_yaml(LEGACY_MM).text
    again = migrate_memory_map_yaml(once)
    assert not again.changed and again.text == once


def test_legacy_key_dropped_when_canonical_present():
    text = "- name: M\n  addressBlocks: []\n  address_blocks: []\n"
    res = migrate_memory_map_yaml(text)
    assert res.text == "- name: M\n  addressBlocks: []\n"


def test_ip_core_keys_renamed():
    text = (
        "vlnv: {vendor: v, library: l, name: n, version: '1.0'}\n"
        "file_sets: []\n"
        "busInterfaces:\n"
        "- name: S\n  use_optional_ports: [a]\n"
    )
    res = migrate_ip_core_yaml(text)
    assert "fileSets: []" in res.text and "useOptionalPorts" in res.text
    assert res.mutation_count == 2


def test_invalid_yaml_raises():
    with pytest.raises(ValueError):
        migrate_ip_core_yaml("a: [")


def _run(*args, cwd):
    return subprocess.run(
        [sys.executable, "-m", "ipcraft.cli", *args], cwd=cwd, capture_output=True, text=True
    )


def test_cli_migrate_check_and_write(tmp_path):
    f = tmp_path / "x.mm.yml"
    f.write_text(LEGACY_MM)
    assert _run("migrate", "--check", str(f), cwd=tmp_path).returncode == 1
    assert f.read_text() == LEGACY_MM
    assert _run("migrate", str(f), cwd=tmp_path).returncode == 0
    assert "addressBlocks" in f.read_text()
    assert _run("migrate", "--check", str(f), cwd=tmp_path).returncode == 0


def test_cli_verify_detects_drift(tmp_path):
    assert _run("new", "demo", "--bus", "AXI4_LITE", "-o", str(tmp_path), cwd=tmp_path).returncode == 0
    ip = str(tmp_path / "demo.ip.yml")
    out = tmp_path / "out"
    assert _run("generate", ip, "-o", str(out), cwd=tmp_path).returncode == 0
    assert _run("verify", ip, str(out), cwd=tmp_path).returncode == 0
    (out / "rtl" / "orphan.vhd").write_text("-- stray\n")
    res = _run("verify", ip, str(out), cwd=tmp_path)
    assert res.returncode == 1 and "rtl/orphan.vhd" in res.stderr


# Expected texts below are the output of the ipcraft-vscode 1.1.0 CLI (`ipcraft migrate`).

def _library():
    from ipcraft.scaffold.loader import load_bus_library

    return load_bus_library("x.ip.yml", {})


IP_V11 = """\
vlnv: {vendor: v, library: l, name: n, version: 1.0.0}
apiVersion: '1.1'
busInterfaces:
  - name: s_axi
    type: ipcraft.busif.axi4_lite.1.0   # dotted
    mode: slave
    memoryMapRef: CSR_OLD
  - name: m_axis
    type: 'ipcraft.busif.axi_stream.1.0'
    mode: master
    useOptionalPorts: [TLAST]
"""


def test_dotted_bus_types_and_dangling_memory_map_ref():
    res = migrate_ip_core_yaml(IP_V11, _library(), ["CSR"])
    assert res.changed and res.mutation_count == 3 and res.from_version == res.to_version == "1.1"
    assert res.text == IP_V11.replace(
        "type: ipcraft.busif.axi4_lite.1.0   # dotted", "type: ipcraft:busif:axi4_lite:1.0 # dotted").replace(
        "CSR_OLD", "CSR").replace("'ipcraft.busif.axi_stream.1.0'", "'ipcraft:busif:axi_stream:1.0'")


def test_dangling_memory_map_ref_left_alone_when_ambiguous():
    lib = _library()
    assert "CSR_OLD" in migrate_ip_core_yaml(IP_V11, lib, ["A", "B"]).text
    assert "CSR_OLD" in migrate_ip_core_yaml(IP_V11, lib, None).text


def test_rename_rerenders_only_the_touched_lines():
    text = (
        "name: CSR\n"
        "address_blocks:\n"
        "  - name: regs\n"
        "    base_address: 0x0\n"
        "    registers:\n"
        "      - name: CTRL\n"
        "        address_offset: 0x04\n"
        "        reset_value: 0x0   # zero\n"
        "        fields: [{name: EN, bit_offset: 0, bit_width: 1}]\n"
        "        description: [untouched]\n"
    )
    assert migrate_memory_map_yaml(text).text == (
        "name: CSR\n"
        "addressBlocks:\n"
        "  - name: regs\n"
        "    baseAddress: 0x0\n"
        "    registers:\n"
        "      - name: CTRL\n"
        "        offset: 0x04\n"
        "        resetValue: 0x0 # zero\n"
        "        fields: [ { name: EN, offset: 0, width: 1 } ]\n"
        "        description: [untouched]\n"
    )


def test_version_upgrade_keeps_untouched_formatting():
    text = (
        "vlnv: {vendor: v, library: l, name: n, version: 1.0.0}\n"
        "description: A long plain description that the original author\n"
        "  wrapped over two lines\n"
        "parameters:\n"
        "  - name: W\n"
        "    value: 8\n"
        "    allowedValues: [ 8, 16 ]\n"
        "busInterfaces:\n"
        "  - name: s0\n"
        "    type: ipcraft:busif:avalon_mm:1.0\n"
        "    mode: slave\n"
        "    useOptionalPorts:\n"
        "      - read_n        # active low\n"
        "      - write\n"
        "    portWidthOverrides: {address: 4}\n"
    )
    res = migrate_ip_core_yaml(text, _library())
    # The lines next to the inserted apiVersion overlap that edit, so TS re-renders them too.
    assert res.text == (
        "vlnv: { vendor: v, library: l, name: n, version: 1.0.0 }\n"
        "apiVersion: '1.1'\n"
        "description: A long plain description that the original author wrapped over two lines\n"
        "parameters:\n"
        "  - name: W\n"
        "    value: 8\n"
        "    allowedValues: [ 8, 16 ]\n"
        "busInterfaces:\n"
        "  - name: s0\n"
        "    type: ipcraft:busif:avalon_mm:1.0\n"
        "    mode: slave\n"
        "    useOptionalPorts:\n"
        "      - read\n"
        "      - write\n"
        "    portWidthOverrides: {address: 4}\n"
        "    portPolarityOverrides:\n"
        "      read: activeLow\n"
    )


def test_cli_migrate_keeps_crlf(tmp_path):
    f = tmp_path / "x.mm.yml"
    f.write_bytes(LEGACY_MM.replace("\n", "\r\n").encode())
    res = _run("migrate", str(f), cwd=tmp_path)
    assert res.returncode == 0 and res.stdout.startswith(f"Upgraded {f} (6 change(s))")
    data = f.read_bytes()
    assert b"addressBlocks:\r\n" in data and b"\n" not in data.replace(b"\r\n", b"")
