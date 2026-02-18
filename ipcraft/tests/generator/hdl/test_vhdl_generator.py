"""Tests for VHDL generator."""

from pathlib import Path

import pytest

from ipcraft.generator.hdl.ipcore_project_generator import IpCoreProjectGenerator
from ipcraft.model.base import VLNV
from ipcraft.model.core import IpCore
from ipcraft.model.memory_map import (
    AccessType,
    AddressBlock,
    BitFieldDef,
    MemoryMap,
    RegisterDef,
)
from ipcraft.model.port import Port, PortDirection
from ipcraft.parser.yaml.ip_yaml_parser import YamlIpCoreParser


class TestIpCoreProjectGeneratorBasic:
    """Basic VHDL generator functionality tests."""

    def test_generator_initialization(self):
        """Test that IpCoreProjectGenerator initializes correctly."""
        generator = IpCoreProjectGenerator()
        assert generator is not None
        assert generator.env is not None

    def test_generate_package(self):
        """Test package generation with simple IP core."""
        ip_core = IpCore(
            api_version="test/v1.0",
            vlnv=VLNV(vendor="test", library="lib", name="simple_ip", version="1.0"),
            description="Simple test IP",
            ports=[],
            parameters=[],
            memory_maps=[],
        )

        generator = IpCoreProjectGenerator()
        package = generator.generate_package(ip_core)

        assert package is not None
        assert "package simple_ip_pkg is" in package
        assert "end package simple_ip_pkg;" in package

    def test_generate_top(self):
        """Test top-level entity generation."""
        ip_core = IpCore(
            api_version="test/v1.0",
            vlnv=VLNV(vendor="test", library="lib", name="test_top", version="1.0"),
            description="Test top entity",
            ports=[],
            parameters=[],
            memory_maps=[],
        )

        generator = IpCoreProjectGenerator()
        top = generator.generate_top(ip_core, bus_type="axil")

        assert top is not None
        assert "entity test_top is" in top
        assert "end entity test_top;" in top

    def test_generate_core(self):
        """Test core module generation."""
        ip_core = IpCore(
            api_version="test/v1.0",
            vlnv=VLNV(vendor="test", library="lib", name="test_core", version="1.0"),
            description="Test core module",
            ports=[],
            parameters=[],
            memory_maps=[],
        )

        generator = IpCoreProjectGenerator()
        core = generator.generate_core(ip_core)

        assert core is not None
        assert "entity test_core_core is" in core
        assert "end entity test_core_core;" in core

    def test_generate_bus_wrapper_axil(self):
        """Test AXI-Lite bus wrapper generation."""
        ip_core = IpCore(
            api_version="test/v1.0",
            vlnv=VLNV(vendor="test", library="lib", name="test_bus", version="1.0"),
            description="Test bus wrapper",
            ports=[],
            parameters=[],
            memory_maps=[],
        )

        generator = IpCoreProjectGenerator()
        bus_wrapper = generator.generate_bus_wrapper(ip_core, bus_type="axil")

        assert bus_wrapper is not None
        assert "entity test_bus_axil is" in bus_wrapper

    def test_generate_bus_wrapper_avmm(self):
        """Test Avalon-MM bus wrapper generation."""
        ip_core = IpCore(
            api_version="test/v1.0",
            vlnv=VLNV(vendor="test", library="lib", name="test_avmm", version="1.0"),
            description="Test Avalon wrapper",
            ports=[],
            parameters=[],
            memory_maps=[],
        )

        generator = IpCoreProjectGenerator()
        bus_wrapper = generator.generate_bus_wrapper(ip_core, bus_type="avmm")

        assert bus_wrapper is not None
        assert "entity test_avmm_avmm is" in bus_wrapper

    def test_generate_all(self):
        """Test generation of all VHDL files."""
        ip_core = IpCore(
            api_version="test/v1.0",
            vlnv=VLNV(vendor="test", library="lib", name="test_all", version="1.0"),
            description="Test all files",
            ports=[],
            parameters=[],
            memory_maps=[],
        )

        generator = IpCoreProjectGenerator()
        files = generator.generate_all(ip_core, bus_type="axil")

        assert len(files) == 4
        assert "test_all_pkg.vhd" in files
        assert "test_all.vhd" in files
        assert "test_all_core.vhd" in files
        assert "test_all_axil.vhd" in files

    def test_generate_with_register_file(self):
        """Test generation including standalone register file."""
        ip_core = IpCore(
            api_version="test/v1.0",
            vlnv=VLNV(vendor="test", library="lib", name="test_regfile", version="1.0"),
            description="Test with regfile",
            ports=[],
            parameters=[],
            memory_maps=[],
        )

        generator = IpCoreProjectGenerator()
        files = generator.generate_all(ip_core, bus_type="axil", include_regs=True)

        assert len(files) == 5
        assert "test_regfile_regs.vhd" in files


