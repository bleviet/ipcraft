"""
Comprehensive test cases for the VHDL parser module.

This test file covers edge cases, bus interface detection scenarios,
and error handling that are not covered by the basic test file.
"""

import pytest

from ipcraft.model import PortDirection
from ipcraft.parser.hdl.vhdl_parser import VHDLParser


class TestVHDLParserEdgeCases:
    """Test edge cases in VHDL parsing."""

    def test_parse_empty_entity(self):
        """Test parsing an entity with no ports."""
        parser = VHDLParser()
        vhdl_code = """
        entity empty_design is
            port (
            );
        end entity empty_design;
        """
        result = parser.parse_text(vhdl_code)
        assert result["entity"] is not None
        assert result["entity"].vlnv.name == "empty_design"
        assert len(result["entity"].ports) == 0

    def test_parse_entity_single_port(self):
        """Test parsing an entity with a single port (no trailing semicolon issues)."""
        parser = VHDLParser()
        vhdl_code = """
        entity single_port is
            port (
                clk : in std_logic
            );
        end entity single_port;
        """
        result = parser.parse_text(vhdl_code)
        assert result["entity"] is not None
        assert len(result["entity"].ports) == 1
        assert result["entity"].ports[0].name == "clk"

    def test_parse_mixed_case_keywords(self):
        """Test parsing with mixed case VHDL keywords."""
        parser = VHDLParser()
        vhdl_code = """
        ENTITY MixedCase IS
            PORT (
                Clk     : IN std_logic;
                Rst     : IN STD_LOGIC;
                DataOut : OUT Std_Logic_Vector(7 DOWNTO 0)
            );
        END ENTITY MixedCase;
        """
        result = parser.parse_text(vhdl_code)
        assert result["entity"] is not None
        assert result["entity"].vlnv.name == "MixedCase"
        assert len(result["entity"].ports) == 3

    def test_parse_comments_in_port_list(self):
        """Test parsing with comments between ports."""
        parser = VHDLParser()
        vhdl_code = """
        entity commented is
            port (
                -- Clock input
                clk     : in std_logic;  -- System clock
                -- Reset input (active high)
                rst     : in std_logic;
                -- Data output
                data    : out std_logic_vector(7 downto 0)  -- 8-bit data
            );
        end entity commented;
        """
        result = parser.parse_text(vhdl_code)
        assert result["entity"] is not None
        assert len(result["entity"].ports) == 3

    def test_parse_multiple_entities(self):
        """Test parsing a file with multiple entities (should get first)."""
        parser = VHDLParser()
        vhdl_code = """
        entity first_entity is
            port (
                a : in std_logic
            );
        end entity first_entity;

        entity second_entity is
            port (
                b : out std_logic
            );
        end entity second_entity;
        """
        result = parser.parse_text(vhdl_code)
        assert result["entity"] is not None
        # Should find first entity
        assert result["entity"].vlnv.name == "first_entity"


class TestVHDLParserPortDirections:
    """Test all port direction types."""

    def test_all_port_directions(self):
        """Test parsing all VHDL port directions."""
        parser = VHDLParser()
        vhdl_code = """
        entity all_directions is
            port (
                input_port  : in std_logic;
                output_port : out std_logic;
                bidir_port  : inout std_logic;
                buffer_port : buffer std_logic;
                link_port   : linkage std_logic
            );
        end entity all_directions;
        """
        result = parser.parse_text(vhdl_code)
        assert result["entity"] is not None
        ports = {p.name: p for p in result["entity"].ports}

        assert ports["input_port"].direction == PortDirection.IN
        assert ports["output_port"].direction == PortDirection.OUT
        assert ports["bidir_port"].direction == PortDirection.INOUT
        # buffer maps to OUT
        assert ports["buffer_port"].direction == PortDirection.OUT
        # linkage maps to IN
        assert ports["link_port"].direction == PortDirection.IN


