"""
Tests for IpXactParser.
"""

from pathlib import Path

import pytest

from ipcraft.model import IpCore, PortDirection
from ipcraft.model.bus import BusInterfaceMode
from ipcraft.parser.vendor.ipxact_parser import IpXactParser

FIXTURES = Path(__file__).parent / "fixtures"


class TestIpXactParser:
    """Unit tests for IpXactParser."""

    def test_parse_returns_ip_core(self):
        parser = IpXactParser()
        ip = parser.parse_file(FIXTURES / "simple_uart_component.xml")
        assert isinstance(ip, IpCore)

    def test_vlnv(self):
        parser = IpXactParser()
        ip = parser.parse_file(FIXTURES / "simple_uart_component.xml")
        assert ip.vlnv.vendor == "user"
        assert ip.vlnv.library == "ip"
        assert ip.vlnv.name == "simple_uart"
        assert ip.vlnv.version == "1.0"

    def test_description(self):
        parser = IpXactParser()
        ip = parser.parse_file(FIXTURES / "simple_uart_component.xml")
        assert "uart" in ip.description.lower()

    def test_bus_interface(self):
        parser = IpXactParser()
        ip = parser.parse_file(FIXTURES / "simple_uart_component.xml")
        assert len(ip.bus_interfaces) == 1
        bus = ip.bus_interfaces[0]
        assert bus.type == "AXI4_LITE"
        assert bus.mode == BusInterfaceMode.SLAVE
        assert bus.name == "S_AXI"

    def test_ports(self):
        parser = IpXactParser()
        ip = parser.parse_file(FIXTURES / "simple_uart_component.xml")
        port_names = {p.name for p in ip.ports}
        assert "txd" in port_names
        assert "rxd" in port_names

    def test_port_directions(self):
        parser = IpXactParser()
        ip = parser.parse_file(FIXTURES / "simple_uart_component.xml")
        port_map = {p.name: p for p in ip.ports}
        assert port_map["txd"].direction == PortDirection.OUT
        assert port_map["rxd"].direction == PortDirection.IN

    def test_clocks_and_resets(self):
        """The fixture has no explicit clock/reset busInterfaces;
        aclk and aresetn remain as standalone ports."""
        parser = IpXactParser()
        ip = parser.parse_file(FIXTURES / "simple_uart_component.xml")
        # No dedicated clock/reset bus-interface sections → lists are empty
        assert ip.clocks == []
        assert ip.resets == []
        # But the physical ports aclk / aresetn are present as standalone ports
        port_names = {p.name for p in ip.ports}
        assert "aclk" in port_names
        assert "aresetn" in port_names

    def test_parameters(self):
        parser = IpXactParser()
        ip = parser.parse_file(FIXTURES / "simple_uart_component.xml")
        assert len(ip.parameters) == 2
        param_names = {p.name for p in ip.parameters}
        assert "C_S_AXI_DATA_WIDTH" in param_names
        assert "C_S_AXI_ADDR_WIDTH" in param_names

    def test_discovered_registers(self):
        """IP-XACT memory map should be captured in _discovered_registers."""
        parser = IpXactParser()
        ip = parser.parse_file(FIXTURES / "simple_uart_component.xml")
        regs = getattr(ip, "_discovered_registers", None)
        assert regs is not None, "_discovered_registers should be set"
        # Structure: list of memory maps → addressBlocks → registers
        assert len(regs) >= 1
        mm = regs[0]
        assert "addressBlocks" in mm
        all_regs = [r for ab in mm["addressBlocks"] for r in ab.get("registers", [])]
        reg_names = {r["name"] for r in all_regs}
        assert "CTRL" in reg_names
        assert "STATUS" in reg_names

    def test_discovered_registers_fields(self):
        """Each discovered register should have addressOffset and fields."""
        parser = IpXactParser()
        ip = parser.parse_file(FIXTURES / "simple_uart_component.xml")
        mm = ip._discovered_registers[0]
        all_regs = [r for ab in mm["addressBlocks"] for r in ab.get("registers", [])]
        ctrl = next(r for r in all_regs if r["name"] == "CTRL")
        assert "addressOffset" in ctrl
        assert "fields" in ctrl
        assert len(ctrl["fields"]) >= 1

    def test_parse_string(self):
        """parse_string should accept raw XML."""
        xml = (FIXTURES / "simple_uart_component.xml").read_text()
        parser = IpXactParser()
        ip = parser.parse_string(xml)
        assert ip.vlnv.name == "simple_uart"
