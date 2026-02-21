"""Template rendering coverage tests for VHDL generator."""

from pathlib import Path

import pytest

from ipcraft.generator.hdl.ipcore_project_generator import IpCoreProjectGenerator
from ipcraft.model.base import VLNV, Parameter, ParameterType
from ipcraft.model.core import IpCore
from ipcraft.model.memory_map import (
    AccessType,
    AddressBlock,
    BitFieldDef,
    MemoryMap,
    RegisterDef,
)
from ipcraft.model.port import Port, PortDirection


class TestTemplateRendering:
    """Test that all templates render without errors."""

    @pytest.fixture
    def generator(self):
        """Create VHDL generator instance."""
        return IpCoreProjectGenerator()

    @pytest.fixture
    def templates_dir(self):
        """Get templates directory."""
        gen = IpCoreProjectGenerator()
        return Path(gen.env.loader.searchpath[0])

    @pytest.fixture
    def simple_ip_core(self):
        """Create a simple IP core for testing."""
        return IpCore(
            api_version="test/v1.0",
            vlnv=VLNV(
                vendor="test", library="lib", name="template_test", version="1.0"
            ),
            description="Template test IP",
            ports=[],
            parameters=[],
            memory_maps=[],
        )

    @pytest.fixture
    def ip_core_with_registers(self):
        """Create an IP core with registers."""
        memory_map = MemoryMap(
            name="regs",
            address_blocks=[
                AddressBlock(
                    name="control",
                    base_address=0x0000,
                    range=0x1000,
                    width=32,
                    registers=[
                        RegisterDef(
                            name="CTRL",
                            address_offset=0x00,
                            size=32,
                            access=AccessType.READ_WRITE,
                            fields=[
                                BitFieldDef(
                                    name="enable",
                                    bit_offset=0,
                                    bit_width=1,
                                    access=AccessType.READ_WRITE,
                                ),
                                BitFieldDef(
                                    name="mode",
                                    bit_offset=1,
                                    bit_width=2,
                                    access=AccessType.READ_WRITE,
                                ),
                            ],
                        ),
                        RegisterDef(
                            name="STATUS",
                            address_offset=0x04,
                            size=32,
                            access=AccessType.READ_ONLY,
                            fields=[
                                BitFieldDef(
                                    name="ready",
                                    bit_offset=0,
                                    bit_width=1,
                                    access=AccessType.READ_ONLY,
                                )
                            ],
                        ),
                    ],
                )
            ],
        )

        return IpCore(
            api_version="test/v1.0",
            vlnv=VLNV(vendor="test", library="lib", name="reg_test", version="1.0"),
            description="Register test IP",
            ports=[],
            parameters=[],
            memory_maps=[memory_map],
        )

    @pytest.fixture
    def ip_core_with_ports(self):
        """Create an IP core with ports."""
        return IpCore(
            api_version="test/v1.0",
            vlnv=VLNV(vendor="test", library="lib", name="port_test", version="1.0"),
            description="Port test IP",
            ports=[
                Port(name="data_in", direction=PortDirection.IN, width=32),
                Port(name="data_out", direction=PortDirection.OUT, width=32),
                Port(name="valid", direction=PortDirection.OUT, width=1),
            ],
            parameters=[
                Parameter(name="DATA_WIDTH", data_type=ParameterType.INTEGER, value=32),
                Parameter(name="FIFO_DEPTH", data_type=ParameterType.INTEGER, value=16),
            ],
            memory_maps=[],
        )

    def test_all_templates_exist(self, templates_dir):
        """Verify all expected templates exist."""
        expected_templates = [
            "package.vhdl.j2",
            "top.vhdl.j2",
            "core.vhdl.j2",
            "bus_axil.vhdl.j2",
            "bus_avmm.vhdl.j2",
            "register_file.vhdl.j2",
            "entity.vhdl.j2",
            "architecture.vhdl.j2",
            "intel_hw_tcl.j2",
            "xilinx_component_xml.j2",
            "cocotb_test.py.j2",
            "cocotb_makefile.j2",
            "memmap.yml.j2",
        ]

        for template_name in expected_templates:
            template_path = templates_dir / template_name
            assert template_path.exists(), f"Template not found: {template_name}"

    def test_package_template(self, generator, simple_ip_core):
        """Test package.vhdl.j2 renders without errors."""
        result = generator.generate_package(simple_ip_core)
        assert result is not None
        assert len(result) > 0
        assert "package" in result

    def test_package_template_with_registers(self, generator, ip_core_with_registers):
        """Test package template with registers."""
        result = generator.generate_package(ip_core_with_registers)
        assert result is not None
        assert "CTRL" in result
        assert "STATUS" in result
        assert "enable" in result
        assert "ready" in result

    def test_top_template_axil(self, generator, simple_ip_core):
        """Test top.vhdl.j2 renders with AXI-Lite."""
        result = generator.generate_top(simple_ip_core, bus_type="axil")
        assert result is not None
        assert "entity" in result
        assert "template_test" in result

    def test_top_template_with_ports(self, generator, ip_core_with_ports):
        """Test top template with user ports."""
        result = generator.generate_top(ip_core_with_ports, bus_type="axil")
        assert result is not None
        assert "data_in" in result
        assert "data_out" in result
        assert "valid" in result

    def test_core_template(self, generator, simple_ip_core):
        """Test core.vhdl.j2 renders without errors."""
        result = generator.generate_core(simple_ip_core)
        assert result is not None
        assert "entity" in result
        assert "_core" in result

    def test_bus_axil_template(self, generator, simple_ip_core):
        """Test bus_axil.vhdl.j2 renders without errors."""
        result = generator.generate_bus_wrapper(simple_ip_core, bus_type="axil")
        assert result is not None
        assert "entity" in result
        assert "_axil" in result

    def test_bus_avmm_template(self, generator, simple_ip_core):
        """Test bus_avmm.vhdl.j2 renders without errors."""
        result = generator.generate_bus_wrapper(simple_ip_core, bus_type="avmm")
        assert result is not None
        assert "entity" in result
        assert "_avmm" in result

    def test_register_file_template(self, generator, ip_core_with_registers):
        """Test register_file.vhdl.j2 renders without errors."""
        result = generator.generate_register_file(ip_core_with_registers)
        assert result is not None
        assert "entity" in result
        assert "_regs" in result

    def test_intel_hw_tcl_template(self, generator, simple_ip_core):
        """Test intel_hw_tcl.j2 renders without errors."""
        result = generator.generate_intel_hw_tcl(simple_ip_core)
        assert result is not None
        assert "package require qsys" in result
        assert "set_module_property" in result

    def test_intel_hw_tcl_with_registers(self, generator, ip_core_with_registers):
        """Test Intel TCL template with registers."""
        result = generator.generate_intel_hw_tcl(ip_core_with_registers)
        assert result is not None
        assert "add_interface" in result

    def test_xilinx_component_xml_template(self, generator, simple_ip_core):
        """Test xilinx_component_xml.j2 renders without errors."""
        result = generator.generate_xilinx_component_xml(simple_ip_core)
        assert result is not None
        assert "<?xml version=" in result
        assert "spirit:component" in result
        # VLNV is rendered as separate XML tags, not colon-separated
        assert "<spirit:vendor>test</spirit:vendor>" in result
        assert "<spirit:name>template_test</spirit:name>" in result

    def test_xilinx_xml_with_ports(self, generator, ip_core_with_ports):
        """Test Xilinx XML template with ports."""
        result = generator.generate_xilinx_component_xml(ip_core_with_ports)
        assert result is not None
        assert "spirit:port" in result

    def test_cocotb_test_template(self, generator, simple_ip_core):
        """Test cocotb_test.py.j2 renders without errors."""
        result = generator.generate_cocotb_test(simple_ip_core)
        assert result is not None
        assert "import cocotb" in result
        assert "async def" in result

    def test_cocotb_test_with_registers(self, generator, ip_core_with_registers):
        """Test cocotb test template with registers."""
        result = generator.generate_cocotb_test(ip_core_with_registers)
        assert result is not None
        # Template uses dynamic driver loading, so check for driver functions
        assert "load_driver" in result
        assert "reg_test.mm.yml" in result

    def test_cocotb_makefile_template(self, generator, simple_ip_core):
        """Test cocotb_makefile.j2 renders without errors."""
        result = generator.generate_cocotb_makefile(simple_ip_core)
        assert result is not None
        assert "SIM ?= ghdl" in result
        assert "TOPLEVEL" in result
        assert "VHDL_SOURCES" in result

    def test_memmap_yml_template(self, generator, ip_core_with_registers):
        """Test memmap.yml.j2 renders without errors."""
        result = generator.generate_memmap_yaml(ip_core_with_registers)
        assert result is not None
        assert "CTRL" in result
        assert "STATUS" in result
        # YAML format checks
        assert "address:" in result or "offset:" in result

    def test_all_templates_render_simple(self, generator, simple_ip_core):
        """Test all templates render with simple IP core."""
        # Generate all files
        files = generator.generate_all(
            simple_ip_core, bus_type="axil", include_regs=False
        )

        # Should have at least package, top, core, bus wrapper
        assert len(files) >= 4

        # All files should have content
        for filename, content in files.items():
            assert content is not None, f"{filename} is None"
            assert len(content) > 0, f"{filename} is empty"

    def test_all_templates_render_with_registers(
        self, generator, ip_core_with_registers
    ):
        """Test all templates render with registers."""
        # Generate all files
        files = generator.generate_all(
            ip_core_with_registers, bus_type="axil", include_regs=True
        )

        # Should have package, top, core, bus wrapper, regfile
        assert len(files) >= 5

        # All files should have content
        for filename, content in files.items():
            assert content is not None, f"{filename} is None"
            assert len(content) > 0, f"{filename} is empty"

    def test_both_bus_types_render(self, generator, simple_ip_core):
        """Test both AXI-Lite and Avalon-MM bus wrappers render."""
        axil_files = generator.generate_all(simple_ip_core, bus_type="axil")
        avmm_files = generator.generate_all(simple_ip_core, bus_type="avmm")

        # Both should succeed
        assert len(axil_files) >= 4
        assert len(avmm_files) >= 4

        # Should have different bus wrapper files
        assert any("_axil.vhd" in f for f in axil_files.keys())
        assert any("_avmm.vhd" in f for f in avmm_files.keys())

    def test_vendor_files_all_render(self, generator, simple_ip_core):
        """Test all vendor integration files render."""
        # Intel
        intel_files = generator.generate_vendor_files(simple_ip_core, vendor="intel")
        assert len(intel_files) == 1
        assert any("_hw.tcl" in f for f in intel_files.keys())

        # Xilinx
        xilinx_files = generator.generate_vendor_files(simple_ip_core, vendor="xilinx")
        assert len(xilinx_files) >= 1
        assert "component.xml" in xilinx_files

        # Both
        both_files = generator.generate_vendor_files(simple_ip_core, vendor="both")
        assert len(both_files) >= 2

    def test_testbench_files_all_render(self, generator, ip_core_with_registers):
        """Test all testbench files render."""
        tb_files = generator.generate_testbench(ip_core_with_registers)

        # Should have test, makefile
        assert len(tb_files) == 2

        name = ip_core_with_registers.vlnv.name.lower()
        assert f"{name}_test.py" in tb_files
        assert "Makefile" in tb_files

        # All should have content
        for content in tb_files.values():
            assert len(content) > 0

    def test_templates_no_syntax_errors(self, generator, ip_core_with_registers):
        """Test templates don't produce obvious syntax errors in VHDL."""
        files = generator.generate_all(ip_core_with_registers, bus_type="axil")

        for filename, content in files.items():
            if filename.endswith(".vhd"):
                # Basic VHDL syntax checks
                # Package files have 'package', entities have 'entity'
                assert (
                    "entity" in content.lower() or "package" in content.lower()
                ), f"{filename} missing entity or package"
                assert "end" in content.lower(), f"{filename} missing end statements"

                # No template artifacts
                assert "{{" not in content, f"{filename} has unrendered Jinja2 syntax"
                assert "{%" not in content, f"{filename} has unrendered Jinja2 control"


