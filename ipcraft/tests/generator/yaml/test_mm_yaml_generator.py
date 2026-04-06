"""
Tests for MmYamlGenerator.
"""

from pathlib import Path

import pytest
import yaml

from ipcraft.generator.yaml.mm_yaml_generator import MmYamlGenerator
from ipcraft.model import IpCore, VLNV


def _make_ip_core(name="test_core"):
    return IpCore(vlnv=VLNV(vendor="test", library="lib", name=name, version="1.0"))


class TestMmYamlGeneratorSkeleton:
    """Tests for skeleton (no discovered registers) mode."""

    def _get_registers(self, result: str) -> list:
        """Navigate nested skeleton structure to the registers list."""
        data = yaml.safe_load(result)
        return data[0]["addressBlocks"][0]["registers"]

    def test_returns_string(self):
        gen = MmYamlGenerator()
        result = gen.generate(_make_ip_core())
        assert isinstance(result, str)

    def test_skeleton_has_registers_key(self):
        gen = MmYamlGenerator()
        result = gen.generate(_make_ip_core())
        data = yaml.safe_load(result)
        assert isinstance(data, list)
        assert "addressBlocks" in data[0]
        assert "registers" in data[0]["addressBlocks"][0]

    def test_skeleton_has_placeholder_registers(self):
        gen = MmYamlGenerator()
        result = gen.generate(_make_ip_core())
        reg_names = {r["name"] for r in self._get_registers(result)}
        assert "CTRL" in reg_names
        assert "STATUS" in reg_names

    def test_skeleton_has_module_reference(self):
        gen = MmYamlGenerator()
        result = gen.generate(_make_ip_core("my_module"))
        assert "my_module" in result

    def test_skeleton_fields_are_present(self):
        gen = MmYamlGenerator()
        result = gen.generate(_make_ip_core())
        for reg in self._get_registers(result):
            assert "fields" in reg
            assert len(reg["fields"]) >= 1


class TestMmYamlGeneratorPopulated:
    """Tests for populated mode (with discovered registers from IP-XACT)."""

    def _make_discovered_regs(self):
        return [
            {
                "name": "CTRL",
                "offset": "0x0",
                "fields": [
                    {"name": "EN", "bits": "0", "access": "RW", "description": "Enable"},
                ],
            },
            {
                "name": "STATUS",
                "offset": "0x4",
                "fields": [
                    {"name": "RDY", "bits": "0", "access": "RO", "description": "Ready"},
                ],
            },
        ]

    def test_populated_has_both_registers(self):
        gen = MmYamlGenerator()
        result = gen.generate(_make_ip_core(), discovered_regs=self._make_discovered_regs())
        data = yaml.safe_load(result)
        reg_names = {r["name"] for r in data}
        assert "CTRL" in reg_names
        assert "STATUS" in reg_names

    def test_populated_preserves_offsets(self):
        gen = MmYamlGenerator()
        result = gen.generate(_make_ip_core(), discovered_regs=self._make_discovered_regs())
        data = yaml.safe_load(result)
        ctrl = next(r for r in data if r["name"] == "CTRL")
        assert ctrl["offset"] == "0x0"

    def test_populated_preserves_fields(self):
        gen = MmYamlGenerator()
        result = gen.generate(_make_ip_core(), discovered_regs=self._make_discovered_regs())
        data = yaml.safe_load(result)
        status = next(r for r in data if r["name"] == "STATUS")
        assert len(status["fields"]) == 1
        assert status["fields"][0]["name"] == "RDY"

    def test_empty_discovered_regs_uses_skeleton(self):
        """An empty list should fall back to skeleton placeholders."""
        gen = MmYamlGenerator()
        result = gen.generate(_make_ip_core(), discovered_regs=[])
        data = yaml.safe_load(result)
        regs = data[0]["addressBlocks"][0]["registers"]
        reg_names = {r["name"] for r in regs}
        assert "CTRL" in reg_names
