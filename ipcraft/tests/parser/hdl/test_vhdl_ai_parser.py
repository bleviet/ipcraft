"""
Unit tests for VHDL AI Parser.

Tests the pure LLM-based VHDL parser with various complexity levels
and validates entity parsing, port extraction, generic handling, and
bus interface detection.
"""

from pathlib import Path

import pytest

from ipcraft.model.core import IpCore
from ipcraft.model.port import PortDirection
from ipcraft.parser.hdl.vhdl_ai_parser import ParserConfig, VHDLAiParser


@pytest.fixture
def test_vhdl_dir():
    """Get the test VHDL directory path."""
    path = Path(__file__).parent.parent.parent / "examples" / "test_vhdl"
    if not path.exists():
        pytest.skip(f"Test VHDL directory not found: {path}")
    return path


@pytest.fixture
def parser_config():
    """Default parser configuration for testing."""
    return ParserConfig(
        llm_provider="ollama", llm_model="gemma3:12b", strict_mode=False
    )


@pytest.fixture
def parser(parser_config):
    """Create parser instance."""
    return VHDLAiParser(config=parser_config)


# ============================================================================
# Basic Entity Parsing Tests
# ============================================================================


class TestBasicEntityParsing:
    """Test basic entity structure parsing."""

    def test_simple_counter_parsing(self, parser, test_vhdl_dir):
        """Test parsing of simple counter entity."""
        vhdl_file = test_vhdl_dir / "simple_counter.vhd"
        assert vhdl_file.exists(), f"Test file not found: {vhdl_file}"

        ip_core = parser.parse_file(vhdl_file)

        assert ip_core is not None
        assert isinstance(ip_core, IpCore)
        assert ip_core.vlnv.name == "simple_counter"
        assert len(ip_core.ports) == 4
        assert len(ip_core.parameters) == 1

    def test_entity_name_extraction(self, parser, test_vhdl_dir):
        """Verify entity name is correctly extracted."""
        test_files = [
            ("simple_counter.vhd", "simple_counter"),
            ("uart_transmitter.vhd", "uart_transmitter"),
            ("fifo_buffer.vhd", "fifo_buffer"),
        ]

        for filename, expected_name in test_files:
            vhdl_file = test_vhdl_dir / filename
            if vhdl_file.exists():
                ip_core = parser.parse_file(vhdl_file)
                assert (
                    ip_core.vlnv.name == expected_name
                ), f"Entity name mismatch for {filename}"

    def test_description_generation(self, parser, test_vhdl_dir):
        """Verify LLM generates meaningful descriptions."""
        vhdl_file = test_vhdl_dir / "simple_counter.vhd"
        ip_core = parser.parse_file(vhdl_file)

        assert ip_core.description is not None
        assert len(ip_core.description) > 0
        assert ip_core.description != "Failed to parse"


# ============================================================================
# Port Parsing Tests
# ============================================================================


class TestPortParsing:
    """Test port extraction and direction parsing."""

    def test_simple_counter_ports(self, parser, test_vhdl_dir):
        """Test simple counter port parsing."""
        ip_core = parser.parse_file(test_vhdl_dir / "simple_counter.vhd")

        # Expected ports: clk, rst_n, enable, count
        port_names = [p.name for p in ip_core.ports]
        assert "clk" in port_names
        assert "rst_n" in port_names
        assert "enable" in port_names
        assert "count" in port_names

    def test_port_directions(self, parser, test_vhdl_dir):
        """Test port direction detection."""
        ip_core = parser.parse_file(test_vhdl_dir / "simple_counter.vhd")

        port_dict = {p.name: p for p in ip_core.ports}

        assert port_dict["clk"].direction == PortDirection.IN
        assert port_dict["rst_n"].direction == PortDirection.IN
        assert port_dict["enable"].direction == PortDirection.IN
        assert port_dict["count"].direction == PortDirection.OUT

    def test_port_widths(self, parser, test_vhdl_dir):
        """Test port width calculation."""
        ip_core = parser.parse_file(test_vhdl_dir / "simple_counter.vhd")

        port_dict = {p.name: p for p in ip_core.ports}

        # std_logic ports should be width 1
        assert port_dict["clk"].width == 1
        assert port_dict["rst_n"].width == 1
        assert port_dict["enable"].width == 1

        # std_logic_vector(WIDTH-1 downto 0) should be WIDTH bits
        # Default WIDTH = 8
        assert port_dict["count"].width == 8

    def test_uart_transmitter_ports(self, parser, test_vhdl_dir):
        """Test UART transmitter with multiple port types."""
        ip_core = parser.parse_file(test_vhdl_dir / "uart_transmitter.vhd")

        assert len(ip_core.ports) == 6

        port_dict = {p.name: p for p in ip_core.ports}

        # System signals
        assert "clk" in port_dict
        assert "rst" in port_dict

        # Data interface
        assert "tx_data" in port_dict
        assert "tx_valid" in port_dict
        assert "tx_ready" in port_dict

        # UART output
        assert "uart_tx" in port_dict