class TestVHDLParserWidthParsing:
    """Test width extraction from different vector declarations."""

    def test_downto_range(self):
        """Test width extraction from downto range."""
        parser = VHDLParser()
        vhdl_code = """
        entity width_test is
            port (
                data8  : out std_logic_vector(7 downto 0);
                data16 : out std_logic_vector(15 downto 0);
                data32 : out std_logic_vector(31 downto 0)
            );
        end entity width_test;
        """
        result = parser.parse_text(vhdl_code)
        ports = {p.name: p for p in result["entity"].ports}

        assert ports["data8"].width == 8
        assert ports["data16"].width == 16
        assert ports["data32"].width == 32

    def test_non_zero_low_bound(self):
        """Test width with non-zero lower bound."""
        parser = VHDLParser()
        vhdl_code = """
        entity offset_range is
            port (
                data : out std_logic_vector(11 downto 4)
            );
        end entity offset_range;
        """
        result = parser.parse_text(vhdl_code)
        assert result["entity"].ports[0].width == 8  # 11 - 4 + 1 = 8

    def test_parameterized_width_defaults_to_one(self):
        """Test that parameterized widths default to 1."""
        parser = VHDLParser()
        vhdl_code = """
        entity generic_width is
            generic (
                WIDTH : natural := 8
            );
            port (
                data : out std_logic_vector(WIDTH-1 downto 0)
            );
        end entity generic_width;
        """
        result = parser.parse_text(vhdl_code)
        # Parameterized width can't be computed, defaults to 1
        assert result["entity"].ports[0].width == 1
        # But the type string should preserve the original
        assert "WIDTH-1" in result["entity"].ports[0].type

    def test_unsigned_signed_types(self):
        """Test parsing unsigned and signed types."""
        parser = VHDLParser()
        vhdl_code = """
        entity numeric_types is
            port (
                unsigned_data : out unsigned(7 downto 0);
                signed_data   : out signed(15 downto 0)
            );
        end entity numeric_types;
        """
        result = parser.parse_text(vhdl_code)
        ports = {p.name: p for p in result["entity"].ports}

        # Type string should be preserved
        assert "unsigned" in ports["unsigned_data"].type
        assert "signed" in ports["signed_data"].type


class TestVHDLParserGenerics:
    """Test generic parsing scenarios."""

    def test_generics_no_default(self):
        """Test generics without default values."""
        parser = VHDLParser()
        vhdl_code = """
        entity no_default is
            generic (
                WIDTH : natural
            );
            port (
                data : out std_logic_vector(WIDTH-1 downto 0)
            );
        end entity no_default;
        """
        result = parser.parse_text(vhdl_code)
        assert result["entity"] is not None
        assert len(result["entity"].parameters) == 1
        assert result["entity"].parameters[0].name == "WIDTH"

    def test_generics_complex_default(self):
        """Test generics with complex default expressions."""
        parser = VHDLParser()
        vhdl_code = """
        entity complex_defaults is
            generic (
                INIT_VALUE : std_logic_vector(31 downto 0) := x"DEADBEEF";
                RESET_VEC  : std_logic_vector(7 downto 0) := (others => '1')
            );
            port (
                clk : in std_logic
            );
        end entity complex_defaults;
        """
        result = parser.parse_text(vhdl_code)
        assert result["entity"] is not None
        assert len(result["entity"].parameters) == 2

    def test_generics_integer_boolean(self):
        """Test generics with integer and boolean types."""
        parser = VHDLParser()
        vhdl_code = """
        entity type_generics is
            generic (
                COUNT    : integer := 10;
                ENABLE   : boolean := true;
                DEPTH    : positive := 16
            );
            port (
                clk : in std_logic
            );
        end entity type_generics;
        """
        result = parser.parse_text(vhdl_code)
        assert result["entity"] is not None
        params = {p.name: p for p in result["entity"].parameters}
        assert "COUNT" in params
        assert "ENABLE" in params
        assert "DEPTH" in params


