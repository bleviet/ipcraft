"""
Bus interface definitions for IP cores.
"""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import Field, field_validator

from .base import VLNV, StrictModel


class BusType(VLNV):
    """
    Bus type identifier from bus library.

    References a standardized bus definition (AXI4L, AXIS, AVALON_MM, etc.).
    Inherits validation, immutability, and factory methods from VLNV.
    """

    # Override fields to provide context-specific descriptions
    vendor: str = Field(..., description="Bus standard vendor")
    library: str = Field(..., description="Bus library")
    name: str = Field(..., description="Bus type name")
    version: str = Field(..., description="Bus version")


class BusInterfaceMode(str, Enum):
    """Enumeration for bus interface modes."""

    MASTER = "master"
    SLAVE = "slave"
    SOURCE = "source"
    SINK = "sink"


class ArrayConfig(StrictModel):
    """
    Configuration for array of bus interfaces.

    Enables creation of multiple interface instances (e.g., 4 AXI Stream channels).
    """

    count: int = Field(..., description="Number of instances", ge=1)
    index_start: int = Field(default=0, description="Starting index")
    naming_pattern: str = Field(
        ...,
        description="Naming pattern with {index} placeholder (e.g., 'M_AXIS_CH{index}_EVENTS')",
    )
    physical_prefix_pattern: str = Field(
        ..., description="Physical prefix pattern with {index} placeholder"
    )

    def get_instance_name(self, index: int) -> str:
        """Get logical name for specific instance."""
        return self.naming_pattern.format(index=index)

    def get_instance_prefix(self, index: int) -> str:
        """Get physical prefix for specific instance."""
        return self.physical_prefix_pattern.format(index=index)

    @property
    def indices(self) -> List[int]:
        """Get list of all instance indices."""
        return list(range(self.index_start, self.index_start + self.count))


class BusInterface(StrictModel):
    """
    Bus interface definition for an IP core.

    Represents a standardized bus connection (AXI, Avalon, etc.) with
    optional width overrides, clock/reset associations, and array support.
    """

    name: str = Field(..., description="Logical interface name")
    type: str = Field(..., description="Bus type from library (e.g., 'AXI4L', 'AXIS')")
    mode: BusInterfaceMode = Field(
        ..., description="Interface mode: 'master' or 'slave'"
    )

    # Port mapping
    physical_prefix: str = Field(
        ..., description="Prefix for physical port names (e.g., 's_axi_')"
    )

    # Clock/Reset association
    associated_clock: Optional[str] = Field(
        default=None, description="Logical clock name this interface uses"
    )
    associated_reset: Optional[str] = Field(
        default=None, description="Logical reset name this interface uses"
    )

    # Memory map reference (for register interfaces)
    memory_map_ref: Optional[str] = Field(
        default=None, description="Memory map name for register access"
    )

    # Optional port usage
    use_optional_ports: List[str] = Field(
        default_factory=list, description="List of optional ports to include"
    )

    # Width overrides
    port_width_overrides: Dict[str, int] = Field(
        default_factory=dict, description="Port width overrides {port_name: width}"
    )

    @field_validator("port_width_overrides")
    @classmethod
    def validate_port_width_overrides(cls, v: Dict[str, int]) -> Dict[str, int]:
        """Ensure overridden widths are positive."""
        for name, width in v.items():
            if width <= 0:
                raise ValueError(f"Port width override for '{name}' must be positive")
        return v

    # Array configuration
    array: Optional[ArrayConfig] = Field(
        default=None, description="Array configuration for multiple instances"
    )

    # Description
    description: str = Field(default="", description="Interface description")

    @field_validator("mode", mode="before")
    @classmethod
    def normalize_mode(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.lower()
        return v

    @property
    def is_master(self) -> bool:
        """Check if interface is master/source."""
        return self.mode in (BusInterfaceMode.MASTER, BusInterfaceMode.SOURCE)

    @property
    def is_slave(self) -> bool:
        """Check if interface is slave/sink."""
        return self.mode in (BusInterfaceMode.SLAVE, BusInterfaceMode.SINK)

    @property
    def is_array(self) -> bool:
        """Check if interface is an array."""
        return self.array is not None

    @property
    def instance_count(self) -> int:
        """Get number of interface instances (1 if not array)."""
        return self.array.count if self.array else 1

    def get_port_width(self, port_name: str, default_width: int) -> int:
        """
        Get effective port width with override support.

        Args:
            port_name: Logical port name
            default_width: Default width from bus definition

        Returns:
            Effective width (override if present, otherwise default)
        """
        return self.port_width_overrides.get(port_name, default_width)