# ============================================================================
# Generic/Parameter Parsing Tests
# ============================================================================


class TestGenericParsing:
    """Test generic/parameter extraction."""

    def test_simple_counter_generic(self, parser, test_vhdl_dir):
        """Test simple generic extraction."""
        ip_core = parser.parse_file(test_vhdl_dir / "simple_counter.vhd")

        assert len(ip_core.parameters) == 1
        param = ip_core.parameters[0]
        assert param.name == "WIDTH"
        assert param.data_type == "integer"
        assert param.value == "8"

    def test_uart_transmitter_generics(self, parser, test_vhdl_dir):
        """Test multiple generics with different types."""
        ip_core = parser.parse_file(test_vhdl_dir / "uart_transmitter.vhd")

        assert len(ip_core.parameters) == 5

        param_dict = {p.name: p for p in ip_core.parameters}

        # Integer generics
        assert "CLK_FREQ" in param_dict
        assert param_dict["CLK_FREQ"].value == "50000000"

        assert "BAUD_RATE" in param_dict
        assert param_dict["BAUD_RATE"].value == "115200"

        assert "DATA_BITS" in param_dict
        assert param_dict["DATA_BITS"].value == "8"

        assert "STOP_BITS" in param_dict
        assert param_dict["STOP_BITS"].value == "1"

        # Boolean generic
        assert "PARITY_ENABLE" in param_dict
        assert param_dict["PARITY_ENABLE"].data_type == "boolean"

    def test_fifo_buffer_generics(self, parser, test_vhdl_dir):
        """Test generics with power-of-2 expressions."""
        ip_core = parser.parse_file(test_vhdl_dir / "fifo_buffer.vhd")

        assert len(ip_core.parameters) == 2

        param_dict = {p.name: p for p in ip_core.parameters}

        assert "DATA_WIDTH" in param_dict
        assert param_dict["DATA_WIDTH"].value == "32"

        assert "DEPTH_LOG2" in param_dict
        assert param_dict["DEPTH_LOG2"].value == "4"


# ============================================================================
# Complex Expression Tests
# ============================================================================


class TestComplexExpressions:
    """Test parsing of complex arithmetic expressions in port widths."""

    def test_simple_subtraction(self, parser, test_vhdl_dir):
        """Test WIDTH-1 expression."""
        ip_core = parser.parse_file(test_vhdl_dir / "simple_counter.vhd")

        port_dict = {p.name: p for p in ip_core.ports}
        # count: std_logic_vector(WIDTH-1 downto 0)
        # With WIDTH=8, should be 8 bits
        assert port_dict["count"].width == 8

    def test_power_of_two(self, parser, test_vhdl_dir):
        """Test 2**N expression."""
        ip_core = parser.parse_file(test_vhdl_dir / "fifo_buffer.vhd")

        # DEPTH_LOG2 = 4, so DEPTH = 2**4 = 16
        # data_count: std_logic_vector(DEPTH_LOG2 downto 0) = 5 bits
        port_dict = {p.name: p for p in ip_core.ports}
        assert "data_count" in port_dict
        assert port_dict["data_count"].width == 5

    def test_division_expression(self, parser, test_vhdl_dir):
        """Test (WIDTH/8)-1 expression."""
        ip_core = parser.parse_file(test_vhdl_dir / "fifo_buffer.vhd")

        # With DATA_WIDTH=32, wr_data should be 32 bits
        port_dict = {p.name: p for p in ip_core.ports}
        assert port_dict["wr_data"].width == 32

    def test_axi_division_expression(self, parser, test_vhdl_dir):
        """Test complex AXI division: (C_DATA_WIDTH/8)-1."""
        vhdl_file = test_vhdl_dir / "axi_example_peripheral.vhd"
        if not vhdl_file.exists():
            pytest.skip("AXI example file not found")

        ip_core = parser.parse_file(vhdl_file)

        port_dict = {p.name: p for p in ip_core.ports}

        # s_axi_wstrb: (C_S_AXI_DATA_WIDTH/8)-1 downto 0
        # With C_S_AXI_DATA_WIDTH=32, should be 4 bits
        if "s_axi_wstrb" in port_dict:
            assert port_dict["s_axi_wstrb"].width == 4


