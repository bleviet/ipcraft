"""
Memory map definitions for IP cores.

These are Pydantic models for YAML parsing and validation.
For runtime register access, use ipcraft.runtime.register classes.

Naming convention:
- Classes here use *Def suffix (e.g., RegisterDef, BitFieldDef) to indicate
    they are definitions/schemas, not runtime objects.
- Use to_runtime_*() methods to convert to runtime objects.
"""

from enum import Enum
from functools import cached_property
from typing import TYPE_CHECKING, Any, Dict, ForwardRef, List, Optional, Union

from pydantic import Field, computed_field, field_validator, model_validator

from ipcraft.utils import parse_bit_range

from .base import FlexibleModel, StrictModel

if TYPE_CHECKING:
    from ipcraft.runtime.register import AbstractBusInterface
    from ipcraft.runtime.register import Register as RuntimeRegister

# Forward reference for recursive register definition
RegisterDef = ForwardRef("RegisterDef")


class AccessType(str, Enum):
    """Register/field access types for YAML parsing."""

    READ_ONLY = "read-only"
    WRITE_ONLY = "write-only"
    READ_WRITE = "read-write"
    WRITE_1_TO_CLEAR = "write-1-to-clear"
    READ_WRITE_1_TO_CLEAR = "read-write-1-to-clear"

    @classmethod
    def normalize(cls, value: str) -> "AccessType":
        """Normalize various access type representations."""
        normalized_map = {
            "ro": cls.READ_ONLY,
            "read-only": cls.READ_ONLY,
            "readonly": cls.READ_ONLY,
            "wo": cls.WRITE_ONLY,
            "write-only": cls.WRITE_ONLY,
            "writeonly": cls.WRITE_ONLY,
            "rw": cls.READ_WRITE,
            "read-write": cls.READ_WRITE,
            "readwrite": cls.READ_WRITE,
            "rw1c": cls.WRITE_1_TO_CLEAR,
            "write-1-to-clear": cls.WRITE_1_TO_CLEAR,
            "write1toclear": cls.WRITE_1_TO_CLEAR,
        }
        return normalized_map.get(value.lower(), cls.READ_WRITE)

    @classmethod
    def from_string(cls, value: str) -> "AccessType":
        """Parse access value from enum value/name or alias string."""
        if isinstance(value, cls):
            return value
        try:
            return cls(value)
        except ValueError:
            return cls.normalize(value)

    def to_runtime_access(self) -> str:
        """Convert to runtime AccessType string value (ro, wo, rw, rw1c).

        Raises:
            ValueError: If the access type has no known runtime mapping.
        """
        mapping = {
            self.READ_ONLY: "ro",
            self.WRITE_ONLY: "wo",
            self.READ_WRITE: "rw",
            self.WRITE_1_TO_CLEAR: "rw1c",
            self.READ_WRITE_1_TO_CLEAR: "rw1c",
        }
        result = mapping.get(self)
        if result is None:
            raise ValueError(f"No runtime mapping for access type '{self.value}'")
        return result


class BitFieldDef(FlexibleModel):
    """
    Bit field definition within a register (Pydantic model for YAML parsing).

    Represents a named range of bits with specific access semantics.
    """

    name: str = Field(..., description="Bit field name")
    bit_offset: Optional[int] = Field(
        default=None, alias="offset", description="Starting bit position (LSB = 0)", ge=0
    )
    bit_width: Optional[int] = Field(
        default=None, alias="width", description="Number of bits", ge=1
    )
    bits: Optional[str] = Field(default=None, description="Bit range string e.g. [7:0]")
    access: AccessType = Field(default=AccessType.READ_WRITE, description="Access type")
    reset_value: Optional[int] = Field(default=None, description="Reset/default value")
    description: str = Field(default="", description="Field description")
    enumerated_values: Optional[Dict[int, str]] = Field(
        default=None, description="Enumeration mapping {value: name}"
    )

    @model_validator(mode="before")
    @classmethod
    def parse_bits_notation(cls, data: Any) -> Any:
        """Parse bits notation (e.g. '[7:4]') into bit_offset and bit_width.

        Allows YAML files to use `bits: "[7:4]"` shorthand. The notation
        is converted to explicit `bit_offset` and `bit_width` values.
        """
        if not isinstance(data, dict):
            return data

        # Support aliases, camelCase, and snake_case field names
        bits_val = data.get("bits")
        has_offset = "bit_offset" in data or "bitOffset" in data or "offset" in data
        has_width = "bit_width" in data or "bitWidth" in data or "width" in data

        if bits_val and not (has_offset and has_width):
            offset, width = parse_bit_range(str(bits_val))
            data["bit_offset"] = offset
            data["bit_width"] = width

        return data

    @field_validator("access", mode="before")
    @classmethod
    def normalize_access(cls, v: Any) -> Any:
        """Normalize access type using AccessType.normalize."""
        if isinstance(v, str):
            return AccessType.from_string(v)
        return v

    def to_runtime_bitfield(self):
        """Convert to a runtime BitField object from core.register."""
        from ipcraft.runtime.register import BitField as RuntimeBitField

        # Resolve bit_offset and bit_width from bits string if needed
        offset = self.bit_offset
        width = self.bit_width

        if offset is None and self.bits:
            offset, width = parse_bit_range(self.bits)

        # Default values if still None
        if offset is None:
            offset = 0
        if width is None:
            width = 1

        return RuntimeBitField(
            name=self.name,
            offset=offset,
            width=width,
            access=self.access.to_runtime_access(),
            description=self.description,
            reset_value=self.reset_value,
        )

    @property
    def bit_range(self) -> str:
        """Get bit range as string (e.g. [7:0])."""
        if self.bits:
            return self.bits

        # Need to resolve offset/width if not set but computed?
        # The fields bit_offset and bit_width are Optional in model.
        # But usually populated or computed via to_runtime.
        # For display, we fall back to defaults or try to compute.

        offset = self.bit_offset or 0
        width = self.bit_width or 1

        msb = offset + width - 1
        lsb = offset
        if msb == lsb:
            return f"[{lsb}]"
        return f"[{msb}:{lsb}]"


