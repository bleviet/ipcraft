"""
Port definitions for IP cores.
"""

from enum import Enum
from typing import Any, Union

from pydantic import Field, field_validator

from .base import StrictModel


class PortDirection(str, Enum):
    """Port direction enumeration."""

    IN = "in"
    OUT = "out"
    INOUT = "inout"

    @classmethod
    def from_string(cls, value: str) -> "PortDirection":
        """Normalize common direction aliases into ``PortDirection``."""
        normalized = value.lower().strip()
        mapping = {
            "in": cls.IN,
            "input": cls.IN,
            "out": cls.OUT,
            "output": cls.OUT,
            "buffer": cls.OUT,
            "inout": cls.INOUT,
            "linkage": cls.IN,
        }
        return mapping.get(normalized, cls.IN)


class Port(StrictModel):
    """
    Generic port definition for IP cores.

    Used for data and control ports that are not part of clock, reset, or bus interfaces.
    """

    name: str = Field(..., description="Physical port name (HDL)")
    logical_name: str = Field(
        default="", description="Standard logical name for association"
    )
    direction: PortDirection = Field(..., description="Port direction")
    width: Union[int, str] = Field(
        default=1, description="Port width in bits or parameter name"
    )
    type: str = Field(
        default="std_logic", description="VHDL type (e.g. std_logic, std_logic_vector)"
    )
    description: str = Field(default="", description="Port description")

    @field_validator("direction", mode="before")
    @classmethod
    def normalize_direction(cls, v: Any) -> Any:
        """Validate and normalize port direction."""
        if isinstance(v, str):
            return PortDirection.from_string(v).value
        return v

    @field_validator("width")
    @classmethod
    def validate_width(cls, v: Union[int, str]) -> Union[int, str]:
        """Ensure port width is positive or a valid parameter reference."""
        if isinstance(v, int):
            if v <= 0:
                raise ValueError("Port width must be positive")
        elif isinstance(v, str):
            # Allow string for parameter references (e.g., "NUM_LEDS")
            if not v or not v.strip():
                raise ValueError("Port width parameter reference cannot be empty")
        return v

    @property
    def is_input(self) -> bool:
        """Check if port is input."""
        return self.direction == PortDirection.IN

    @property
    def is_output(self) -> bool:
        """Check if port is output."""
        return self.direction == PortDirection.OUT

    @property
    def is_bidirectional(self) -> bool:
        """Check if port is bidirectional."""
        return self.direction == PortDirection.INOUT

    @property
    def is_vector(self) -> bool:
        """Check if port is a vector (multi-bit)."""
        if isinstance(self.width, str):
            return True  # Parameter-based widths are assumed to be vectors
        return self.width > 1

    @property
    def range_string(self) -> str:
        """Get VHDL-style range string (e.g., '7 downto 0')."""
        if isinstance(self.width, str):
            # Parameter-based width
            return f"{self.width} - 1 downto 0"
        if self.width == 1:
            return ""
        return f"{self.width - 1} downto 0"
