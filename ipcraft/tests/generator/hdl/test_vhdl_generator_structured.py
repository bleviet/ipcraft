"""Test structured folder generation for VHDL generator."""

from pathlib import Path

import pytest

from ipcraft.generator.hdl.ipcore_project_generator import IpCoreProjectGenerator
from ipcraft.model.core import VLNV, IpCore
from ipcraft.model.memory_map import AddressBlock, BitFieldDef, MemoryMap, RegisterDef


class TestIpCoreProjectGeneratorStructured:
    """Test structured folder generation (VSCode extension compatible)."""

    @pytest.fixture
    def simple_ip_core(self):
        """Create a simple IP core for testing."""
        return IpCore(
            api_version="test/v1.0",
            vlnv=VLNV(vendor="test", library="lib", name="struct_test", version="1.0"),
            description="Structured output test",
            ports=[],
            parameters=[],
            memory_maps=[],
        )

    def test_structured_basic_generation(self, simple_ip_core):
        """Test basic structured generation without extras."""
        generator = IpCoreProjectGenerator()
        files = generator.generate_all(simple_ip_core, bus_type="axil", structured=True)

        # Check we have RTL files in rtl/ subdirectory
        assert "rtl/struct_test_pkg.vhd" in files
        assert "rtl/struct_test.vhd" in files
        assert "rtl/struct_test_core.vhd" in files
        assert "rtl/struct_test_axil.vhd" in files

        # Check no vendor or testbench files by default
        assert not any(f.startswith("intel/") for f in files)
        assert not any(f.startswith("xilinx/") for f in files)
        assert not any(f.startswith("tb/") for f in files)

    def test_structured_with_testbench(self, simple_ip_core):
        """Test structured generation with testbench files."""
        generator = IpCoreProjectGenerator()
        files = generator.generate_all(
            simple_ip_core, bus_type="axil", structured=True, include_testbench=True
        )

        # Check testbench files in tb/ subdirectory
        assert "tb/struct_test_test.py" in files
        assert "tb/Makefile" in files

    def test_structured_with_vendor_intel(self, simple_ip_core):
        """Test structured generation with Intel vendor files."""
        generator = IpCoreProjectGenerator()
        files = generator.generate_all(
            simple_ip_core, bus_type="axil", structured=True, vendor="intel"
        )

        # Check Intel vendor files in intel/ subdirectory
        assert "intel/struct_test_hw.tcl" in files

        # Xilinx should not be present
        assert not any(f.startswith("xilinx/") for f in files)

    def test_structured_with_vendor_xilinx(self, simple_ip_core):
        """Test structured generation with Xilinx vendor files."""
        generator = IpCoreProjectGenerator()
        files = generator.generate_all(
            simple_ip_core, bus_type="axil", structured=True, vendor="xilinx"
        )

        # Check Xilinx vendor files in xilinx/ subdirectory
        assert "xilinx/component.xml" in files

        # Intel should not be present
        assert not any(f.startswith("intel/") for f in files)

    def test_structured_with_vendor_both(self, simple_ip_core):
        """Test structured generation with both vendor files."""
        generator = IpCoreProjectGenerator()
        files = generator.generate_all(
            simple_ip_core, bus_type="axil", structured=True, vendor="both"
        )

        # Check both vendor files
        assert "intel/struct_test_hw.tcl" in files
        assert "xilinx/component.xml" in files

    def test_structured_with_regfile(self, simple_ip_core):
        """Test structured generation with register file."""
        generator = IpCoreProjectGenerator()
        files = generator.generate_all(
            simple_ip_core, bus_type="axil", structured=True, include_regs=True
        )

        # Check register file in rtl/ subdirectory
        assert "rtl/struct_test_regs.vhd" in files

    def test_structured_complete(self, simple_ip_core):
        """Test structured generation with all options."""
        generator = IpCoreProjectGenerator()
        files = generator.generate_all(
            simple_ip_core,
            bus_type="axil",
            structured=True,
            include_regs=True,
            vendor="both",
            include_testbench=True,
        )

        # Count files in each category
        rtl_files = [f for f in files if f.startswith("rtl/")]
        tb_files = [f for f in files if f.startswith("tb/")]
        intel_files = [f for f in files if f.startswith("intel/")]
        xilinx_files = [f for f in files if f.startswith("xilinx/")]

        # Verify counts
        assert len(rtl_files) == 5  # pkg, top, core, bus, regfile
        assert len(tb_files) == 2  # test.py, Makefile
        assert len(intel_files) == 1  # hw.tcl
        assert len(xilinx_files) >= 1  # component.xml + xgui

        # Total should be at least 9 files
        assert len(files) >= 9

    def test_non_structured_backward_compatibility(self, simple_ip_core):
        """Test that non-structured mode still works (backward compatibility)."""
        generator = IpCoreProjectGenerator()
        files = generator.generate_all(
            simple_ip_core, bus_type="axil", structured=False  # Default behavior
        )

        # Files should NOT have subdirectory prefixes
        assert "struct_test_pkg.vhd" in files
        assert "struct_test.vhd" in files
        assert "struct_test_core.vhd" in files
        assert "struct_test_axil.vhd" in files

        # No subdirectory prefixes
        assert not any("/" in f for f in files)

    def test_file_content_same_structured_vs_flat(self, simple_ip_core):
        """Test that file content is identical between structured and flat modes."""
        generator = IpCoreProjectGenerator()

        # Generate both modes
        structured = generator.generate_all(simple_ip_core, bus_type="axil", structured=True)
        flat = generator.generate_all(simple_ip_core, bus_type="axil", structured=False)

        # Compare package file content
        struct_pkg = structured["rtl/struct_test_pkg.vhd"]
        flat_pkg = flat["struct_test_pkg.vhd"]
        assert struct_pkg == flat_pkg

        # Compare top file content
        struct_top = structured["rtl/struct_test.vhd"]
        flat_top = flat["struct_test.vhd"]
        assert struct_top == flat_top
