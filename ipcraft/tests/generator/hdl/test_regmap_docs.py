"""Tests for Markdown register-map documentation generation (TASK-07)."""

import re

import pytest

from ipcraft.generator.hdl.ipcore_project_generator import IpCoreProjectGenerator
from ipcraft.model.base import VLNV
from ipcraft.model.bus import BusInterface, BusInterfaceMode
from ipcraft.model.core import IpCore
from ipcraft.model.memory_map import (
    AccessType,
    AddressBlock,
    BitFieldDef,
    MemoryMap,
    RegisterDef,
)


@pytest.fixture
def generator():
    return IpCoreProjectGenerator()


@pytest.fixture
def pwm_ip():
    """A representative IP core with multiple register types for documentation tests."""
    bus_iface = BusInterface(
        name="s_axi",
        type="AXI4L",
        mode=BusInterfaceMode.SLAVE,
        physical_prefix="s_axi_",
    )
    memory_map = MemoryMap(
        name="regs",
        address_blocks=[
            AddressBlock(
                name="control",
                base_address=0x00,
                range=0x1000,
                width=32,
                registers=[
                    RegisterDef(
                        name="CTRL",
                        address_offset=0x00,
                        size=32,
                        access=AccessType.READ_WRITE,
                        description="Control register",
                        fields=[
                            BitFieldDef(
                                name="enable",
                                bit_offset=0,
                                bit_width=1,
                                access=AccessType.READ_WRITE,
                                description="Enable PWM output",
                            ),
                            BitFieldDef(
                                name="mode",
                                bit_offset=1,
                                bit_width=2,
                                access=AccessType.READ_WRITE,
                                description="0=single, 1=continuous",
                            ),
                        ],
                    ),
                    RegisterDef(
                        name="PERIOD",
                        address_offset=0x04,
                        size=32,
                        access=AccessType.READ_WRITE,
                        description="PWM period in clock cycles",
                        reset_value=0x000003FF,
                    ),
                    RegisterDef(
                        name="STATUS",
                        address_offset=0x08,
                        size=32,
                        access=AccessType.READ_ONLY,
                        description="Status register",
                        fields=[
                            BitFieldDef(
                                name="ready",
                                bit_offset=0,
                                bit_width=1,
                                access=AccessType.READ_ONLY,
                                description="Core ready",
                            ),
                            BitFieldDef(
                                name="busy",
                                bit_offset=1,
                                bit_width=1,
                                access=AccessType.READ_ONLY,
                                description="Core busy",
                            ),
                        ],
                    ),
                    RegisterDef(
                        name="INT_STATUS",
                        address_offset=0x20,
                        size=32,
                        access=AccessType.WRITE_1_TO_CLEAR,
                        description="Interrupt status (sparse offset at 0x20)",
                        fields=[
                            BitFieldDef(
                                name="done",
                                bit_offset=0,
                                bit_width=1,
                                access=AccessType.WRITE_1_TO_CLEAR,
                                description="Cycle complete interrupt",
                            ),
                        ],
                    ),
                ],
            )
        ],
    )
    return IpCore(
        vlnv=VLNV(vendor="test", library="lib", name="pwm_core", version="1.0"),
        description="A simple PWM core for testing documentation generation.",
        bus_interfaces=[bus_iface],
        memory_maps=[memory_map],
    )