class TestIpCoreProjectGeneratorWithRegisters:
    """Test VHDL generation with memory maps and registers."""

    def test_generate_with_simple_register(self):
        """Test generation with a simple register."""
        memory_map = MemoryMap(
            name="regs",
            address_blocks=[
                AddressBlock(
                    name="ctrl_block",
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
                                )
                            ],
                        )
                    ],
                )
            ],
        )

        ip_core = IpCore(
            api_version="test/v1.0",
            vlnv=VLNV(vendor="test", library="lib", name="reg_test", version="1.0"),
            description="Register test",
            ports=[],
            parameters=[],
            memory_maps=[memory_map],
        )

        generator = IpCoreProjectGenerator()
        package = generator.generate_package(ip_core)

        assert "CTRL" in package
        assert "enable" in package

    def test_generate_with_user_ports(self):
        """Test generation with user-defined ports."""
        ip_core = IpCore(
            api_version="test/v1.0",
            vlnv=VLNV(vendor="test", library="lib", name="port_test", version="1.0"),
            description="Port test",
            ports=[
                Port(name="clk", direction=PortDirection.IN, width=1),
                Port(name="rst_n", direction=PortDirection.IN, width=1),
                Port(name="data_out", direction=PortDirection.OUT, width=8),
            ],
            parameters=[],
            memory_maps=[],
        )

        generator = IpCoreProjectGenerator()
        top = generator.generate_top(ip_core, bus_type="axil")

        assert "clk" in top
        assert "rst_n" in top
        assert "data_out" in top


class TestIpCoreProjectGeneratorVendorFiles:
    """Test vendor integration file generation."""

    def test_generate_intel_hw_tcl(self):
        """Test Intel Platform Designer _hw.tcl generation."""
        ip_core = IpCore(
            api_version="test/v1.0",
            vlnv=VLNV(vendor="test", library="lib", name="intel_test", version="1.0"),
            description="Intel test",
            ports=[],
            parameters=[],
            memory_maps=[],
        )

        generator = IpCoreProjectGenerator()
        tcl = generator.generate_intel_hw_tcl(ip_core)

        assert tcl is not None
        assert "package require qsys" in tcl

    def test_generate_xilinx_component_xml(self):
        """Test Xilinx component.xml generation."""
        ip_core = IpCore(
            api_version="test/v1.0",
            vlnv=VLNV(vendor="test", library="lib", name="xilinx_test", version="1.0"),
            description="Xilinx test",
            ports=[],
            parameters=[],
            memory_maps=[],
        )

        generator = IpCoreProjectGenerator()
        xml = generator.generate_xilinx_component_xml(ip_core)

        assert xml is not None
        assert "<?xml version=" in xml
        assert "spirit:component" in xml


class TestIpCoreProjectGeneratorTestbench:
    """Test testbench file generation."""

    def test_generate_cocotb_test(self):
        """Test cocotb test file generation."""
        ip_core = IpCore(
            api_version="test/v1.0",
            vlnv=VLNV(vendor="test", library="lib", name="tb_test", version="1.0"),
            description="Testbench test",
            ports=[],
            parameters=[],
            memory_maps=[],
        )

        generator = IpCoreProjectGenerator()
        test = generator.generate_cocotb_test(ip_core)

        assert test is not None
        assert "import cocotb" in test

    def test_generate_cocotb_makefile(self):
        """Test cocotb Makefile generation."""
        ip_core = IpCore(
            api_version="test/v1.0",
            vlnv=VLNV(vendor="test", library="lib", name="make_test", version="1.0"),
            description="Makefile test",
            ports=[],
            parameters=[],
            memory_maps=[],
        )

        generator = IpCoreProjectGenerator()
        makefile = generator.generate_cocotb_makefile(ip_core)

        assert makefile is not None
        assert "SIM ?= ghdl" in makefile
        assert "TOPLEVEL = make_test" in makefile

    def test_generate_testbench_files(self):
        """Test generation of all testbench files."""
        ip_core = IpCore(
            api_version="test/v1.0",
            vlnv=VLNV(vendor="test", library="lib", name="tb_all", version="1.0"),
            description="All testbench files",
            ports=[],
            parameters=[],
            memory_maps=[],
        )

        generator = IpCoreProjectGenerator()
        files = generator.generate_testbench(ip_core)

        assert len(files) == 2
        assert "tb_all_test.py" in files
        assert "Makefile" in files
