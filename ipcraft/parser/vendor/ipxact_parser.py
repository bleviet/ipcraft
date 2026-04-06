"""
Xilinx Vivado IP-XACT component.xml parser.

Supports both IP-XACT 2009 (spirit: namespace) and IP-XACT 2014 (ipxact:
namespace).  Uses only stdlib xml.etree.ElementTree — no additional deps.
"""

import logging
import xml.etree.ElementTree as ET
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
# Namespace URIs
# ---------------------------------------------------------------------------

_NS_URIS = {
    "spirit": "http://www.spiritconsortium.org/XMLSchema/SPIRIT/1685-2009-06",
    "ipxact":  "http://www.accellera.org/XMLSchema/IPXACT/1685-2014",
}

# ---------------------------------------------------------------------------
# Bus type mapping: (busType name, vendor) → ipcraft canonical key
# ---------------------------------------------------------------------------

_BUS_NAME_MAP: Dict[str, str] = {
    "aximm":      "AXI4_LITE",   # Default; refined by addr-width heuristic
    "axis":       "AXI_STREAM",
    "axi4":       "AXI4_FULL",
    "axi4lite":   "AXI4_LITE",
    "axi4_lite":  "AXI4_LITE",
    "axi4stream": "AXI_STREAM",
    "axi_stream": "AXI_STREAM",
    "avalon":     "AVALON_MM",
    "avalon_streaming": "AVALON_ST",
}

# IP-XACT direction → PortDirection
_DIR_MAP: Dict[str, PortDirection] = {
    "in":    PortDirection.IN,
    "out":   PortDirection.OUT,
    "inout": PortDirection.INOUT,
}


