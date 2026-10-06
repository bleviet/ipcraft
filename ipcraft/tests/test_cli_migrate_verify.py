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
