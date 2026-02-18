"""
Bus Library module.

Provides access to predefined bus definitions (AXI4L, AXIS, AVALON_MM, etc.)
from the bus_definitions.yml file.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from ipcraft.model.base import VLNV
from ipcraft.utils import BUS_DEFINITIONS_PATH

# Default path to bus definitions
DEFAULT_BUS_DEFS_PATH = BUS_DEFINITIONS_PATH

# Suggested physical prefixes for each bus type and mode
SUGGESTED_PREFIXES = {
    "AXI4L": {"slave": "s_axil_", "master": "m_axil_"},
    "AXI4": {"slave": "s_axi_", "master": "m_axi_"},
    "AXIS": {"source": "m_axis_", "sink": "s_axis_"},
    "AVALON_MM": {"slave": "avs_", "master": "avm_"},
    "AVALON_ST": {"source": "aso_", "sink": "asi_"},
}


@dataclass
class PortDefinition:
    """Definition of a bus port."""

    name: str
    direction: Optional[str] = None
    width: Optional[int] = None
    presence: str = "required"

    @property
    def is_required(self) -> bool:
        return self.presence == "required"

    @property
    def is_optional(self) -> bool:
        return self.presence == "optional"


@dataclass
class BusDefinition:
    """Complete bus definition including type info and ports."""

    key: str  # e.g., "AXI4L"
    bus_type: VLNV
    ports: List[PortDefinition]
    description: str = ""

    @property
    def required_ports(self) -> List[PortDefinition]:
        return [p for p in self.ports if p.is_required]

    @property
    def optional_ports(self) -> List[PortDefinition]:
        return [p for p in self.ports if p.is_optional]

    def get_suggested_prefix(self, mode: str) -> str:
        """Get suggested physical prefix for this bus type and mode."""
        prefixes = SUGGESTED_PREFIXES.get(self.key, {})
        return prefixes.get(mode, f"{mode[:1]}_{self.key.lower()}_")


class BusLibrary:
    """
    Access predefined bus definitions.

    Loads bus definitions from YAML and provides query methods.
    """

    def __init__(self, definitions: Dict[str, BusDefinition]):
        """Initialize with pre-loaded definitions."""
        self._definitions = definitions

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "BusLibrary":
        """
        Load bus definitions from YAML file.

        Args:
            path: Path to bus_definitions.yml (defaults to ipcraft-spec/common/)

        Returns:
            BusLibrary instance
        """
        path = path or DEFAULT_BUS_DEFS_PATH

        if not path.exists():
            raise FileNotFoundError(f"Bus definitions file not found: {path}")

        with open(path, "r") as f:
            raw_data = yaml.safe_load(f) or {}

        definitions = {}
        for key, data in raw_data.items():
            bus_type_data = data.get("busType", {})
            bus_type = VLNV(
                vendor=bus_type_data.get("vendor", ""),
                library=bus_type_data.get("library", ""),
                name=bus_type_data.get("name", key.lower()),
                version=bus_type_data.get("version", "1.0"),
            )

            ports = []
            for port_data in data.get("ports", []):
                ports.append(
                    PortDefinition(
                        name=port_data.get("name", ""),
                        direction=port_data.get("direction"),
                        width=port_data.get("width"),
                        presence=port_data.get("presence", "required"),
                    )
                )

            definitions[key] = BusDefinition(
                key=key,
                bus_type=bus_type,
                ports=ports,
            )

        return cls(definitions)

    def list_bus_types(self) -> List[str]:
        """
        Get list of available bus type keys.

        Returns:
            List of bus type names (e.g., ['AXI4L', 'AXIS', 'AVALON_MM', 'AVALON_ST'])
        """
        return list(self._definitions.keys())

    def get_bus_definition(self, bus_type: str) -> Optional[BusDefinition]:
        """
        Get full bus definition by key.

        Args:
            bus_type: Bus type key (e.g., 'AXI4L')

        Returns:
            BusDefinition or None if not found
        """
        return self._definitions.get(bus_type)

    def get_bus_info(self, bus_type: str, include_ports: bool = False) -> Optional[Dict[str, Any]]:
        """
        Get bus information as dictionary (for JSON serialization).

        Args:
            bus_type: Bus type key
            include_ports: If True, include full port definitions

        Returns:
            Dictionary with bus info or None
        """
        defn = self.get_bus_definition(bus_type)
        if not defn:
            return None

        info = {
            "key": defn.key,
            "vlnv": (
                f"{defn.bus_type.vendor}/{defn.bus_type.library}/{defn.bus_type.name}/{defn.bus_type.version}"
            ),
            "vendor": defn.bus_type.vendor,
            "library": defn.bus_type.library,
            "name": defn.bus_type.name,
            "version": defn.bus_type.version,
            "requiredPorts": len(defn.required_ports),
            "optionalPorts": len(defn.optional_ports),
            "suggestedPrefixes": SUGGESTED_PREFIXES.get(defn.key, {}),
        }

        if include_ports:
            info["ports"] = [
                {
                    "name": p.name,
                    "direction": p.direction,
                    "width": p.width,
                    "presence": p.presence,
                }
                for p in defn.ports
            ]

        return info

    def get_all_bus_info(self, include_ports: bool = False) -> List[Dict[str, Any]]:
        """
        Get information for all bus types.

        Args:
            include_ports: If True, include full port definitions

        Returns:
            List of bus info dictionaries
        """
        return [
            self.get_bus_info(key, include_ports=include_ports) for key in self.list_bus_types()
        ]

    def get_bus_library_dict(self) -> Dict[str, Dict[str, Any]]:
        """
        Get the bus library in the format expected by the UI.

        Returns dict like: { "AXI4L": { "ports": [...] } }
        """
        result = {}
        for key in self.list_bus_types():
            defn = self.get_bus_definition(key)
            if defn:
                result[key] = {
                    "ports": [
                        {
                            "name": p.name,
                            "direction": p.direction,
                            "width": p.width,
                            "presence": p.presence,
                        }
                        for p in defn.ports
                    ]
                }
        return result

    def get_required_ports(self, bus_type: str) -> List[PortDefinition]:
        """Get required ports for a bus type."""
        defn = self.get_bus_definition(bus_type)
        return defn.required_ports if defn else []

    def get_optional_ports(self, bus_type: str) -> List[PortDefinition]:
        """Get optional ports for a bus type."""
        defn = self.get_bus_definition(bus_type)
        return defn.optional_ports if defn else []


# Singleton instance for convenience
_library_instance: Optional[BusLibrary] = None


def get_bus_library() -> BusLibrary:
    """Get or create the global BusLibrary instance."""
    global _library_instance
    if _library_instance is None:
        _library_instance = BusLibrary.load()
    return _library_instance