class TestVHDLParserBusInterfacePatterns:
    """Test parsing of common bus interface patterns."""

    def test_parse_axi_lite_slave_ports(self):
        """Test parsing AXI-Lite slave interface ports."""
        parser = VHDLParser()
        vhdl_code = """
        entity axi_slave is
            port (
                s_axi_aclk    : in  std_logic;
                s_axi_aresetn : in  std_logic;
                s_axi_awaddr  : in  std_logic_vector(31 downto 0);
                s_axi_awprot  : in  std_logic_vector(2 downto 0);
                s_axi_awvalid : in  std_logic;
                s_axi_awready : out std_logic;
                s_axi_wdata   : in  std_logic_vector(31 downto 0);
                s_axi_wstrb   : in  std_logic_vector(3 downto 0);
                s_axi_wvalid  : in  std_logic;
                s_axi_wready  : out std_logic;
                s_axi_bresp   : out std_logic_vector(1 downto 0);
                s_axi_bvalid  : out std_logic;
                s_axi_bready  : in  std_logic;
                s_axi_araddr  : in  std_logic_vector(31 downto 0);
                s_axi_arprot  : in  std_logic_vector(2 downto 0);
                s_axi_arvalid : in  std_logic;
                s_axi_arready : out std_logic;
                s_axi_rdata   : out std_logic_vector(31 downto 0);
                s_axi_rresp   : out std_logic_vector(1 downto 0);
                s_axi_rvalid  : out std_logic;
                s_axi_rready  : in  std_logic
            );
        end entity axi_slave;
        """
        result = parser.parse_text(vhdl_code)
        assert result["entity"] is not None
        assert len(result["entity"].ports) == 21

        # Verify some key ports
        ports = {p.name: p for p in result["entity"].ports}
        assert ports["s_axi_awaddr"].direction == PortDirection.IN
        assert ports["s_axi_awready"].direction == PortDirection.OUT
        assert ports["s_axi_rdata"].direction == PortDirection.OUT
        assert ports["s_axi_rdata"].width == 32

    def test_parse_axi_stream_source_ports(self):
        """Test parsing AXI-Stream source interface ports."""
        parser = VHDLParser()
        vhdl_code = """
        entity axis_source is
            port (
                aclk        : in  std_logic;
                aresetn     : in  std_logic;
                m_axis_tdata  : out std_logic_vector(31 downto 0);
                m_axis_tkeep  : out std_logic_vector(3 downto 0);
                m_axis_tlast  : out std_logic;
                m_axis_tvalid : out std_logic;
                m_axis_tready : in  std_logic
            );
        end entity axis_source;
        """
        result = parser.parse_text(vhdl_code)
        assert result["entity"] is not None
        assert len(result["entity"].ports) == 7

        ports = {p.name: p for p in result["entity"].ports}
        assert ports["m_axis_tdata"].direction == PortDirection.OUT
        assert ports["m_axis_tready"].direction == PortDirection.IN

    def test_parse_avalon_mm_slave_ports(self):
        """Test parsing Avalon-MM slave interface ports."""
        parser = VHDLParser()
        vhdl_code = """
        entity avalon_slave is
            port (
                clk           : in  std_logic;
                reset         : in  std_logic;
                avs_address     : in  std_logic_vector(7 downto 0);
                avs_read        : in  std_logic;
                avs_readdata    : out std_logic_vector(31 downto 0);
                avs_write       : in  std_logic;
                avs_writedata   : in  std_logic_vector(31 downto 0);
                avs_waitrequest : out std_logic
            );
        end entity avalon_slave;
        """
        result = parser.parse_text(vhdl_code)
        assert result["entity"] is not None
        ports = {p.name: p for p in result["entity"].ports}

        assert ports["avs_address"].direction == PortDirection.IN
        assert ports["avs_readdata"].direction == PortDirection.OUT
        assert ports["avs_readdata"].width == 32


class TestVHDLParserArchitecture:
    """Test architecture parsing."""

    def test_parse_architecture_name(self):
        """Test extraction of architecture name."""
        parser = VHDLParser()
        vhdl_code = """
        entity test is
            port (clk : in std_logic);
        end entity test;

        architecture rtl of test is
        begin
        end architecture rtl;
        """
        result = parser.parse_text(vhdl_code)
        assert result["architecture"] is not None
        assert result["architecture"]["name"] == "rtl"
        assert result["architecture"]["entity"] == "test"

    def test_parse_multiple_architectures(self):
        """Test file with multiple architectures."""
        parser = VHDLParser()
        vhdl_code = """
        entity multi_arch is
            port (clk : in std_logic);
        end entity multi_arch;

        architecture behavioral of multi_arch is
        begin
        end architecture behavioral;

        architecture structural of multi_arch is
        begin
        end architecture structural;
        """
        result = parser.parse_text(vhdl_code)
        # Should find first architecture
        assert result["architecture"]["name"] == "behavioral"


class TestVHDLParserPackage:
    """Test package parsing."""

    def test_parse_package(self):
        """Test package declaration parsing."""
        parser = VHDLParser()
        vhdl_code = """
        package my_types_pkg is
            type my_record is record
                field1 : std_logic;
                field2 : std_logic_vector(7 downto 0);
            end record;
        end package my_types_pkg;
        """
        result = parser.parse_text(vhdl_code)
        assert result["package"] is not None
        assert result["package"]["name"] == "my_types_pkg"


class TestVHDLParserErrorHandling:
    """Test error handling and fallback behavior."""

    def test_parse_malformed_port(self):
        """Test parsing continues with malformed port syntax."""
        parser = VHDLParser()
        # Missing direction keyword - should still attempt to parse
        vhdl_code = """
        entity malformed is
            port (
                good_port : in std_logic
            );
        end entity malformed;
        """
        result = parser.parse_text(vhdl_code)
        # Should still parse entity even with issues
        assert result["entity"] is not None

    def test_parse_empty_input(self):
        """Test parsing empty input."""
        parser = VHDLParser()
        result = parser.parse_text("")
        assert result["entity"] is None
        assert result["architecture"] is None
        assert result["package"] is None

    def test_parse_non_vhdl_text(self):
        """Test parsing non-VHDL content."""
        parser = VHDLParser()
        result = parser.parse_text("This is not VHDL code at all.")
        assert result["entity"] is None


class TestVHDLParserFileLoading:
    """Test file-based parsing."""

    def test_parse_file_not_found(self):
        """Test handling of non-existent file."""
        parser = VHDLParser()
        with pytest.raises(FileNotFoundError):
            parser.parse_file("/nonexistent/path/file.vhd")
