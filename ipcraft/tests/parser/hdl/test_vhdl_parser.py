"""
Test cases for the VHDL parser module.
"""

import difflib
import os

import pytest
from pyparsing import Word, alphanums, alphas

from ipcraft.generator.hdl.ipcore_project_generator import IpCoreProjectGenerator
from ipcraft.model import IpCore, Port, PortDirection
from ipcraft.parser.hdl.vhdl_parser import VHDLParser


class TestVHDLParser:
    """Test suite for VHDL parser functionality."""

    def test_parse_entity_simple(self):
        """Test parsing a simple VHDL entity."""
        parser = VHDLParser()
        vhdl_code = """
        library IEEE;
        use IEEE.std_logic_1164.all;

        entity counter is
            port (
                clk     : in std_logic;
                rst     : in std_logic;
                enable  : in std_logic;
                count   : out std_logic_vector(7 downto 0)
            );
        end entity counter;
        """

        result = parser.parse_text(vhdl_code)

        # Verify entity was parsed
        assert result["entity"] is not None
        assert isinstance(result["entity"], IpCore)
        # IpCore uses vlnv.name
        assert result["entity"].vlnv.name == "counter"

        # Verify ports - accessible directly on ip_core now
        assert len(result["entity"].ports) == 4

        # Verify port details
        port_names = [p.name for p in result["entity"].ports]
        assert "clk" in port_names
        assert "rst" in port_names
        assert "enable" in port_names
        assert "count" in port_names

        # Find count port and check its type
        count_port = next(p for p in result["entity"].ports if p.name == "count")
        # New model stores full type string or reconstructed one
        assert "std_logic_vector" in count_port.type
        assert count_port.direction == PortDirection.OUT

    def test_parse_entity_and_architecture(self):
        """Test parsing both entity and architecture."""
        parser = VHDLParser()
        vhdl_code = """
        library IEEE;
        use IEEE.std_logic_1164.all;
        use IEEE.numeric_std.all;

        entity counter is
            port (
                clk     : in std_logic;
                rst     : in std_logic;
                enable  : in std_logic;
                count   : out std_logic_vector(7 downto 0)
            );
        end entity counter;

        architecture behavioral of counter is
            signal count_internal : unsigned(7 downto 0);
        begin
            process(clk, rst)
            begin
                if rst = '1' then
                    count_internal <= (others => '0');
                elsif rising_edge(clk) then
                    if enable = '1' then
                        count_internal <= count_internal + 1;
                    end if;
                end if;
            end process;

            count <= std_logic_vector(count_internal);
        end architecture behavioral;
        """

        result = parser.parse_text(vhdl_code)

        # Verify entity
        assert result["entity"] is not None
        assert result["entity"].vlnv.name == "counter"

        # Verify architecture
        assert result["architecture"] is not None
        assert result["architecture"]["name"] == "behavioral"
        assert result["architecture"]["entity"] == "counter"

    def test_roundtrip_entity(self):
        """Test roundtrip: parse a VHDL entity and regenerate it."""
        parser = VHDLParser()
        generator = IpCoreProjectGenerator()

        # Original VHDL code (simplified for comparison)
        original_vhdl = """
entity counter is
    port (
        clk     : in std_logic;
        rst     : in std_logic;
        enable  : in std_logic;
        count   : out std_logic_vector(7 downto 0)
    );
end entity counter;
        """.strip()

        # Parse the VHDL code
        result = parser.parse_text(original_vhdl)
        ip_core = result["entity"]

        # Regenerate VHDL code from the parsed entity
        # Use generate_core as generate_entity is deprecated/removed
        generated_vhdl = generator.generate_core(ip_core).strip()

        # Normalize whitespace for comparison
        norm_original = self._normalize_whitespace(original_vhdl)
        norm_regenerated = self._normalize_whitespace(generated_vhdl)

        # Compare the essential parts
        assert "entity counter_core is" in norm_regenerated
        assert "port (" in norm_regenerated
        assert "clk : in std_logic" in norm_regenerated
        assert "rst : in std_logic" in norm_regenerated
        assert "enable : in std_logic" in norm_regenerated
        assert "count : out std_logic_vector(7 downto 0)" in norm_regenerated
        assert "end entity counter_core" in norm_regenerated

    def test_parse_entity_with_generics(self):
        """Test parsing a VHDL entity with generics."""
        parser = VHDLParser()
        vhdl_code = """
        library IEEE;
        use IEEE.std_logic_1164.all;

        entity configurable_counter is
            generic (
                WIDTH       : natural := 8;
                RESET_VALUE : std_logic_vector(7 downto 0) := (others => '0')
            );
            port (
                clk     : in std_logic;
                rst     : in std_logic;
                enable  : in std_logic;
                count   : out std_logic_vector(WIDTH-1 downto 0)
            );
        end entity configurable_counter;
        """

        result = parser.parse_text(vhdl_code)

        # Verify entity was parsed
        assert result["entity"] is not None
        assert isinstance(result["entity"], IpCore)
        assert result["entity"].vlnv.name == "configurable_counter"

        # Verify generics/parameters
        # Parameters are stored as a list in IpCore
        assert len(result["entity"].parameters) == 2

        param_names = [p.name for p in result["entity"].parameters]
        assert "WIDTH" in param_names
        assert "RESET_VALUE" in param_names

        # Check generic types by finding params
        width_param = next(p for p in result["entity"].parameters if p.name == "WIDTH")
        assert "natural" in width_param.description.lower()

        reset_value_param = next(p for p in result["entity"].parameters if p.name == "RESET_VALUE")
        assert "std_logic_vector" in reset_value_param.description.lower()

        # Verify ports - direct access
        assert len(result["entity"].ports) == 4

        # Verify port details
        port_names = [p.name for p in result["entity"].ports]
        assert "clk" in port_names
        assert "rst" in port_names
        assert "enable" in port_names
        assert "count" in port_names

    def test_parse_neorv32_cfs_with_generics(self):
        """Test parsing the actual neorv32_cfs.vhd file that has generics."""
        parser = VHDLParser()

        # Use the actual neorv32_cfs.vhd file from the test resources
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "resources",
            "vhdl",
            "neorv32_core",
            "neorv32_cfs.vhd",
        )

        # Check if file exists, skip if not (might not be present in fresh checkout environment)
        if not os.path.exists(file_path):
            pytest.skip(f"Test file not found: {file_path}")

        result = parser.parse_file(file_path)

        # Verify entity was parsed
        assert result["entity"] is not None
        assert isinstance(result["entity"], IpCore)
        assert result["entity"].vlnv.name == "neorv32_cfs"

        # Verify generics/parameters - should have 3 generics
        assert len(result["entity"].parameters) == 3
        param_names = [p.name for p in result["entity"].parameters]
        assert "CFS_CONFIG" in param_names
        assert "CFS_IN_SIZE" in param_names
        assert "CFS_OUT_SIZE" in param_names

        # Check generic types
        cfs_config = next(p for p in result["entity"].parameters if p.name == "CFS_CONFIG")
        assert "std_ulogic_vector" in cfs_config.description.lower()

        cfs_in_size = next(p for p in result["entity"].parameters if p.name == "CFS_IN_SIZE")
        assert "natural" in cfs_in_size.description.lower()

        cfs_out_size = next(p for p in result["entity"].parameters if p.name == "CFS_OUT_SIZE")
        assert "natural" in cfs_out_size.description.lower()

        # Verify all 9 ports are still parsed correctly
        assert len(result["entity"].ports) == 9

    def _normalize_whitespace(self, text):
        """Normalize whitespace for comparison."""
        return " ".join(text.replace("\n", " ").split())