class RegisterDef(FlexibleModel):
    """
    Register definition within a memory map (Pydantic model for YAML parsing).

    Represents a memory-mapped register with bit fields.
    """

    name: str = Field(..., description="Register name")
    address_offset: Optional[int] = Field(
        default=None, alias="offset", description="Offset from address block base", ge=0
    )
    size: int = Field(default=32, description="Register width in bits")
    access: AccessType = Field(default=AccessType.READ_WRITE, description="Default access type")
    reset_value: Optional[int] = Field(default=0, description="Reset value for entire register")
    description: str = Field(default="", description="Register description")
    fields: List[BitFieldDef] = Field(default_factory=list, description="Bit fields")

    # Recursion support for register groups/arrays
    registers: List["RegisterDef"] = Field(
        default_factory=list, description="Child registers (for groups)"
    )
    count: Optional[int] = Field(default=1, description="Array replication count")
    stride: Optional[int] = Field(default=None, description="Array replication stride")

    @field_validator("access", mode="before")
    @classmethod
    def normalize_access(cls, v: Any) -> Any:
        """Normalize access type using AccessType.normalize."""
        if isinstance(v, str):
            return AccessType.from_string(v)
        return v

    def to_runtime_register(
        self,
        bus: "AbstractBusInterface",
        base_offset: int = 0,
        register_class: Any = None,
    ):
        """
        Convert to a runtime Register object from core.register.

        Args:
            bus: Bus interface for hardware communication
            base_offset: Base address offset to add to register offset
            register_class: Class to use for register creation (Sync/Async).
                            Defaults to ipcraft.runtime.register.Register

        Returns:
            Runtime Register object
        """
        from ipcraft.runtime.register import Register as RuntimeRegister

        if register_class is None:
            register_class = RuntimeRegister

        offset = (self.address_offset or 0) + base_offset
        runtime_fields = [f.to_runtime_bitfield() for f in self.fields]

        return register_class(
            name=self.name,
            offset=offset,
            bus=bus,
            fields=runtime_fields,
            description=self.description,
        )

    @property
    def hex_address(self) -> str:
        """Get relative address as hex string."""
        return hex(self.address_offset or 0)


class RegisterArrayDef(FlexibleModel):
    """
    Array of registers definition with automatic address calculation (Pydantic model).

    Used for repeated register structures (e.g., per-channel registers).
    """

    name: str = Field(..., description="Base name for array")
    base_address: int = Field(..., description="Starting address", ge=0)
    count: int = Field(..., description="Number of instances", ge=1)
    stride: int = Field(..., description="Address increment between instances", ge=4)
    template: RegisterDef = Field(..., description="Register template for each instance")
    description: str = Field(default="", description="Array description")

    @field_validator("stride")
    @classmethod
    def validate_stride(cls, v: int) -> int:
        """Ensure stride is aligned."""
        if v < 4 or v % 4 != 0:
            raise ValueError("Stride must be at least 4 and word-aligned")
        return v

    def get_register_address(self, index: int) -> int:
        """Get address for specific array instance."""
        if index < 0 or index >= self.count:
            raise IndexError(f"Register array index {index} out of range [0, {self.count})")
        return self.base_address + (index * self.stride)

    def get_register_name(self, index: int) -> str:
        """Get name for specific array instance."""
        return f"{self.name}{index}"

    def to_runtime_array(self, bus: "AbstractBusInterface", register_class: Any = None):
        """Convert to a runtime RegisterArrayAccessor from core.register."""
        from ipcraft.runtime.register import Register as RuntimeRegister
        from ipcraft.runtime.register import RegisterArrayAccessor

        if register_class is None:
            register_class = RuntimeRegister

        runtime_fields = [f.to_runtime_bitfield() for f in self.template.fields]

        return RegisterArrayAccessor(
            name=self.name,
            base_offset=self.base_address,
            count=self.count,
            stride=self.stride,
            field_template=runtime_fields,
            bus_interface=bus,
            register_class=register_class,
        )

    @computed_field
    @property
    def total_size(self) -> int:
        """Get total size occupied by array."""
        return self.count * self.stride


