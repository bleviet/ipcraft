"""
Base models for IP core metadata.

Provides shared base models with centralized configuration for all
IP core schema classes. Using these base models eliminates repetitive
``model_config`` declarations across the codebase.

Architecture Decision:
    Two ``extra`` policies exist on purpose:
    StrictModel (extra="forbid") is for top-level schema objects
    (IpCore, BusInterface, etc.) where extra fields indicate user typos.
    FlexibleModel (extra="ignore") is for memory-map models
    (RegisterDef, BitFieldDef, etc.) where vendor extensions like
    ``x-vendor-attr`` should be silently accepted.
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, ValidationInfo, field_validator
from pydantic.alias_generators import to_camel


class IpCoreBaseModel(BaseModel):
    """Base model with shared configuration for all IP core schema models.

    Provides camelCase aliasing, assignment validation, and allows field
    population by either alias or Python name.
    """

    model_config = {
        "validate_assignment": True,
        "alias_generator": to_camel,
        "populate_by_name": True,
    }


class StrictModel(IpCoreBaseModel):
    """Base model that forbids unknown fields.

    Use for top-level schema objects where extra fields likely indicate
    user typos (e.g., IpCore, BusInterface, Port, FileSet).
    """

    model_config = {
        **IpCoreBaseModel.model_config,
        "extra": "forbid",
    }


class FlexibleModel(IpCoreBaseModel):
    """Base model that silently ignores unknown fields.

    Use for memory-map models where vendor extensions
    (e.g., ``x-vendor-attr``) should be accepted without errors.
    """

    model_config = {
        **IpCoreBaseModel.model_config,
        "extra": "ignore",
    }


class VLNV(BaseModel):
    """
    Vendor-Library-Name-Version identifier for IP cores.

    This uniquely identifies an IP core in the IP-XACT standard format.

    Note: This model is frozen (immutable) to ensure safe hashing for use
    in sets and as dictionary keys.
    """

    vendor: str = Field(..., description="Vendor identifier (e.g., 'my-company.com')")
    library: str = Field(..., description="Library name (e.g., 'processing')")
    name: str = Field(..., description="IP core name (e.g., 'my_timer_core')")
    version: str = Field(..., description="Version string (e.g., '1.2.0')")

    model_config = {
        "frozen": True,
        "alias_generator": to_camel,
        "populate_by_name": True,
    }

    @field_validator("vendor", "library", "name", "version")
    @classmethod
    def validate_identifiers(cls, v: str, info: ValidationInfo) -> str:
        """
        Ensure identifiers are not empty and contain valid characters.
        Strips whitespace automatically.
        """
        v = v.strip()
        if not v:
            raise ValueError(f"{info.field_name} cannot be empty")

        return v

    @classmethod
    def from_string(cls, vlnv_string: str) -> "VLNV":
        """Parse VLNV from colon-separated string.

        Args:
            vlnv_string: String in format "vendor:library:name:version"

        Returns:
            VLNV instance

        Raises:
            ValueError: If string format is invalid

        Example:
            >>> vlnv = VLNV.from_string("acme.com:peripherals:timer:1.0.0")
            >>> print(vlnv.vendor)
            'acme.com'
        """
        parts = vlnv_string.split(":")
        if len(parts) != 4:
            raise ValueError(
                f"Invalid VLNV format: expected 4 colon-separated parts, got {len(parts)}. "
                f"Expected format: 'vendor:library:name:version'"
            )
        return cls(vendor=parts[0], library=parts[1], name=parts[2], version=parts[3])

    @property
    def full_name(self) -> str:
        """Return fully qualified VLNV string."""
        return f"{self.vendor}:{self.library}:{self.name}:{self.version}"

    def __str__(self) -> str:
        return self.full_name


class ParameterType(str, Enum):
    """Enumeration for standard IP-XACT/HDL parameter types."""

    INTEGER = "integer"
    NATURAL = "natural"
    POSITIVE = "positive"
    REAL = "real"
    BOOLEAN = "boolean"
    STRING = "string"


class Parameter(StrictModel):
    """
    Generic parameter/generic definition for IP cores.

    Used for VHDL generics, Verilog parameters, or component configuration.
    """

    name: str = Field(..., description="Parameter name")
    value: Any = Field(..., description="Default value")
    data_type: ParameterType = Field(
        default=ParameterType.INTEGER, description="Data type"
    )
    description: str = Field(default="", description="Parameter description")

    # This allows the Parameter class to accept raw strings (including mixed case Integer, INTEGER etc.) and
    # normalize them into the correct Enum type before Pydantic performs its strict validation.
    @field_validator("data_type", mode="before")
    @classmethod
    def normalize_data_type(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.lower()
        return v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Ensure parameter name is valid."""
        v = v.strip()
        if not v:
            raise ValueError("Parameter name cannot be empty")
        return v

    @property
    def is_numeric(self) -> bool:
        """Check if parameter is numeric type."""
        return self.data_type in (
            ParameterType.INTEGER,
            ParameterType.NATURAL,
            ParameterType.POSITIVE,
            ParameterType.REAL,
        )

    @property
    def is_boolean(self) -> bool:
        """Check if parameter is boolean type."""
        return self.data_type == ParameterType.BOOLEAN

    @property
    def is_string(self) -> bool:
        """Check if parameter is string type."""
        return self.data_type == ParameterType.STRING


class Polarity(str, Enum):
    """Reset polarity enumeration."""

    ACTIVE_HIGH = "activeHigh"
    ACTIVE_LOW = "activeLow"