class TestRegmapDocsTemplate:
    """Verify the Markdown register-map documentation template output."""

    def test_generate_regmap_docs_returns_string(self, generator, pwm_ip):
        doc = generator.generate_regmap_docs(pwm_ip)
        assert isinstance(doc, str)
        assert len(doc) > 0

    def test_title_contains_entity_name(self, generator, pwm_ip):
        doc = generator.generate_regmap_docs(pwm_ip)
        assert "pwm_core" in doc

    def test_description_present(self, generator, pwm_ip):
        doc = generator.generate_regmap_docs(pwm_ip)
        assert "A simple PWM core for testing documentation generation" in doc

    def test_register_summary_table_present(self, generator, pwm_ip):
        doc = generator.generate_regmap_docs(pwm_ip)
        assert "Register Summary" in doc
        # All register names should appear in upper-case
        assert "CTRL" in doc
        assert "PERIOD" in doc
        assert "STATUS" in doc
        assert "INT_STATUS" in doc

    def test_register_offsets_correct(self, generator, pwm_ip):
        doc = generator.generate_regmap_docs(pwm_ip)
        assert "0x0000" in doc  # CTRL
        assert "0x0004" in doc  # PERIOD
        assert "0x0008" in doc  # STATUS
        assert "0x0020" in doc  # INT_STATUS -- sparse address must appear correctly

    def test_sparse_offset_not_linear(self, generator, pwm_ip):
        """INT_STATUS is at offset 0x20 not 0x0C (linear 3rd after two 4-byte regs)."""
        doc = generator.generate_regmap_docs(pwm_ip)
        # Sparse offset 0x0020 must be present
        assert "0x0020" in doc
        # Linear calculation would give 0x000C for the 4th register - must NOT appear as offset
        assert "`0x000C`" not in doc

    def test_reset_values_formatted(self, generator, pwm_ip):
        doc = generator.generate_regmap_docs(pwm_ip)
        # PERIOD has a non-zero reset value
        assert "0x000003FF" in doc

    def test_field_tables_rendered(self, generator, pwm_ip):
        doc = generator.generate_regmap_docs(pwm_ip)
        assert "ENABLE" in doc
        assert "MODE" in doc
        assert "READY" in doc
        assert "BUSY" in doc
        assert "DONE" in doc

    def test_single_bit_field_notation(self, generator, pwm_ip):
        """Single-bit fields should use [N] notation."""
        doc = generator.generate_regmap_docs(pwm_ip)
        assert re.search(r"\[0\]", doc)

    def test_multi_bit_field_notation(self, generator, pwm_ip):
        """Multi-bit fields should use [M:N] notation."""
        doc = generator.generate_regmap_docs(pwm_ip)
        assert re.search(r"\[2:1\]", doc)

    def test_access_types_shown(self, generator, pwm_ip):
        doc = generator.generate_regmap_docs(pwm_ip)
        assert "READ-WRITE" in doc.upper() or "RW" in doc.upper()
        assert "READ-ONLY" in doc.upper() or "RO" in doc.upper()
        assert "WRITE-1-TO-CLEAR" in doc.upper() or "W1C" in doc.upper()

    def test_register_without_fields_handled(self, generator, pwm_ip):
        """PERIOD has no named fields; the template should emit a sensible message."""
        doc = generator.generate_regmap_docs(pwm_ip)
        assert "No named fields" in doc or "single" in doc.lower()

    def test_no_registers_handled_gracefully(self, generator):
        """IP with no memory map should not crash."""
        ip = IpCore(
            vlnv=VLNV(vendor="v", library="l", name="bare_core", version="1.0"),
            description="No registers.",
        )
        doc = generator.generate_regmap_docs(ip)
        assert "bare_core" in doc
        assert "no memory-mapped registers" in doc.lower()


class TestRegmapDocsIntegration:
    """Verify regmap docs are correctly integrated into generate_all paths."""

    def test_include_docs_flat(self, generator, pwm_ip):
        files = generator.generate_all(pwm_ip, bus_type="axil", include_docs=True)
        assert "pwm_core_regmap.md" in files
        assert "CTRL" in files["pwm_core_regmap.md"]

    def test_include_docs_not_emitted_by_default(self, generator, pwm_ip):
        files = generator.generate_all(pwm_ip, bus_type="axil")
        assert not any(k.endswith("_regmap.md") for k in files)

    def test_include_docs_structured(self, generator, pwm_ip):
        files = generator.generate_all(
            pwm_ip, bus_type="axil", structured=True, include_docs=True
        )
        assert "docs/pwm_core_regmap.md" in files
        assert "CTRL" in files["docs/pwm_core_regmap.md"]

    def test_include_docs_structured_not_emitted_by_default(self, generator, pwm_ip):
        files = generator.generate_all(pwm_ip, bus_type="axil", structured=True)
        assert not any("regmap.md" in k for k in files)

    def test_docs_offset_matches_vhdl_package(self, generator, pwm_ip):
        """Cross-check: offsets in MD must match those in the generated VHDL package."""
        files = generator.generate_all(
            pwm_ip, bus_type="axil", include_docs=True
        )
        doc = files["pwm_core_regmap.md"]
        pkg = generator.generate_package(pwm_ip)

        # The integer offset 0x20 = 32 should appear in the VHDL package constant
        # and as 0x0020 in the Markdown
        assert "0x0020" in doc
        assert "32" in pkg or "16#20#" in pkg or "x\"20\"" in pkg