class BlockUsage(str, Enum):
    """Address block usage type."""

    REGISTERS = "register"
    MEMORY = "memory"
    RESERVED = "reserved"


class AddressBlock(FlexibleModel):
    """
    Contiguous address block within a memory map (Pydantic model).

    Can contain registers, memory, or reserved space.
    """

    name: str = Field(..., description="Block name")
    base_address: Optional[int] = Field(default=0, description="Block starting address", ge=0)
    range: Optional[Union[int, str]] = Field(
        default=None, description="Block size (bytes or '4K', '1M', etc.)"
    )
    usage: BlockUsage = Field(default=BlockUsage.REGISTERS, description="Block usage type")
    access: AccessType = Field(default=AccessType.READ_WRITE, description="Default access")
    description: str = Field(default="", description="Block description")

    default_reg_width: int = Field(default=32, description="Default register width")

    # Content
    registers: List[RegisterDef] = Field(default_factory=list, description="Registers in block")

    @computed_field
    @cached_property
    def end_address(self) -> int:
        """Calculate end address of the block."""
        range_val = self.range
        if isinstance(range_val, str):
            # Simple parsing for common suffixes
            suffix = range_val[-1].upper()
            if suffix == "K":
                range_val = int(range_val[:-1]) * 1024
            elif suffix == "M":
                range_val = int(range_val[:-1]) * 1024 * 1024
            elif suffix == "G":
                range_val = int(range_val[:-1]) * 1024 * 1024 * 1024
            else:
                range_val = int(range_val)

        # Default to 0 size if None (though parser provides default)
        size = range_val if range_val is not None else 0
        return self.base_address + size

    def contains_address(self, address: int) -> bool:
        """Check if address is within this block."""
        return self.base_address <= address < self.end_address

    @property
    def hex_range(self) -> str:
        """Get range as hex string."""
        return f"[{hex(self.base_address)} : {hex(self.end_address)}]"


# Update forward refs
RegisterDef.model_rebuild()
AddressBlock.model_rebuild()


class MemoryMapReference(StrictModel):
    """Reference to a memory map by name."""

    name: str = Field(..., description="Memory map name")


class MemoryMap(StrictModel):
    """
    Complete memory map for an IP core (Pydantic model).

    Organizes registers into address blocks with validation.
    """

    name: str = Field(..., description="Memory map name")
    description: str = Field(default="", description="Memory map description")
    address_blocks: List[AddressBlock] = Field(default_factory=list, description="Address blocks")

    def model_post_init(self, __context: Any) -> None:
        """Validate memory map after initialization."""
        # Check for overlapping address blocks
        for i, block1 in enumerate(self.address_blocks):
            for block2 in self.address_blocks[i + 1 :]:
                if self._blocks_overlap(block1, block2):
                    raise ValueError(
                        f"Overlapping address blocks: '{block1.name}' {block1.hex_range} "
                        f"and '{block2.name}' {block2.hex_range}"
                    )

    @staticmethod
    def _blocks_overlap(block1: AddressBlock, block2: AddressBlock) -> bool:
        """Check if two address blocks overlap."""
        # If range is missing (validation pending or failed), skip check to avoid crash
        if block1.range is None or block2.range is None:
            return False

        return not (
            block1.end_address <= block2.base_address or block2.end_address <= block1.base_address
        )

    def get_block_at_address(self, address: int) -> Optional[AddressBlock]:
        """Find address block containing given address."""
        for block in self.address_blocks:
            if block.contains_address(address):
                return block
        return None

    def get_register_by_name(self, name: str) -> Optional[RegisterDef]:
        """Find register by name across all blocks."""
        for block in self.address_blocks:
            for reg in block.registers:
                if reg.name == name:
                    return reg
        return None

    @computed_field
    @property
    def total_registers(self) -> int:
        """Count total registers across all blocks."""
        return sum(len(block.registers) for block in self.address_blocks)

    @computed_field
    @property
    def total_address_space(self) -> int:
        """Get total address space covered by all blocks."""
        if not self.address_blocks:
            return 0
        max_end = max(block.end_address for block in self.address_blocks)
        min_start = min(block.base_address for block in self.address_blocks)
        return max_end - min_start
