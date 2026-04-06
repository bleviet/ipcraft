"""
Intel Platform Designer _hw.tcl parser.

Parses Intel Quartus / Platform Designer component description files into an
IpCore model using regex-based extraction (no Tcl interpreter required).
"""

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ipcraft.model import (
    VLNV,
    BusInterface,
    Clock,
    IpCore,
    Parameter,
    Port,
    PortDirection,
    Reset,
)
from ipcraft.model.base import ParameterType
from ipcraft.model.bus import BusInterfaceMode

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

RE_MODULE_INFO = re.compile(
    r'set_module_info\s+-(\w+)\s+"([^"]*)"', re.IGNORECASE
)
RE_ADD_INTERFACE = re.compile(
    r"add_interface\s+(\S+)\s+(\S+)\s+(\S+)", re.IGNORECASE
)
RE_IF_PROPERTY = re.compile(
    r"set_interface_property\s+(\S+)\s+(\S+)\s+(\S+)", re.IGNORECASE
)
RE_ADD_IF_PORT = re.compile(
    r'add_interface_port\s+(\S+)\s+(\S+)\s+(\S*)\s+(Input|Output|Bidir)\s+(\d+)',
    re.IGNORECASE,
)
RE_ADD_PARAM = re.compile(
    r"add_parameter\s+(\S+)\s+(\S+)\s+(\S+)", re.IGNORECASE
)
RE_PARAM_DISPLAY = re.compile(
    r'set_parameter_property\s+(\S+)\s+DISPLAY_NAME\s+"([^"]*)"', re.IGNORECASE
)

# ---------------------------------------------------------------------------
# Bus type mapping: _hw.tcl interface type → ipcraft canonical bus key
# ---------------------------------------------------------------------------

_BUS_TYPE_MAP: Dict[str, str] = {
    "avalon": "AVALON_MM",
    "avalon_streaming": "AVALON_ST",
    "axi4lite": "AXI4_LITE",
    "axi4": "AXI4_FULL",
    "axi4stream": "AXI_STREAM",
}

# Interface types that map to clock / reset (not bus)
_CLOCK_TYPES = {"clock", "clock_sink", "clock_source"}
_RESET_TYPES = {"reset", "reset_sink", "reset_source"}

# Interface direction mapping
_MODE_MAP: Dict[str, BusInterfaceMode] = {
    "end": BusInterfaceMode.SLAVE,
    "slave": BusInterfaceMode.SLAVE,
    "sink": BusInterfaceMode.SLAVE,
    "start": BusInterfaceMode.MASTER,
    "master": BusInterfaceMode.MASTER,
    "source": BusInterfaceMode.MASTER,
}

# Port direction mapping
_PORT_DIR_MAP: Dict[str, PortDirection] = {
    "input": PortDirection.IN,
    "output": PortDirection.OUT,
    "bidir": PortDirection.INOUT,
}


