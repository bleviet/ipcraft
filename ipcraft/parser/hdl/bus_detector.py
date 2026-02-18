"""
Bus interface detector module.

Analyzes parsed VHDL ports to detect common bus interfaces (AXI-Lite, AXI-Stream,
Avalon-MM, etc.) by matching port naming patterns against bus definitions.
"""

import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from ipcraft.model.base import Polarity
from ipcraft.model.bus import BusInterface, BusInterfaceMode
from ipcraft.model.clock_reset import Clock, Reset
from ipcraft.model.port import Port, PortDirection
from ipcraft.utils import BUS_DEFINITIONS_PATH

# Default path to bus definitions
DEFAULT_BUS_DEFS_PATH = BUS_DEFINITIONS_PATH


class BusInterfaceDetector:
    """
    Detects bus interfaces from parsed VHDL ports.

    Uses pattern matching against bus definitions to identify
    AXI-Lite, AXI-Stream, Avalon-MM, and other standard interfaces.
    """

    def __init__(self, bus_defs_path: Optional[Path] = None):
        """
        Initialize detector with bus definitions.

        Args:
            bus_defs_path: Path to bus_definitions.yml file.
                            Defaults to ipcraft-spec/common/bus_definitions.yml
        """
        self.bus_defs_path = bus_defs_path or DEFAULT_BUS_DEFS_PATH
        self.bus_definitions = self._load_definitions()

    def _load_definitions(self) -> Dict[str, Any]:
        """Load bus definitions from YAML file."""
        if not self.bus_defs_path.exists():
            return {}
        with open(self.bus_defs_path, "r") as f:
            return yaml.safe_load(f) or {}

    def detect(self, ports: List[Port]) -> List[BusInterface]:
        """
        Analyze ports and return detected bus interfaces.

        Args:
            ports: List of parsed Port objects

        Returns:
            List of detected BusInterface objects
        """
        detected = []

        # Group ports by prefix
        prefix_groups = self._group_ports_by_prefix(ports)

        # For each prefix group, try to match against bus definitions
        for prefix, group_ports in prefix_groups.items():
            bus_match = self._match_bus_type(prefix, group_ports)
            if bus_match:
                detected.append(bus_match)

        return detected

    def classify_clocks_resets(self, ports: List[Port]) -> Tuple[List[Clock], List[Reset]]:
        """
        Identify clock and reset signals from ports.

        Args:
            ports: List of parsed Port objects

        Returns:
            Tuple of (clocks, resets) lists
        """
        clocks = []
        resets = []

        # Common clock patterns
        clock_patterns = [
            r"^i?_?clk",
            r"^i?_?clock",
            r"_clk$",
            r"_clock$",
            r"^aclk$",
            r"^i_clk_.*",
        ]

        # Common reset patterns
        reset_patterns = [
            r"^i?_?rst",
            r"^i?_?reset",
            r"_rst$",
            r"_reset$",
            r"^aresetn?$",
            r"^i_rst_n?_.*",
        ]

        for port in ports:
            if port.direction != PortDirection.IN:
                continue

            name_lower = port.name.lower()

            # Check clock patterns
            for pattern in clock_patterns:
                if re.search(pattern, name_lower, re.IGNORECASE):
                    clocks.append(
                        Clock(
                            name=port.name,
                            frequency=None,  # Unknown from VHDL
                            description=f"Detected clock signal",
                        )
                    )
                    break

            # Check reset patterns
            for pattern in reset_patterns:
                if re.search(pattern, name_lower, re.IGNORECASE):
                    # Detect polarity from name
                    polarity = (
                        Polarity.ACTIVE_LOW
                        if "_n" in name_lower or "resetn" in name_lower
                        else Polarity.ACTIVE_HIGH
                    )
                    resets.append(
                        Reset(
                            name=port.name, polarity=polarity, description=f"Detected reset signal"
                        )
                    )
                    break

        return clocks, resets

    def _group_ports_by_prefix(self, ports: List[Port]) -> Dict[str, List[Port]]:
        """
        Group ports by common prefix.

        Identifies prefixes like 's_axi_', 'm_axis_', 'avs_', etc.
        """
        groups = defaultdict(list)

        # Known bus prefixes to look for
        prefix_patterns = [
            r"^(s_axi_\w*?)(?:aw|ar|w|r|b)",  # AXI-Lite slave
            r"^(m_axi_\w*?)(?:aw|ar|w|r|b)",  # AXI-Lite master
            r"^(s_axis_\w*?)t",  # AXI-Stream sink
            r"^(m_axis_\w*?)t",  # AXI-Stream source
            r"^(avs_)",  # Avalon slave
            r"^(avm_)",  # Avalon master
        ]

        for port in ports:
            name_lower = port.name.lower()
            matched = False

            for pattern in prefix_patterns:
                match = re.match(pattern, name_lower)
                if match:
                    prefix = match.group(1)
                    groups[prefix].append(port)
                    matched = True
                    break

            if not matched:
                # Try to extract prefix from underscore-separated name
                parts = name_lower.split("_")
                if len(parts) >= 2:
                    # Use first two parts as potential prefix
                    potential_prefix = f"{parts[0]}_{parts[1]}_"
                    if any(p.name.lower().startswith(potential_prefix) for p in ports if p != port):
                        groups[potential_prefix].append(port)

        return dict(groups)

    def _match_bus_type(self, prefix: str, ports: List[Port]) -> Optional[BusInterface]:
        """
        Match a port group against known bus definitions.

        Args:
            prefix: Port name prefix (e.g., 's_axi_')
            ports: List of ports with this prefix

        Returns:
            BusInterface if match found, None otherwise
        """
        # Create suffix map from ports
        suffix_map = {}
        for port in ports:
            suffix = port.name.lower()[len(prefix) :].upper()
            suffix_map[suffix] = port

        best_match = None
        best_score = 0

        for bus_name, bus_def in self.bus_definitions.items():
            if "ports" not in bus_def:
                continue

            required_ports = [
                p["name"] for p in bus_def["ports"] if p.get("presence") == "required"
            ]
            optional_ports = [
                p["name"] for p in bus_def["ports"] if p.get("presence") == "optional"
            ]

            # Count matches
            required_matched = sum(1 for p in required_ports if p in suffix_map)
            optional_matched = sum(1 for p in optional_ports if p in suffix_map)

            # Calculate score (required matches are worth more)
            if len(required_ports) > 0:
                required_ratio = required_matched / len(required_ports)
            else:
                required_ratio = 0

            # Need at least 70% of required ports to consider it a match
            if required_ratio >= 0.7:
                score = required_matched * 10 + optional_matched

                if score > best_score:
                    best_score = score
                    # Determine mode from port directions
                    mode = self._detect_bus_mode(bus_def, suffix_map)
                    best_match = BusInterface(
                        name=f"{prefix.strip('_').upper()}",
                        type=bus_name,
                        mode=mode,
                        physical_prefix=prefix,
                        description=f"Detected {bus_name} interface",
                    )

        return best_match

    def _detect_bus_mode(
        self, bus_def: Dict[str, Any], suffix_map: Dict[str, Port]
    ) -> BusInterfaceMode:
        """
        Determine bus mode (master/slave/source/sink) from port directions.

        The bus definition uses directions for master/source perspective.
        If actual directions are inverted, the interface is slave/sink.
        """
        bus_type_name = bus_def.get("busType", {}).get("name", "").lower()

        # For AXI-Stream, use source/sink terminology
        if "axis" in bus_type_name or "avalon_st" in bus_type_name:
            # Check TDATA or DATA direction
            for port_def in bus_def.get("ports", []):
                if port_def["name"].upper() in ("TDATA", "DATA"):
                    expected_dir = port_def.get("direction", "out")
                    if port_def["name"].upper() in suffix_map:
                        actual_port = suffix_map[port_def["name"].upper()]
                        if expected_dir == "out" and actual_port.direction == PortDirection.OUT:
                            return BusInterfaceMode.SOURCE
                        elif expected_dir == "out" and actual_port.direction == PortDirection.IN:
                            return BusInterfaceMode.SINK
            return BusInterfaceMode.SOURCE  # Default

        # For memory-mapped buses, use master/slave
        # Check AWREADY or ARREADY direction
        for port_def in bus_def.get("ports", []):
            if port_def["name"].upper() in ("AWREADY", "ARREADY", "READDATA"):
                expected_dir = port_def.get("direction", "in")
                if port_def["name"].upper() in suffix_map:
                    actual_port = suffix_map[port_def["name"].upper()]
                    # Master: AWREADY is input (from slave)
                    # Slave: AWREADY is output (to master)
                    if expected_dir == "in" and actual_port.direction == PortDirection.OUT:
                        return BusInterfaceMode.SLAVE
                    elif expected_dir == "in" and actual_port.direction == PortDirection.IN:
                        return BusInterfaceMode.MASTER

        return BusInterfaceMode.SLAVE  # Default for most IPs
