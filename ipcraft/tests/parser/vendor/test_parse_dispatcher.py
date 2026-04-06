"""
Tests for ParseDispatcher.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from ipcraft.parser.vendor.parse_dispatcher import ParseDispatcher, ParseFormatError

FIXTURES = Path(__file__).parent / "fixtures"


class TestDetectFormat:
    """Unit tests for ParseDispatcher.detect_format()."""

    def test_hw_tcl(self):
        d = ParseDispatcher()
        assert d.detect_format(Path("foo_hw.tcl")) == "hw_tcl"

    def test_component_xml(self):
        d = ParseDispatcher()
        assert d.detect_format(FIXTURES / "simple_uart_component.xml") == "ipxact"

    def test_vhd(self):
        d = ParseDispatcher()
        assert d.detect_format(Path("my_entity.vhd")) == "vhdl"

    def test_vhdl(self):
        d = ParseDispatcher()
        assert d.detect_format(Path("my_entity.vhdl")) == "vhdl"

    def test_v(self):
        d = ParseDispatcher()
        assert d.detect_format(Path("my_module.v")) == "verilog"

    def test_sv(self):
        d = ParseDispatcher()
        assert d.detect_format(Path("my_module.sv")) == "verilog"

    def test_unknown_raises(self):
        d = ParseDispatcher()
        with pytest.raises(ParseFormatError):
            d.detect_format(Path("foo.xyz"))

    def test_generic_xml_sniffs_ipxact(self, tmp_path):
        """An .xml file that contains a spirit:component root is IP-XACT."""
        xml_file = tmp_path / "core.xml"
        xml_file.write_text(
            '<?xml version="1.0"?>'
            '<spirit:component xmlns:spirit="http://www.spiritconsortium.org/XMLSchema/SPIRIT/1685-2009"/>'
        )
        d = ParseDispatcher()
        assert d.detect_format(xml_file) == "ipxact"

    def test_generic_xml_unknown(self, tmp_path):
        """An .xml file that is not IP-XACT raises ParseFormatError."""
        xml_file = tmp_path / "data.xml"
        xml_file.write_text('<root/>')
        d = ParseDispatcher()
        with pytest.raises(ParseFormatError):
            d.detect_format(xml_file)


class TestParseDispatch:
    """Integration tests dispatching to real parsers."""

    def test_dispatches_hw_tcl(self):
        d = ParseDispatcher()
        ip = d.parse(FIXTURES / "simple_uart_hw.tcl")
        assert ip.vlnv.name == "simple_uart"

    def test_dispatches_ipxact(self):
        d = ParseDispatcher()
        ip = d.parse(FIXTURES / "simple_uart_component.xml")
        assert ip.vlnv.name == "simple_uart"

    def test_dispatches_axilite(self):
        d = ParseDispatcher()
        ip = d.parse(FIXTURES / "axilite_slave_hw.tcl")
        assert ip.vlnv.name == "axilite_slave"

    def test_unknown_file_raises(self, tmp_path):
        txt = tmp_path / "random.json"
        txt.write_text("{}")
        d = ParseDispatcher()
        with pytest.raises(ParseFormatError):
            d.parse(txt)