class HwTclParser:
    """Parse an Intel Platform Designer _hw.tcl file into an IpCore."""

    def parse_file(self, path: Path) -> IpCore:
        """Parse a _hw.tcl file and return an IpCore.

        Args:
            path: Path to the _hw.tcl file.

        Returns:
            IpCore model populated with VLNV, ports, bus interfaces, clocks,
            resets, and parameters.
        """
        content = Path(path).read_text(encoding="utf-8", errors="replace")
        return self.parse_string(content, source_name=str(path))

    def parse_string(self, content: str, source_name: str = "<string>") -> IpCore:
        """Parse _hw.tcl content and return an IpCore.

        Args:
            content: Raw text of the _hw.tcl file.
            source_name: Display name used in log messages.

        Returns:
            IpCore model.
        """
        lines = content.splitlines()
        raw = self._extract_all(lines, source_name)
        return self._map_to_ipcore(raw)

    # ------------------------------------------------------------------
    # Extraction
    # ------------------------------------------------------------------

    def _extract_all(self, lines: List[str], source_name: str) -> Dict[str, Any]:
        """Run all extraction passes over the line list."""
        raw: Dict[str, Any] = {
            "module_info": {},
            "interfaces": {},      # name → {type, direction, assoc_clock, assoc_reset}
            "if_ports": [],        # list of {if_name, port, logical, dir, width}
            "parameters": {},      # name → {type, default, display_name}
        }

        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            self._parse_module_info(stripped, raw)
            self._parse_add_interface(stripped, raw)
            self._parse_if_property(stripped, raw)
            self._parse_add_if_port(stripped, raw)
            self._parse_add_parameter(stripped, raw)
            self._parse_param_property(stripped, raw)

        return raw

    def _parse_module_info(self, line: str, raw: Dict[str, Any]) -> None:
        m = RE_MODULE_INFO.match(line)
        if m:
            raw["module_info"][m.group(1).lower()] = m.group(2)

    def _parse_add_interface(self, line: str, raw: Dict[str, Any]) -> None:
        m = RE_ADD_INTERFACE.match(line)
        if m:
            name, itype, direction = m.group(1), m.group(2).lower(), m.group(3).lower()
            raw["interfaces"][name] = {
                "type": itype,
                "direction": direction,
                "assoc_clock": None,
                "assoc_reset": None,
            }

    def _parse_if_property(self, line: str, raw: Dict[str, Any]) -> None:
        m = RE_IF_PROPERTY.match(line)
        if m:
            if_name, prop, value = m.group(1), m.group(2).lower(), m.group(3)
            if if_name in raw["interfaces"]:
                if prop == "associatedclock":
                    raw["interfaces"][if_name]["assoc_clock"] = value
                elif prop == "associatedreset":
                    raw["interfaces"][if_name]["assoc_reset"] = value

    def _parse_add_if_port(self, line: str, raw: Dict[str, Any]) -> None:
        m = RE_ADD_IF_PORT.match(line)
        if m:
            # Strip surrounding double-quotes from interface name (e.g. "" → "")
            if_name = m.group(1).strip('"')
            raw["if_ports"].append({
                "if_name": if_name,
                "port": m.group(2),
                "logical": m.group(3).strip('"'),
                "dir": m.group(4).lower(),
                "width": int(m.group(5)),
            })

    def _parse_add_parameter(self, line: str, raw: Dict[str, Any]) -> None:
        m = RE_ADD_PARAM.match(line)
        if m:
            name, ptype, default = m.group(1), m.group(2).upper(), m.group(3)
            raw["parameters"][name] = {
                "type": ptype,
                "default": default,
                "display_name": "",
            }

    def _parse_param_property(self, line: str, raw: Dict[str, Any]) -> None:
        m = RE_PARAM_DISPLAY.match(line)
        if m:
            name, display = m.group(1), m.group(2)
            if name in raw["parameters"]:
                raw["parameters"][name]["display_name"] = display

    # ------------------------------------------------------------------
    # Mapping to IpCore
    # ------------------------------------------------------------------

    def _map_to_ipcore(self, raw: Dict[str, Any]) -> IpCore:
        """Convert the raw extraction result into an IpCore."""
        info = raw["module_info"]
        name = info.get("name", "unknown").replace(" ", "_").lower()
        version = info.get("version", "1.0")
        description = info.get("display_name", "") or info.get("description", "")

        vlnv = VLNV(vendor="user", library="ip", name=name, version=version)

        clocks: List[Clock] = []
        resets: List[Reset] = []
        bus_interfaces: List[BusInterface] = []
        standalone_ports: List[Port] = []
        parameters: List[Parameter] = []

        # Collect port names that belong to clock/reset/bus interfaces
        assigned_ports: set = set()

        for if_name, iface in raw["interfaces"].items():
            itype = iface["type"]
            direction = iface["direction"]
            iface_ports = [p for p in raw["if_ports"] if p["if_name"] == if_name]

            if itype in _CLOCK_TYPES:
                for p in iface_ports:
                    clocks.append(Clock(
                        name=if_name,
                        direction=PortDirection.IN,
                        width=p["width"],
                    ))
                    assigned_ports.add(p["port"])
                    break  # Only first port creates the Clock entry
                continue

            if itype in _RESET_TYPES:
                for p in iface_ports:
                    resets.append(Reset(
                        name=if_name,
                        direction=PortDirection.IN,
                        width=p["width"],
                    ))
                    assigned_ports.add(p["port"])
                    break
                continue

            bus_key = _BUS_TYPE_MAP.get(itype)
            if bus_key:
                mode = _MODE_MAP.get(direction, BusInterfaceMode.SLAVE)
                # Derive physical prefix from the first port of this interface
                prefix = self._derive_prefix(iface_ports, if_name)
                assoc_clock = iface.get("assoc_clock")
                assoc_reset = iface.get("assoc_reset")
                bus_interfaces.append(BusInterface(
                    name=if_name,
                    type=bus_key,
                    mode=mode,
                    physical_prefix=prefix,
                    associated_clock=assoc_clock,
                    associated_reset=assoc_reset,
                ))
                for p in iface_ports:
                    assigned_ports.add(p["port"])
                continue

            # conduit or unknown → plain ports
            for p in iface_ports:
                assigned_ports.add(p["port"])
                standalone_ports.append(Port(
                    name=p["port"],
                    direction=_PORT_DIR_MAP.get(p["dir"], PortDirection.IN),
                    width=p["width"],
                ))

        # Ports with empty interface name ("") are also standalone
        for p in raw["if_ports"]:
            if p["if_name"] == "" and p["port"] not in assigned_ports:
                standalone_ports.append(Port(
                    name=p["port"],
                    direction=_PORT_DIR_MAP.get(p["dir"], PortDirection.IN),
                    width=p["width"],
                ))
                assigned_ports.add(p["port"])

        # Parameters
        for pname, pdata in raw["parameters"].items():
            ptype_str = pdata["type"].lower()
            try:
                ptype = ParameterType(ptype_str)
            except ValueError:
                ptype = ParameterType.INTEGER
            default = pdata["default"]
            try:
                default = int(default)
            except (ValueError, TypeError):
                try:
                    default = float(default)
                except (ValueError, TypeError):
                    pass
            parameters.append(Parameter(
                name=pname,
                value=default,
                data_type=ptype,
                description=pdata.get("display_name", ""),
            ))

        return IpCore(
            vlnv=vlnv,
            description=description,
            clocks=clocks,
            resets=resets,
            ports=standalone_ports,
            bus_interfaces=bus_interfaces,
            parameters=parameters,
        )

    @staticmethod
    def _derive_prefix(ports: List[Dict[str, Any]], fallback: str) -> str:
        """Derive a physical port prefix from the common leading characters."""
        if not ports:
            return fallback.lower() + "_"
        names = [p["port"] for p in ports]
        # Find longest common prefix and strip trailing underscores
        prefix = names[0]
        for name in names[1:]:
            while not name.startswith(prefix) and prefix:
                prefix = prefix[:-1]
        # Strip trailing non-underscore chars to land on a clean prefix boundary
        last_sep = max(prefix.rfind("_"), 0)
        prefix = prefix[: last_sep + 1] if last_sep > 0 else prefix + "_"
        return prefix.lower() if prefix else fallback.lower() + "_"
