"""
Tests for HwTclParser.
"""

from pathlib import Path

import pytest

from ipcraft.model import IpCore, PortDirection
from ipcraft.model.bus import BusInterfaceMode
from ipcraft.parser.vendor.hw_tcl_parser import HwTclParser

FIXTURES = Path(__file__).parent / "fixtures"


class TestHwTclParser:
    """Unit tests for HwTclParser."""

    def test_parse_simple_uart(self):
        """Parse the simple_uart_hw.tcl fixture."""
        parser = HwTclParser()
        ip = parser.parse_file(FIXTURES / "simple_uart_hw.tcl")

        assert isinstance(ip, IpCore)
        assert ip.vlnv.name == "simple_uart"
        assert ip.vlnv.version == "1.0"

    def test_simple_uart_has_avalon_bus(self):
        parser = HwTclParser()
        ip = parser.parse_file(FIXTURES / "simple_uart_hw.tcl")

        assert len(ip.bus_interfaces) == 1
        bus = ip.bus_interfaces[0]
        assert bus.type == "AVALON_MM"
        assert bus.mode == BusInterfaceMode.SLAVE
        assert bus.name == "s0"

    def test_simple_uart_has_clock_and_reset(self):
        parser = HwTclParser()
        ip = parser.parse_file(FIXTURES / "simple_uart_hw.tcl")

        assert len(ip.clocks) == 1
        assert ip.clocks[0].name == "clk"

        assert len(ip.resets) == 1
        assert ip.resets[0].name == "rst"

    def test_simple_uart_standalone_ports(self):
        parser = HwTclParser()
        ip = parser.parse_file(FIXTURES / "simple_uart_hw.tcl")

        port_names = {p.name for p in ip.ports}
        assert "txd" in port_names
        assert "rxd" in port_names

        txd = next(p for p in ip.ports if p.name == "txd")
        rxd = next(p for p in ip.ports if p.name == "rxd")
        assert txd.direction == PortDirection.OUT
        assert rxd.direction == PortDirection.IN

    def test_simple_uart_parameter(self):
        parser = HwTclParser()
        ip = parser.parse_file(FIXTURES / "simple_uart_hw.tcl")

        assert len(ip.parameters) == 1
        param = ip.parameters[0]
        assert param.name == "BAUD_RATE"
        assert param.value == 115200

    def test_axilite_slave(self):
        parser = HwTclParser()
        ip = parser.parse_file(FIXTURES / "axilite_slave_hw.tcl")

        assert ip.vlnv.name == "axilite_slave"
        assert ip.vlnv.version == "2.0"
        assert len(ip.bus_interfaces) == 1
        bus = ip.bus_interfaces[0]
        assert bus.type == "AXI4_LITE"
        assert bus.mode == BusInterfaceMode.SLAVE

    def test_axilite_slave_has_two_parameters(self):
        parser = HwTclParser()
        ip = parser.parse_file(FIXTURES / "axilite_slave_hw.tcl")
        param_names = {p.name for p in ip.parameters}
        assert "C_S_AXI_DATA_WIDTH" in param_names
        assert "C_S_AXI_ADDR_WIDTH" in param_names

    def test_parse_string(self):
        """parse_string should work the same as parse_file."""
        tcl = """
set_module_info -name "my_core"
set_module_info -version "3.0"
add_interface clk clock end
add_interface_port clk clk clk Input 1
add_interface_port "" led "" Output 8
"""
        parser = HwTclParser()
        ip = parser.parse_string(tcl)
        assert ip.vlnv.name == "my_core"
        assert ip.vlnv.version == "3.0"
        assert len(ip.clocks) == 1
        port_names = {p.name for p in ip.ports}
        assert "led" in port_names

    def test_unknown_module_name_defaults(self):
        """A minimal file with no set_module_info should not crash."""
        tcl = "add_interface_port \"\" out_sig \"\" Output 1\n"
        parser = HwTclParser()
        ip = parser.parse_string(tcl)
        assert isinstance(ip, IpCore)
        assert ip.vlnv.name == "unknown"

    def test_bus_clock_association(self):
        """Bus interface should record its associated clock/reset."""
        parser = HwTclParser()
        ip = parser.parse_file(FIXTURES / "simple_uart_hw.tcl")
        bus = ip.bus_interfaces[0]
        assert bus.associated_clock == "clk"
        assert bus.associated_reset == "rst"
