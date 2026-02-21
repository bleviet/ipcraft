"""
Clock and reset definitions for IP cores.
"""

from typing import Any, Optional

from pydantic import Field, field_validator

from .base import Polarity
from .port import Port, PortDirection


class Clock(Port):
    """
    Clock definition for an IP core.

    Defines both logical (internal) and physical (port) names for clock signals.
    Inherits from Port, typically with width=1.
    """

    # Override direction to default to IN, but allow others
    direction: PortDirection = Field(
        default=PortDirection.IN, description="Port direction (typically 'in')"
    )
    frequency: Optional[str] = Field(
        default=None, description="Clock frequency (e.g., '100MHz')"
    )

    @property
    def frequency_hz(self) -> Optional[float]:
        """Parse frequency string to Hz (e.g., '100MHz' -> 100000000.0)."""
        if not self.frequency:
            return None

        freq_str = self.frequency.strip().upper()
        multipliers = {
            "HZ": 1,
            "KHZ": 1e3,
            "MHZ": 1e6,
            "GHZ": 1e9,
        }

        for suffix, mult in multipliers.items():
            if freq_str.endswith(suffix):
                try:
                    value = float(freq_str[: -len(suffix)])
                    return value * mult
                except ValueError:
                    return None
        return None


class Reset(Port):
    """
    Reset definition for an IP core.

    Defines both logical (internal) and physical (port) names for reset signals,
    including polarity information.
    Inherits from Port, typically with width=1.
    """

    # Override direction to default to IN
    direction: PortDirection = Field(
        default=PortDirection.IN, description="Port direction (typically 'in')"
    )
    polarity: Polarity = Field(
        default=Polarity.ACTIVE_HIGH,
        description="Reset polarity (activeHigh or activeLow)",
    )

    @field_validator("polarity", mode="before")
    @classmethod
    def normalize_polarity(cls, v: Any) -> Any:
        """Support case-insensitive polarity strings."""
        if isinstance(v, str):
            v_lower = v.lower().replace("_", "")
            if v_lower == "activehigh":
                return Polarity.ACTIVE_HIGH
            if v_lower == "activelow":
                return Polarity.ACTIVE_LOW
        return v

    @property
    def is_active_low(self) -> bool:
        """Check if reset is active low."""
        return self.polarity == Polarity.ACTIVE_LOW

    @property
    def is_active_high(self) -> bool:
        """Check if reset is active high."""
        return self.polarity == Polarity.ACTIVE_HIGH
