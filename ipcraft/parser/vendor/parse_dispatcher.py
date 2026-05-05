"""
Parse dispatcher — auto-detect file format and dispatch to the right parser.
"""

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Optional

from ipcraft.model import VLNV, IpCore
from ipcraft.parser.hdl.bus_detector import BusInterfaceDetector
from ipcraft.parser.hdl.vhdl_parser import VHDLParser
from ipcraft.parser.hdl.verilog_parser import VerilogParser
from ipcraft.parser.vendor.hw_tcl_parser import HwTclParser
from ipcraft.parser.vendor.ipxact_parser import IpXactParser


class ParseFormatError(ValueError):
    """Raised when the file format cannot be determined."""


class ParseDispatcher:
    """Detect input format and dispatch to the appropriate parser."""

    def detect_format(self, path: Path) -> str:
        """Detect the format of *path* and return a canonical format string.

        Detection order:
          1. Extension ``.vhd`` / ``.vhdl`` → ``'vhdl'``
          2. Extension ``.v`` / ``.sv`` → ``'verilog'``
          3. Filename ends with ``_hw.tcl`` → ``'hw_tcl'``
          4. Any ``.tcl`` file → ``'hw_tcl'``
          5. XML root tag contains ``component`` → ``'ipxact'``
          6. :class:`ParseFormatError` if unrecognised.

        Args:
            path: Path to the file to inspect.

        Returns:
            One of ``'vhdl'``, ``'verilog'``, ``'hw_tcl'``, ``'ipxact'``.

        Raises:
            ParseFormatError: When the format cannot be determined.
        """
        path = Path(path)
        suffix = path.suffix.lower()
        name_lower = path.name.lower()

        if suffix in (".vhd", ".vhdl"):
            return "vhdl"
        if suffix in (".v", ".sv"):
            return "verilog"
        if name_lower.endswith("_hw.tcl") or suffix == ".tcl":
            return "hw_tcl"
        if suffix == ".xml":
            return self._detect_xml_format(path)

        raise ParseFormatError(
            f"Cannot determine format for '{path.name}'. "
            "Supported: .vhd/.vhdl, .v, _hw.tcl, component.xml"
        )

    def parse(self, path: Path, detect_bus: bool = True, **kwargs: Any) -> IpCore:
        """Detect format and return a parsed IpCore.

        Args:
            path: Path to the source file.
            detect_bus: Enable bus-interface detection for HDL files.

        Returns:
            Parsed IpCore model.
        """
        fmt = self.detect_format(path)
        if fmt == "vhdl":
            return self._parse_vhdl(path, detect_bus=detect_bus)
        if fmt == "verilog":
            return self._parse_verilog(path, detect_bus=detect_bus)
        if fmt == "hw_tcl":
            return HwTclParser().parse_file(path)
        if fmt == "ipxact":
            return IpXactParser().parse_file(path)
        raise ParseFormatError(f"Unsupported format: '{fmt}'")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _detect_xml_format(self, path: Path) -> str:
        """Inspect the XML root element to distinguish IP-XACT from other XML."""
        try:
            for event, elem in ET.iterparse(str(path), events=("start",)):
                tag_local = elem.tag.split("}")[-1].lower() if "}" in elem.tag else elem.tag.lower()
                if tag_local == "component":
                    return "ipxact"
                # Only check root
                break
        except ET.ParseError:
            pass
        raise ParseFormatError(
            f"XML file '{path.name}' does not look like an IP-XACT component.xml"
        )

    def _parse_vhdl(self, path: Path, detect_bus: bool = True) -> IpCore:
        """Parse a VHDL file using the existing VHDLParser + BusInterfaceDetector."""
        vhdl_text = path.read_text()
        parser = VHDLParser()
        result = parser.parse_text(vhdl_text)
        ip_core = result.get("entity")
        if ip_core is None:
            raise ValueError(f"No VHDL entity found in '{path}'")

        if detect_bus:
            detector = BusInterfaceDetector()
            bus_interfaces = detector.detect(ip_core.ports)
            clocks, resets = detector.classify_clocks_resets(ip_core.ports, vhdl_text=vhdl_text)

            claimed = set()
            for bi in bus_interfaces:
                prefix = bi.physical_prefix.lower()
                for port in ip_core.ports:
                    if port.name.lower().startswith(prefix):
                        claimed.add(port.name)
            for c in clocks:
                claimed.add(c.name)
            for r in resets:
                claimed.add(r.name)

            remaining_ports = [p for p in ip_core.ports if p.name not in claimed]

            ip_core = IpCore(
                vlnv=ip_core.vlnv,
                description=ip_core.description,
                clocks=clocks,
                resets=resets,
                ports=remaining_ports,
                bus_interfaces=bus_interfaces,
                parameters=ip_core.parameters,
                file_sets=ip_core.file_sets,
                memory_maps=ip_core.memory_maps,
            )

        return ip_core

    def _parse_verilog(self, path: Path, detect_bus: bool = True) -> IpCore:
        """Parse a Verilog file using the existing VerilogParser."""
        parser = VerilogParser()
        result = parser.parse_file(str(path))
        ip_core = result.get("module")
        if ip_core is None:
            raise ValueError(f"No Verilog module found in '{path}'")

        if detect_bus:
            detector = BusInterfaceDetector()
            bus_interfaces = detector.detect(ip_core.ports)
            clocks, resets = detector.classify_clocks_resets(ip_core.ports)

            claimed = set()
            for bi in bus_interfaces:
                prefix = bi.physical_prefix.lower()
                for port in ip_core.ports:
                    if port.name.lower().startswith(prefix):
                        claimed.add(port.name)
            for c in clocks:
                claimed.add(c.name)
            for r in resets:
                claimed.add(r.name)

            remaining_ports = [p for p in ip_core.ports if p.name not in claimed]

            ip_core = IpCore(
                vlnv=ip_core.vlnv,
                description=ip_core.description,
                clocks=clocks,
                resets=resets,
                ports=remaining_ports,
                bus_interfaces=bus_interfaces,
                parameters=ip_core.parameters,
                file_sets=ip_core.file_sets,
                memory_maps=ip_core.memory_maps,
            )

        return ip_core
