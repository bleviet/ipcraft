"""
Bus interface detector module.

Analyzes parsed VHDL ports to detect common bus interfaces (AXI-Lite, AXI-Stream,
Avalon-MM, etc.) by matching port naming patterns against bus definitions.
"""

import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from ipcraft.model.base import Polarity
from ipcraft.model.bus import BusInterface, BusInterfaceMode
from ipcraft.model.bus_library import BusLibrary, get_bus_library
from ipcraft.model.clock_reset import Clock, Reset
from ipcraft.model.port import Port, PortDirection

# Minimum fraction of required ports that must be present to claim a bus match
_REQUIRED_MATCH_THRESHOLD = 0.7
# How much more a required-port match counts versus an optional-port match in scoring
_REQUIRED_PORT_SCORE_WEIGHT = 10

# ---------------------------------------------------------------------------
# Clock / reset name heuristics (matched against port names)
# ---------------------------------------------------------------------------
_CLOCK_NAME_RE = re.compile(
    r"^i?_?clk|^i?_?clock|_clk$|_clock$|^aclk$|^i_clk_",
    re.IGNORECASE,
)
_RESET_NAME_RE = re.compile(
    r"^i?_?rst|^i?_?reset|_rst$|_reset$|^aresetn?$|^i_rst_n?_",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# VHDL edge-construct patterns (matched against architecture body text).
# Each tuple is (compiled_pattern, edge_type).  Group 1 captures the signal name.
#
# Supported constructs:
#   rising_edge(clk)                 — IEEE Std 1076-1993 and later
#   falling_edge(clk)                — same
#   clk'event and clk = '1'         — traditional rising-edge (pre-1993 style)
#   clk'event and clk = '0'         — traditional falling-edge
# ---------------------------------------------------------------------------
_VHDL_CLOCK_CONSTRUCTS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"\brising_edge\s*\(\s*(\w+)\s*\)", re.IGNORECASE), "rising"),
    (re.compile(r"\bfalling_edge\s*\(\s*(\w+)\s*\)", re.IGNORECASE), "falling"),
    (re.compile(r"\b(\w+)'event\s+and\s+\1\s*=\s*'1'", re.IGNORECASE), "rising"),
    (re.compile(r"\b(\w+)'event\s+and\s+\1\s*=\s*'0'", re.IGNORECASE), "falling"),
]


class BusInterfaceDetector:
    """
    Detects bus interfaces from parsed VHDL ports.

    Uses pattern matching against bus definitions to identify
    AXI-Lite, AXI-Stream, Avalon-MM, and other standard interfaces.
    """

    def __init__(self, bus_library: Optional[BusLibrary] = None):
        """
        Initialize detector with bus definitions.
        """
        self._bus_library = bus_library or get_bus_library()
        self.bus_definitions = self._bus_library.get_all_raw_dicts()

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

    def classify_clocks_resets(
        self, ports: List[Port], vhdl_text: Optional[str] = None
    ) -> Tuple[List[Clock], List[Reset]]:
        """
        Identify clock and reset signals from a list of ports.

        When ``vhdl_text`` is provided the architecture body is scanned for
        real edge-triggered constructs (``rising_edge``, ``falling_edge``,
        ``'event and … = '1'``).  Ports whose names appear in such constructs
        are classified as clocks with high confidence.  Name-pattern heuristics
        serve as a fallback for ports not found via structural analysis.

        Args:
            ports: Parsed port objects from the entity declaration.
            vhdl_text: Full VHDL source text (optional).  Supply this to enable
                       architecture-body clock detection.

        Returns:
            Tuple of (clocks, resets) lists.
        """
        clock_signals = (
            self._detect_clock_names_from_vhdl(vhdl_text) if vhdl_text else set()
        )

        clocks: List[Clock] = []
        resets: List[Reset] = []

        for port in ports:
            if port.direction != PortDirection.IN:
                continue

            name_lower = port.name.lower()

            if port.width == 1 and (name_lower in clock_signals or _CLOCK_NAME_RE.search(name_lower)):
                clocks.append(Clock(name=port.name, description="Detected clock signal"))
            elif _RESET_NAME_RE.search(name_lower):
                polarity = (
                    Polarity.ACTIVE_LOW
                    if "_n" in name_lower or "resetn" in name_lower
                    else Polarity.ACTIVE_HIGH
                )
                resets.append(
                    Reset(name=port.name, polarity=polarity, description="Detected reset signal")
                )

        return clocks, resets

    def _detect_clock_names_from_vhdl(self, vhdl_text: str) -> set:
        """
        Scan VHDL source for edge-triggered process constructs and return the
        set of signal names (lowercase) used as clock arguments.

        Recognises:
          rising_edge(clk)  /  falling_edge(clk)
          clk'event and clk = '1'  /  clk'event and clk = '0'
        """
        # Strip comments so patterns don't match commented-out code
        clean = re.sub(r"--.*$", "", vhdl_text, flags=re.MULTILINE)
        clock_names: set = set()
        for pattern, _edge in _VHDL_CLOCK_CONSTRUCTS:
            for m in pattern.finditer(clean):
                clock_names.add(m.group(1).lower())
        return clock_names

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

            for pattern in prefix_patterns:
                m = re.match(pattern, name_lower)
                if m:
                    groups[m.group(1)].append(port)
                    break
            else:
                # Try to extract prefix from underscore-separated name
                parts = name_lower.split("_")
                if len(parts) >= 2:
                    potential_prefix = f"{parts[0]}_{parts[1]}_"
                    if any(
                        p.name.lower().startswith(potential_prefix)
                        for p in ports
                        if p != port
                    ):
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

            required_ratio = required_matched / len(required_ports) if required_ports else 0

            if required_ratio >= _REQUIRED_MATCH_THRESHOLD:
                score = required_matched * _REQUIRED_PORT_SCORE_WEIGHT + optional_matched

                if score > best_score:
                    best_score = score
                    mode = self._detect_bus_mode(bus_def, suffix_map)
                    best_match = BusInterface(
                        name=prefix.strip("_").upper(),
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

        # For AXI-Stream / Avalon-ST, classify as source or sink
        if "axis" in bus_type_name or "avalon_st" in bus_type_name:
            for port_def in bus_def.get("ports", []):
                port_name = port_def["name"].upper()
                if port_name not in ("TDATA", "DATA") or port_name not in suffix_map:
                    continue
                if port_def.get("direction", "out") == "out":
                    actual = suffix_map[port_name]
                    return (
                        BusInterfaceMode.SOURCE
                        if actual.direction == PortDirection.OUT
                        else BusInterfaceMode.SINK
                    )
            return BusInterfaceMode.SOURCE

        # For memory-mapped buses, classify as master or slave.
        # AWREADY/ARREADY are driven by the slave — if they're outputs here, this is the slave.
        for port_def in bus_def.get("ports", []):
            port_name = port_def["name"].upper()
            if port_name not in ("AWREADY", "ARREADY", "READDATA") or port_name not in suffix_map:
                continue
            if port_def.get("direction", "in") == "in":
                actual = suffix_map[port_name]
                return (
                    BusInterfaceMode.SLAVE
                    if actual.direction == PortDirection.OUT
                    else BusInterfaceMode.MASTER
                )

        return BusInterfaceMode.SLAVE