# ============================================================================
# Bus Interface Detection Tests
# ============================================================================


class TestBusInterfaceDetection:
    """Test AI-powered bus interface detection."""

    def test_axi4_lite_detection(self, parser, test_vhdl_dir):
        """Test AXI4-Lite bus interface detection."""
        vhdl_file = test_vhdl_dir / "axi_example_peripheral.vhd"
        if not vhdl_file.exists():
            pytest.skip("AXI example file not found")

        ip_core = parser.parse_file(vhdl_file)

        assert len(ip_core.bus_interfaces) >= 1

        # Find AXI interface
        axi_bus = next(
            (b for b in ip_core.bus_interfaces if "AXI" in b.type.upper()), None
        )
        assert axi_bus is not None
        assert "s_axi" in axi_bus.name.lower()
        assert axi_bus.mode == "slave"

    def test_axi_stream_detection(self, parser, test_vhdl_dir):
        """Test AXI-Stream interface detection."""
        ip_core = parser.parse_file(test_vhdl_dir / "axi_stream_filter.vhd")

        assert len(ip_core.bus_interfaces) >= 1

        # Should detect both slave and master interfaces
        bus_names = [b.name for b in ip_core.bus_interfaces]
        bus_types = [b.type for b in ip_core.bus_interfaces]

        # Check for AXI-Stream interfaces
        assert any(
            "axis" in name.lower() or "stream" in t.lower()
            for name, t in zip(bus_names, bus_types)
        )

    def test_spi_detection(self, parser, test_vhdl_dir):
        """Test SPI bus interface detection."""
        ip_core = parser.parse_file(test_vhdl_dir / "spi_master.vhd")

        # Should detect SPI interface from spi_sclk, spi_mosi, spi_miso, spi_cs_n
        bus_types = [b.type for b in ip_core.bus_interfaces]

        assert any("spi" in t.lower() for t in bus_types)

    def test_wishbone_detection(self, parser, test_vhdl_dir):
        """Test Wishbone bus interface detection."""
        ip_core = parser.parse_file(test_vhdl_dir / "wishbone_slave.vhd")

        # Should detect Wishbone from wb_* signals
        bus_types = [b.type for b in ip_core.bus_interfaces]

        assert any("wishbone" in t.lower() or "wb" in t.lower() for t in bus_types)

    def test_no_bus_interface(self, parser, test_vhdl_dir):
        """Test that simple cores without buses don't detect false positives."""
        ip_core = parser.parse_file(test_vhdl_dir / "simple_counter.vhd")

        # Simple counter should have no bus interfaces
        assert len(ip_core.bus_interfaces) == 0


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Test parser error handling and graceful degradation."""

    def test_nonexistent_file(self, parser):
        """Test handling of non-existent file."""
        with pytest.raises(FileNotFoundError):
            parser.parse_file(Path("/nonexistent/file.vhd"))

    def test_strict_mode_on_failure(self):
        """Test strict mode raises errors."""
        config = ParserConfig(llm_provider="invalid_provider", strict_mode=True)

        # Should raise RuntimeError in strict mode
        with pytest.raises(RuntimeError):
            VHDLAiParser(config=config)

    def test_graceful_degradation_on_failure(self):
        """Test graceful degradation when LLM unavailable."""
        config = ParserConfig(llm_provider="invalid_provider", strict_mode=False)

        # Should create parser but log error
        parser = VHDLAiParser(config=config)
        assert parser is not None


# ============================================================================
# Model Validation Tests
# ============================================================================


class TestModelValidation:
    """Test Pydantic model validation."""

    def test_valid_ip_core_model(self, parser, test_vhdl_dir):
        """Test that parsed IP core passes Pydantic validation."""
        ip_core = parser.parse_file(test_vhdl_dir / "simple_counter.vhd")

        # Should be valid Pydantic model
        assert isinstance(ip_core, IpCore)

        # Should be serializable to JSON
        json_str = ip_core.model_dump_json()
        assert json_str is not None
        assert len(json_str) > 0

    def test_vlnv_structure(self, parser, test_vhdl_dir):
        """Test VLNV structure is correctly populated."""
        ip_core = parser.parse_file(test_vhdl_dir / "simple_counter.vhd")

        vlnv = ip_core.vlnv
        assert vlnv.vendor == "unknown.vendor"
        assert vlnv.library == "work"
        assert vlnv.name == "simple_counter"
        assert vlnv.version == "1.0.0"

    def test_port_model_validation(self, parser, test_vhdl_dir):
        """Test Port models are correctly validated."""
        ip_core = parser.parse_file(test_vhdl_dir / "simple_counter.vhd")

        for port in ip_core.ports:
            # Required fields
            assert port.name is not None
            assert port.direction in [
                PortDirection.IN,
                PortDirection.OUT,
                PortDirection.INOUT,
            ]
            assert port.width > 0
            assert port.physical_port is not None


# ============================================================================
# Performance Tests
# ============================================================================


@pytest.mark.slow
class TestPerformance:
    """Performance and timing tests."""

    def test_parsing_time_simple(self, parser, test_vhdl_dir, benchmark):
        """Benchmark parsing time for simple entity."""
        vhdl_file = test_vhdl_dir / "simple_counter.vhd"

        result = benchmark(parser.parse_file, vhdl_file)
        assert result is not None

    def test_parsing_time_complex(self, parser, test_vhdl_dir, benchmark):
        """Benchmark parsing time for complex entity."""
        vhdl_file = test_vhdl_dir / "axi_example_peripheral.vhd"
        if not vhdl_file.exists():
            pytest.skip("AXI example file not found")

        result = benchmark(parser.parse_file, vhdl_file)
        assert result is not None


# ============================================================================
# Integration Tests
# ============================================================================


@pytest.mark.integration
class TestIntegration:
    """Integration tests with different LLM providers."""

    def test_parse_with_ollama(self, test_vhdl_dir):
        """Test parsing with Ollama provider."""
        config = ParserConfig(llm_provider="ollama", llm_model="gemma3:12b")
        parser = VHDLAiParser(config=config)

        if not parser.llm_parser.is_available():
            pytest.skip("Ollama not available")

        ip_core = parser.parse_file(test_vhdl_dir / "simple_counter.vhd")
        assert ip_core.vlnv.name == "simple_counter"

    @pytest.mark.skipif(
        "OPENAI_API_KEY" not in __import__("os").environ,
        reason="OpenAI API key not configured",
    )
    def test_parse_with_openai(self, test_vhdl_dir):
        """Test parsing with OpenAI provider."""
        config = ParserConfig(llm_provider="openai", llm_model="gpt-4o-mini")
        parser = VHDLAiParser(config=config)

        ip_core = parser.parse_file(test_vhdl_dir / "simple_counter.vhd")
        assert ip_core.vlnv.name == "simple_counter"

    @pytest.mark.skipif(
        "GEMINI_API_KEY" not in __import__("os").environ,
        reason="Gemini API key not configured",
    )
    def test_parse_with_gemini(self, test_vhdl_dir):
        """Test parsing with Gemini provider."""
        config = ParserConfig(llm_provider="gemini", llm_model="gemini-2.0-flash-exp")
        parser = VHDLAiParser(config=config)

        ip_core = parser.parse_file(test_vhdl_dir / "simple_counter.vhd")
        assert ip_core.vlnv.name == "simple_counter"


# ============================================================================
# Run Tests
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
