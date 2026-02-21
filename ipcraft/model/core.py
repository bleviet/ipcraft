"""Main IP Core model - the canonical representation."""

from typing import List, Optional, Sequence, TypeVar

from pydantic import Field, field_validator

from .base import VLNV, Parameter, StrictModel
from .bus import BusInterface
from .clock_reset import Clock, Reset
from .fileset import FileSet
from .memory_map import MemoryMap
from .port import Port

NamedItem = TypeVar("NamedItem")


class IpCore(StrictModel):
    """
    Complete IP core definition - the single source of truth.

    This is the canonical data model that all parsers produce and
    all generators consume. It includes:
    - Metadata (VLNV, description)
    - Interface definitions (clocks, resets, ports, buses)
    - Memory maps (registers, bit fields)
    - Files (HDL sources, constraints, documentation)
    - Parameters/generics
    """

    # Metadata
    api_version: str = Field(..., description="Schema version (e.g., 'my-ip-schema/v2.3')")
    vlnv: VLNV = Field(..., description="Unique identifier")
    description: str = Field(default="", description="IP core description")

    # Interface definitions
    clocks: List[Clock] = Field(default_factory=list, description="Clock definitions")
    resets: List[Reset] = Field(default_factory=list, description="Reset definitions")
    ports: List[Port] = Field(default_factory=list, description="Data/control ports")
    bus_interfaces: List[BusInterface] = Field(
        default_factory=list, description="Bus interface definitions"
    )

    # Memory maps
    memory_maps: List[MemoryMap] = Field(default_factory=list, description="Memory maps")

    # Files
    file_sets: List[FileSet] = Field(default_factory=list, description="File sets")

    # Parameters
    parameters: List[Parameter] = Field(default_factory=list, description="Generics/parameters")

    # Bus library reference
    use_bus_library: Optional[str] = Field(
        default=None, description="Path to bus definitions library"
    )

    @field_validator("api_version")
    @classmethod
    def validate_api_version(cls, v: str) -> str:
        """Ensure API version is not empty."""
        if not v or not v.strip():
            raise ValueError("API version cannot be empty")
        return v.strip()

    # --- Convenience accessors ---

    @staticmethod
    def _find_by_name(items: Sequence[NamedItem], name: str) -> Optional[NamedItem]:
        """Return the first item with a matching ``name`` attribute."""
        return next((item for item in items if getattr(item, "name", None) == name), None)

    def get_clock(self, name: str) -> Optional[Clock]:
        """Get clock by logical name."""
        return self._find_by_name(self.clocks, name)

    def get_reset(self, name: str) -> Optional[Reset]:
        """Get reset by logical name."""
        return self._find_by_name(self.resets, name)

    def get_port(self, name: str) -> Optional[Port]:
        """Get port by logical name."""
        return self._find_by_name(self.ports, name)

    def get_bus_interface(self, name: str) -> Optional[BusInterface]:
        """Get bus interface by name."""
        return self._find_by_name(self.bus_interfaces, name)

    def get_memory_map(self, name: str) -> Optional[MemoryMap]:
        """Get memory map by name."""
        return self._find_by_name(self.memory_maps, name)

    def get_parameter(self, name: str) -> Optional[Parameter]:
        """Get parameter by name."""
        return self._find_by_name(self.parameters, name)

    def get_file_set(self, name: str) -> Optional[FileSet]:
        """Get file set by name."""
        return self._find_by_name(self.file_sets, name)

    # --- Computed properties ---

    @property
    def master_bus_interfaces(self) -> List[BusInterface]:
        """Get all master/source bus interfaces."""
        return [bus for bus in self.bus_interfaces if bus.is_master]

    @property
    def slave_bus_interfaces(self) -> List[BusInterface]:
        """Get all slave/sink bus interfaces."""
        return [bus for bus in self.bus_interfaces if bus.is_slave]

    @property
    def total_registers(self) -> int:
        """Count total registers across all memory maps."""
        return sum(mm.total_registers for mm in self.memory_maps)

    @property
    def hdl_file_sets(self) -> List[FileSet]:
        """Get file sets containing HDL files."""
        return [fs for fs in self.file_sets if fs.hdl_files]

    @property
    def has_memory_maps(self) -> bool:
        """Check if IP core has any memory maps."""
        return len(self.memory_maps) > 0

    @property
    def has_bus_interfaces(self) -> bool:
        """Check if IP core has any bus interfaces."""
        return len(self.bus_interfaces) > 0

    # --- Reference validation ---

    def validate_references(self) -> List[str]:
        """
        Validate all internal references.

        Returns list of validation error messages (empty if all valid).
        """
        errors = []

        # Check bus interface clock/reset references
        for bus in self.bus_interfaces:
            if bus.associated_clock:
                if not self.get_clock(bus.associated_clock):
                    errors.append(
                        f"Bus interface '{bus.name}' references unknown clock '{bus.associated_clock}'"
                    )
            if bus.associated_reset:
                if not self.get_reset(bus.associated_reset):
                    errors.append(
                        f"Bus interface '{bus.name}' references unknown reset '{bus.associated_reset}'"
                    )
            if bus.memory_map_ref:
                if not self.get_memory_map(bus.memory_map_ref):
                    errors.append(
                        f"Bus interface '{bus.name}' references unknown memory map '{bus.memory_map_ref}'"
                    )

        return errors