class TestTemplateEdgeCases:
    """Test templates with edge cases and boundary conditions."""

    @pytest.fixture
    def generator(self):
        """Create VHDL generator instance."""
        return IpCoreProjectGenerator()

    def test_empty_memory_map(self, generator):
        """Test templates with empty memory maps."""
        ip_core = IpCore(
            api_version="test/v1.0",
            vlnv=VLNV(vendor="test", library="lib", name="empty", version="1.0"),
            description="Empty test",
            ports=[],
            parameters=[],
            memory_maps=[],
        )

        # Should not crash
        files = generator.generate_all(ip_core, bus_type="axil")
        assert len(files) >= 4

    def test_single_bit_fields(self, generator):
        """Test with single-bit register fields."""
        memory_map = MemoryMap(
            name="regs",
            address_blocks=[
                AddressBlock(
                    name="control",
                    base_address=0x00,
                    range=0x100,
                    width=32,
                    registers=[
                        RegisterDef(
                            name="FLAGS",
                            address_offset=0x00,
                            size=32,
                            access=AccessType.READ_WRITE,
                            fields=[
                                BitFieldDef(
                                    name=f"flag{i}",
                                    bit_offset=i,
                                    bit_width=1,
                                    access=AccessType.READ_WRITE,
                                )
                                for i in range(8)
                            ],
                        )
                    ],
                )
            ],
        )

        ip_core = IpCore(
            api_version="test/v1.0",
            vlnv=VLNV(vendor="test", library="lib", name="flags", version="1.0"),
            description="Flags test",
            memory_maps=[memory_map],
        )

        result = generator.generate_package(ip_core)
        assert result is not None
        assert "flag0" in result
        assert "flag7" in result

    def test_wide_registers(self, generator):
        """Test with wide register fields."""
        memory_map = MemoryMap(
            name="regs",
            address_blocks=[
                AddressBlock(
                    name="data",
                    base_address=0x00,
                    range=0x100,
                    width=32,
                    registers=[
                        RegisterDef(
                            name="DATA",
                            address_offset=0x00,
                            size=32,
                            access=AccessType.READ_WRITE,
                            fields=[
                                BitFieldDef(
                                    name="data",
                                    bit_offset=0,
                                    bit_width=32,
                                    access=AccessType.READ_WRITE,
                                )
                            ],
                        )
                    ],
                )
            ],
        )

        ip_core = IpCore(
            api_version="test/v1.0",
            vlnv=VLNV(vendor="test", library="lib", name="wide", version="1.0"),
            description="Wide register test",
            memory_maps=[memory_map],
        )

        result = generator.generate_package(ip_core)
        assert result is not None
        assert "DATA" in result

    def test_max_ports(self, generator):
        """Test with many ports."""
        ports = [
            Port(
                name=f"port{i}",
                direction=PortDirection.IN if i % 2 == 0 else PortDirection.OUT,
                width=8,
            )
            for i in range(20)
        ]

        ip_core = IpCore(
            api_version="test/v1.0",
            vlnv=VLNV(vendor="test", library="lib", name="many_ports", version="1.0"),
            description="Many ports test",
            ports=ports,
        )

        result = generator.generate_top(ip_core, bus_type="axil")
        assert result is not None
        assert "port0" in result
        assert "port19" in result