class IpXactParser:
    """Parse a Xilinx Vivado component.xml (IP-XACT) file into an IpCore."""

    def parse_file(self, path: Path) -> IpCore:
        """Parse a component.xml file and return an IpCore.

        Args:
            path: Path to the IP-XACT XML file.

        Returns:
            IpCore model with optional memory maps stored in
            ``ip_core._discovered_registers`` (list-of-dicts).
        """
        content = Path(path).read_text(encoding="utf-8", errors="replace")
        return self.parse_string(content, source_name=str(path))

    def parse_string(self, content: str, source_name: str = "<string>") -> IpCore:
        """Parse IP-XACT XML content and return an IpCore.

        Args:
            content: Raw XML text.
            source_name: Display name used in log messages.

        Returns:
            IpCore model.
        """
        try:
            root = ET.fromstring(content)
        except ET.ParseError as exc:
            raise ValueError(f"Invalid XML in {source_name}: {exc}") from exc

        ns_prefix, ns_uri = self._detect_namespace(root)
        ns = {ns_prefix: ns_uri}

        vlnv = self._extract_vlnv(root, ns_prefix, ns)
        description = self._text(root, f"{ns_prefix}:description", ns) or ""
        ports = self._extract_ports(root, ns_prefix, ns)
        bus_interfaces, clocks, resets = self._extract_bus_interfaces(
            root, ns_prefix, ns, ports
        )
        standalone_ports = self._filter_standalone_ports(ports, bus_interfaces, clocks, resets)
        parameters = self._extract_parameters(root, ns_prefix, ns)
        discovered_regs = self._extract_memory_maps(root, ns_prefix, ns)

        ip_core = IpCore(
            vlnv=vlnv,
            description=description,
            ports=standalone_ports,
            bus_interfaces=bus_interfaces,
            clocks=clocks,
            resets=resets,
            parameters=parameters,
        )
        # Stash discovered register data as a private attribute so cmd_parse
        # can pass it to MmYamlGenerator without modifying IpCore schema.
        if discovered_regs:
            object.__setattr__(ip_core, "_discovered_registers", discovered_regs)

        return ip_core

    # ------------------------------------------------------------------
    # Namespace detection
    # ------------------------------------------------------------------

    def _detect_namespace(self, root: ET.Element) -> Tuple[str, str]:
        """Return ('spirit' | 'ipxact', uri) based on the root tag."""
        tag = root.tag
        for prefix, uri in _NS_URIS.items():
            if f"{{{uri}}}" in tag:
                return prefix, uri
        # Fallback: try the first namespace seen in the tag
        if tag.startswith("{"):
            uri = tag[1: tag.index("}")]
            return "spirit", uri
        return "spirit", _NS_URIS["spirit"]

    # ------------------------------------------------------------------
    # VLNV
    # ------------------------------------------------------------------

    def _extract_vlnv(
        self, root: ET.Element, prefix: str, ns: Dict[str, str]
    ) -> VLNV:
        vendor  = self._text(root, f"{prefix}:vendor",  ns) or "user"
        library = self._text(root, f"{prefix}:library", ns) or "ip"
        name    = self._text(root, f"{prefix}:name",    ns) or "unknown"
        version = self._text(root, f"{prefix}:version", ns) or "1.0"
        # Sanitise name: replace spaces/dots with underscores
        name = name.replace(" ", "_").replace(".", "_")
        return VLNV(vendor=vendor, library=library, name=name, version=version)

    # ------------------------------------------------------------------
    # Ports
    # ------------------------------------------------------------------

    def _extract_ports(
        self, root: ET.Element, prefix: str, ns: Dict[str, str]
    ) -> Dict[str, Port]:
        """Return a dict of physical-port-name → Port (all ports in model)."""
        ports: Dict[str, Port] = {}
        model_el = root.find(f"{prefix}:model", ns)
        if model_el is None:
            return ports
        ports_el = model_el.find(f"{prefix}:ports", ns)
        if ports_el is None:
            return ports
        for port_el in ports_el.findall(f"{prefix}:port", ns):
            pname = self._text(port_el, f"{prefix}:name", ns) or ""
            wire_el = port_el.find(f"{prefix}:wire", ns)
            if wire_el is None:
                continue
            dir_str = (self._text(wire_el, f"{prefix}:direction", ns) or "in").lower()
            direction = _DIR_MAP.get(dir_str, PortDirection.IN)
            width = self._extract_port_width(wire_el, prefix, ns)
            ports[pname] = Port(name=pname, direction=direction, width=width)
        return ports

    def _extract_port_width(
        self, wire_el: ET.Element, prefix: str, ns: Dict[str, str]
    ) -> int:
        """Extract port width from wire element."""
        vector_el = wire_el.find(f"{prefix}:vector", ns)
        if vector_el is None:
            return 1
        left_txt  = self._text(vector_el, f"{prefix}:left",  ns)
        right_txt = self._text(vector_el, f"{prefix}:right", ns)
        try:
            left  = int(left_txt)   # type: ignore[arg-type]
            right = int(right_txt)  # type: ignore[arg-type]
            return abs(left - right) + 1
        except (TypeError, ValueError):
            return 1

    # ------------------------------------------------------------------
    # Bus interfaces
    # ------------------------------------------------------------------

    def _extract_bus_interfaces(
        self,
        root: ET.Element,
        prefix: str,
        ns: Dict[str, str],
        all_ports: Dict[str, Port],
    ) -> Tuple[List[BusInterface], List[Clock], List[Reset]]:
        """Parse busInterfaces section → (bus_interfaces, clocks, resets)."""
        bus_interfaces: List[BusInterface] = []
        clocks: List[Clock] = []
        resets: List[Reset] = []

        bis_el = root.find(f"{prefix}:busInterfaces", ns)
        if bis_el is None:
            return bus_interfaces, clocks, resets

        for bi_el in bis_el.findall(f"{prefix}:busInterface", ns):
            bi_name = self._text(bi_el, f"{prefix}:name", ns) or "bus"

            # Determine mode
            mode = self._extract_mode(bi_el, prefix, ns)

            # Bus type element
            bus_type_el = bi_el.find(f"{prefix}:busType", ns)
            bus_type_name = ""
            if bus_type_el is not None:
                bus_type_name = bus_type_el.get(f"{{{ns[prefix]}}}name", "")

            # Collect physical port names via portMaps
            physical_ports = self._collect_port_map_names(bi_el, prefix, ns)

            # Classify as clock / reset / bus
            bt_lower = bus_type_name.lower()
            if bt_lower in ("clock", "clk", "clock_source", "clock_sink"):
                for pname in physical_ports:
                    if pname in all_ports:
                        clocks.append(Clock(
                            name=bi_name,
                            direction=all_ports[pname].direction,
                            width=all_ports[pname].width,
                        ))
                        break
                continue

            if bt_lower in ("reset", "reset_source", "reset_sink"):
                for pname in physical_ports:
                    if pname in all_ports:
                        resets.append(Reset(
                            name=bi_name,
                            direction=all_ports[pname].direction,
                            width=all_ports[pname].width,
                        ))
                        break
                continue

            ipcraft_key = self._map_bus_type(bus_type_name)
            prefix_str = self._derive_prefix(physical_ports, bi_name)

            bus_interfaces.append(BusInterface(
                name=bi_name,
                type=ipcraft_key,
                mode=mode,
                physical_prefix=prefix_str,
            ))

        return bus_interfaces, clocks, resets

    def _extract_mode(
        self, bi_el: ET.Element, prefix: str, ns: Dict[str, str]
    ) -> BusInterfaceMode:
        """Return SLAVE or MASTER by inspecting child elements."""
        for child in bi_el:
            local = child.tag.split("}")[-1].lower() if "}" in child.tag else child.tag.lower()
            if local in ("slave", "sink"):
                return BusInterfaceMode.SLAVE
            if local in ("master", "source"):
                return BusInterfaceMode.MASTER
        return BusInterfaceMode.SLAVE

    def _collect_port_map_names(
        self, bi_el: ET.Element, prefix: str, ns: Dict[str, str]
    ) -> List[str]:
        """Return list of physical port names referenced in portMaps."""
        names: List[str] = []
        pm_parent = bi_el.find(f"{prefix}:portMaps", ns)
        if pm_parent is None:
            return names
        for pm in pm_parent.findall(f"{prefix}:portMap", ns):
            phys_el = pm.find(f"{prefix}:physicalPort/{prefix}:name", ns)
            if phys_el is not None and phys_el.text:
                names.append(phys_el.text.strip())
        return names

    def _derive_prefix(self, port_names: List[str], fallback: str) -> str:
        """Derive a physical prefix from the longest common prefix of port names."""
        if not port_names:
            return fallback.lower() + "_"
        prefix = port_names[0]
        for name in port_names[1:]:
            while not name.startswith(prefix) and prefix:
                prefix = prefix[:-1]
        last_sep = max(prefix.rfind("_"), 0)
        prefix = prefix[: last_sep + 1] if last_sep > 0 else prefix + "_"
        return prefix.lower() if prefix else fallback.lower() + "_"

    def _map_bus_type(self, type_name: str) -> str:
        """Map IP-XACT busType name to ipcraft canonical bus key."""
        return _BUS_NAME_MAP.get(type_name.lower(), "AXI4_LITE")

    # ------------------------------------------------------------------
    # Standalone ports (not claimed by any bus/clock/reset interface)
    # ------------------------------------------------------------------

    def _filter_standalone_ports(
        self,
        all_ports: Dict[str, Port],
        bus_interfaces: List[BusInterface],
        clocks: List[Clock],
        resets: List[Reset],
    ) -> List[Port]:
        """Return ports not covered by any bus, clock, or reset interface."""
        claimed: set = set()
        for bi in bus_interfaces:
            prefix = bi.physical_prefix.lower()
            for pname in all_ports:
                if pname.lower().startswith(prefix):
                    claimed.add(pname)
        for c in clocks:
            claimed.add(c.name)
        for r in resets:
            claimed.add(r.name)
        return [p for pname, p in all_ports.items() if pname not in claimed]

    # ------------------------------------------------------------------
    # Parameters
    # ------------------------------------------------------------------

    def _extract_parameters(
        self, root: ET.Element, prefix: str, ns: Dict[str, str]
    ) -> List[Parameter]:
        params: List[Parameter] = []
        params_el = root.find(f"{prefix}:parameters", ns)
        if params_el is None:
            return params
        for param_el in params_el.findall(f"{prefix}:parameter", ns):
            pname = self._text(param_el, f"{prefix}:name",  ns)
            pval  = self._text(param_el, f"{prefix}:value", ns)
            if not pname:
                continue
            # Try to convert value to int, else keep as string
            value: Any = pval or ""
            try:
                value = int(value)
                ptype = ParameterType.INTEGER
            except (ValueError, TypeError):
                try:
                    value = float(value)
                    ptype = ParameterType.REAL
                except (ValueError, TypeError):
                    ptype = ParameterType.STRING
            # Skip Xilinx internal parameters (usually start with C_ and are numbers)
            params.append(Parameter(name=pname, value=value, data_type=ptype))
        return params

    # ------------------------------------------------------------------
    # Memory maps → discovered register data (list-of-dicts for MmYamlGenerator)
    # ------------------------------------------------------------------

    def _extract_memory_maps(
        self, root: ET.Element, prefix: str, ns: Dict[str, str]
    ) -> List[Dict[str, Any]]:
        """Extract memory maps and return list of dicts matching .mm.yml schema."""
        result: List[Dict[str, Any]] = []
        mms_el = root.find(f"{prefix}:memoryMaps", ns)
        if mms_el is None:
            return result
        for mm_el in mms_el.findall(f"{prefix}:memoryMap", ns):
            mm_name = self._text(mm_el, f"{prefix}:name", ns) or "REGS"
            mm_desc = self._text(mm_el, f"{prefix}:description", ns) or ""
            address_blocks: List[Dict[str, Any]] = []
            for ab_el in mm_el.findall(f"{prefix}:addressBlock", ns):
                ab = self._parse_address_block(ab_el, prefix, ns)
                address_blocks.append(ab)
            mm_dict: Dict[str, Any] = {"name": mm_name, "addressBlocks": address_blocks}
            if mm_desc:
                mm_dict["description"] = mm_desc
            result.append(mm_dict)
        return result

    def _parse_address_block(
        self, ab_el: ET.Element, prefix: str, ns: Dict[str, str]
    ) -> Dict[str, Any]:
        ab_name = self._text(ab_el, f"{prefix}:name",        ns) or "BLOCK"
        base_addr_txt = self._text(ab_el, f"{prefix}:baseAddress", ns) or "0"
        width_txt     = self._text(ab_el, f"{prefix}:width",       ns) or "32"
        try:
            base_addr = int(base_addr_txt, 0)
        except ValueError:
            base_addr = 0
        try:
            reg_width = int(width_txt)
        except ValueError:
            reg_width = 32

        registers: List[Dict[str, Any]] = []
        for reg_el in ab_el.findall(f"{prefix}:register", ns):
            reg = self._parse_register(reg_el, prefix, ns)
            registers.append(reg)

        return {
            "name": ab_name,
            "baseAddress": base_addr,
            "usage": "register",
            "defaultRegWidth": reg_width,
            "registers": registers,
        }

    def _parse_register(
        self, reg_el: ET.Element, prefix: str, ns: Dict[str, str]
    ) -> Dict[str, Any]:
        reg_name   = self._text(reg_el, f"{prefix}:name",          ns) or "REG"
        reg_desc   = self._text(reg_el, f"{prefix}:description",   ns) or ""
        offset_txt = self._text(reg_el, f"{prefix}:addressOffset", ns) or "0"
        size_txt   = self._text(reg_el, f"{prefix}:size",          ns) or "32"

        try:
            offset = int(offset_txt, 0)
        except ValueError:
            offset = 0
        try:
            size = int(size_txt)
        except ValueError:
            size = 32

        fields: List[Dict[str, Any]] = []
        for field_el in reg_el.findall(f"{prefix}:field", ns):
            field = self._parse_field(field_el, prefix, ns)
            fields.append(field)

        reg: Dict[str, Any] = {
            "name": reg_name,
            "addressOffset": hex(offset),
        }
        if reg_desc:
            reg["description"] = reg_desc
        if fields:
            reg["fields"] = fields

        return reg

    def _parse_field(
        self, field_el: ET.Element, prefix: str, ns: Dict[str, str]
    ) -> Dict[str, Any]:
        fname      = self._text(field_el, f"{prefix}:name",        ns) or "FIELD"
        fdesc      = self._text(field_el, f"{prefix}:description", ns) or ""
        offset_txt = self._text(field_el, f"{prefix}:bitOffset",   ns) or "0"
        width_txt  = self._text(field_el, f"{prefix}:bitWidth",    ns) or "1"
        access_txt = self._text(field_el, f"{prefix}:access",      ns) or "read-write"

        try:
            bit_offset = int(offset_txt)
            bit_width  = int(width_txt)
        except ValueError:
            bit_offset, bit_width = 0, 1

        msb = bit_offset + bit_width - 1
        bits = f"[{msb}:{bit_offset}]" if msb != bit_offset else f"[{bit_offset}:{bit_offset}]"

        field: Dict[str, Any] = {
            "name": fname,
            "bits": bits,
            "access": access_txt,
        }
        if fdesc:
            field["description"] = fdesc
        return field

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _text(
        el: ET.Element, path: str, ns: Dict[str, str]
    ) -> Optional[str]:
        """Find a child element and return its stripped text, or None."""
        child = el.find(path, ns)
        if child is not None and child.text:
            return child.text.strip()
        return None
