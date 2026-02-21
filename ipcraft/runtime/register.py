"""
Generic Register and BitField Classes

This module provides generic, reusable register abstraction classes that can be
used by any IP core driver implementation. These classes handle bit-wise
operations, field validation, and access control.
"""

import logging
import warnings
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


class BusIOError(IOError):
    """Raised when a bus read/write operation fails.

    Bus interface implementations should raise this when
    a hardware read or write operation fails (timeout, NACK, etc.).
    """


class RuntimeAccessType(str, Enum):
    """
    Register field access types.
    """

    RO = "ro"  # Read-only
    WO = "wo"  # Write-only
    RW = "rw"  # Read-write
    RW1C = "rw1c"  # Read-write-1-to-clear


@dataclass
class BitField:
    """
    Represents a bit field within a register.
    """

    MAX_REGISTER_WIDTH: ClassVar[int] = 64

    name: str
    offset: int
    width: int
    access: str = "rw"
    description: str = ""
    reset_value: Optional[int] = None

    @property
    def mask(self) -> int:
        """Get the bit mask for this field within the register."""
        return ((1 << self.width) - 1) << self.offset

    @property
    def max_value(self) -> int:
        """Get the maximum value that can be stored in this field."""
        return (1 << self.width) - 1

    def extract_value(self, register_value: int) -> int:
        """Extract this field's value from a complete register value."""
        return (register_value >> self.offset) & ((1 << self.width) - 1)

    def __post_init__(self):
        """Validate bit field parameters."""
        valid_access = {at.value for at in RuntimeAccessType}
        # Check if access is string and valid
        acc_val = (
            self.access.value
            if isinstance(self.access, RuntimeAccessType)
            else self.access
        )
        if acc_val not in valid_access:
            raise ValueError(f"access must be one of {valid_access}")

        if self.width <= 0:
            raise ValueError(f"Bit field '{self.name}' width must be positive")
        if self.width > self.MAX_REGISTER_WIDTH:
            raise ValueError(
                f"Bit field '{self.name}' width cannot exceed "
                f"{self.MAX_REGISTER_WIDTH} bits"
            )
        if self.offset < 0:
            raise ValueError(f"Bit field '{self.name}' offset must be non-negative")
        if self.offset + self.width > self.MAX_REGISTER_WIDTH:
            raise ValueError(
                f"Bit field '{self.name}' extends beyond "
                f"{self.MAX_REGISTER_WIDTH}-bit register boundary"
            )

    def insert_value(self, register_value: int, field_value: int) -> int:
        """Insert this field's value into a complete register value."""
        # Clear the field bits
        cleared_value = register_value & ~self.mask
        # Insert the new field value
        return cleared_value | ((field_value << self.offset) & self.mask)


class AbstractBusInterface(ABC):
    """
    Abstract base class for synchronous bus interfaces.
    """

    @abstractmethod
    def read_word(self, address: int) -> int:
        """Read a 32-bit word from the specified address.

        Raises:
            BusIOError: If the bus operation fails.
        """
        pass

    @abstractmethod
    def write_word(self, address: int, data: int) -> None:
        """Write a 32-bit word to the specified address.

        Raises:
            BusIOError: If the bus operation fails.
        """
        pass


class AsyncBusInterface(ABC):
    """
    Abstract base class for asynchronous bus interfaces.
    """

    @abstractmethod
    async def read_word(self, address: int) -> int:
        """Read a 32-bit word from the specified address.

        Raises:
            BusIOError: If the bus operation fails.
        """
        pass

    @abstractmethod
    async def write_word(self, address: int, data: int) -> None:
        """Write a 32-bit word to the specified address.

        Raises:
            BusIOError: If the bus operation fails.
        """
        pass


class RegisterBoundField:
    """
    Helper class to provide access to a specific field within a register instance.
    """

    def __init__(self, register: "Register", field_def: BitField):
        self._register = register
        self._field_def = field_def

    def read(self) -> int:
        return self._register.read_field(self._field_def.name)

    def write(self, value: int) -> None:
        self._register.write_field(self._field_def.name, value)

    def __int__(self) -> int:
        return self.read()

    def __index__(self) -> int:
        return self.read()

    def __repr__(self) -> str:
        return str(self.read())


def _build_rmw_value(
    fields_dict: Dict[str, BitField], field_values: Dict[str, int], current_reg_val: int
) -> int:
    """
    Build register write value preserving non-target fields safely.

    This is a shared helper for both sync and async register implementations.

    Args:
        fields_dict: Dictionary mapping field names to BitField definitions
        field_values: Dictionary of field names to new values to write
        current_reg_val: Current register value (from read operation)

    Returns:
        Computed register value with updated fields and preserved RW fields

    Raises:
        ValueError: If a field value exceeds its width
    """
    reg_val_to_write = 0
    for f_name, field in fields_dict.items():
        if f_name in field_values:
            value = field_values[f_name]
            if value > field.max_value:
                raise ValueError(f"Value {value} exceeds field '{f_name}' width")
            reg_val_to_write = field.insert_value(reg_val_to_write, value)
            continue

        field_access = str(field.access)
        if field_access == RuntimeAccessType.RW.value:
            preserved = field.extract_value(current_reg_val)
            reg_val_to_write = field.insert_value(reg_val_to_write, preserved)

    return reg_val_to_write


class AsyncRegisterBoundField:
    """
    Helper class for async field access.
    """

    def __init__(self, register: "AsyncRegister", field_def: BitField):
        self._register = register
        self._field_def = field_def

    async def read(self) -> int:
        return await self._register.read_field(self._field_def.name)

    async def write(self, value: int) -> None:
        await self._register.write_field(self._field_def.name, value)


class _RegisterBase:
    """Shared initialization, validation, and helper logic for registers.

    This base class centralizes logic common to both synchronous and
    asynchronous register implementations, eliminating code duplication.
    """

    def __init__(
        self,
        name: str,
        offset: int,
        bus: Union[AbstractBusInterface, AsyncBusInterface],
        fields: List[BitField],
        description: str = "",
    ):
        self.name = name
        self.offset = offset
        self.description = description
        self._bus = bus
        self._fields: Dict[str, BitField] = {f.name: f for f in fields}

    @property
    def reset_value(self) -> int:
        """Calculate the register's reset value from its fields."""
        value = 0
        for field in self._fields.values():
            if field.reset_value is not None:
                value = field.insert_value(value, field.reset_value)
        return value

    def _validate_readable(self, field_name: str) -> BitField:
        """Validate that a field exists and is readable.

        Args:
            field_name: Name of the field to validate.

        Returns:
            The validated BitField object.

        Raises:
            KeyError: If field not found.
            ValueError: If field is write-only.
        """
        field = self._fields[field_name]
        if str(field.access) == RuntimeAccessType.WO.value:
            raise ValueError(f"Field '{field_name}' is write-only")
        return field

    def _validate_writable(self, field_name: str, value: int) -> BitField:
        """Validate that a field exists, is writable, and the value fits.

        Args:
            field_name: Name of the field to validate.
            value: Value to write.

        Returns:
            The validated BitField object.

        Raises:
            KeyError: If field not found.
            ValueError: If field is read-only or value exceeds width.
        """
        field = self._fields[field_name]
        if str(field.access) == RuntimeAccessType.RO.value:
            raise ValueError(f"Field '{field_name}' is read-only")
        if value > field.max_value:
            raise ValueError(f"Value {value} exceeds field '{field_name}' width")
        return field

    def get_field_names(self) -> List[str]:
        """Get all field names in this register."""
        return list(self._fields.keys())

    def get_field_info(self, name: str) -> BitField:
        """Get the BitField object for a given field name."""
        if name not in self._fields:
            raise KeyError(f"Field '{name}' not found in register '{self.name}'")
        return self._fields[name]


class Register(_RegisterBase):
    """
    Synchronous Register abstraction.
    """

    def __init__(
        self,
        name: str,
        offset: int,
        bus: AbstractBusInterface,
        fields: List[BitField],
        description: str = "",
    ):
        super().__init__(name, offset, bus, fields, description)
        # Create bound field attributes for easy access
        for field in fields:
            setattr(self, field.name, RegisterBoundField(self, field))

    def read(self) -> int:
        """Read the entire register value."""
        return self._bus.read_word(self.offset)

    def write(self, value: int) -> None:
        """Write the entire register value."""
        self._bus.write_word(self.offset, value & 0xFFFFFFFF)

    def read_field(self, field_name: str) -> int:
        """Read a specific bit field."""
        field = self._validate_readable(field_name)
        reg_val = self.read()
        return field.extract_value(reg_val)

    def write_field(self, field_name: str, value: int) -> None:
        """Write a specific bit field (Read-Modify-Write)."""
        self._validate_writable(field_name, value)

        current_reg_val = 0
        try:
            current_reg_val = self.read()
        except BusIOError as exc:
            logger.warning(
                "Failed to read register '%s' during RMW: %s; "
                "proceeding with current_value=0 — other fields may be corrupted",
                self.name,
                exc,
            )

        reg_val_to_write = _build_rmw_value(
            self._fields, {field_name: value}, current_reg_val
        )
        self.write(reg_val_to_write)

    def read_all_fields(self) -> Dict[str, int]:
        """Read all readable fields in the register."""
        reg_value = self.read()
        result = {}
        for field_name, field in self._fields.items():
            if field.access != "wo":
                result[field_name] = field.extract_value(reg_value)
        return result

    def write_multiple_fields(self, field_values: Dict[str, int]) -> None:
        """Write multiple fields in a single register operation."""
        current_reg_val = 0
        try:
            current_reg_val = self.read()
        except BusIOError as exc:
            logger.warning(
                "Failed to read register '%s' during RMW: %s; "
                "proceeding with current_value=0 — other fields may be corrupted",
                self.name,
                exc,
            )

        reg_val_to_write = _build_rmw_value(self._fields, field_values, current_reg_val)
        self.write(reg_val_to_write)


class AsyncRegister(_RegisterBase):
    """
    Asynchronous Register abstraction (for use with Cocotb/async IO).
    """

    def __init__(
        self,
        name: str,
        offset: int,
        bus: AsyncBusInterface,
        fields: List[BitField],
        description: str = "",
    ):
        super().__init__(name, offset, bus, fields, description)
        for field in fields:
            setattr(self, field.name, AsyncRegisterBoundField(self, field))

    async def read(self) -> int:
        """Read the entire register value."""
        val = self._bus.read_word(self.offset)
        if hasattr(val, "__await__"):
            return await val
        return val

    async def write(self, value: int) -> None:
        """Write the entire register value."""
        res = self._bus.write_word(self.offset, value & 0xFFFFFFFF)
        if hasattr(res, "__await__"):
            await res

    async def read_field(self, field_name: str) -> int:
        """Read a specific bit field."""
        field = self._validate_readable(field_name)
        reg_val = await self.read()
        return field.extract_value(reg_val)

    async def write_field(self, field_name: str, value: int) -> None:
        """Write a specific bit field (Read-Modify-Write)."""
        self._validate_writable(field_name, value)

        current_reg_val = 0
        try:
            current_reg_val = await self.read()
        except BusIOError as exc:
            logger.warning(
                "Failed to read register '%s' during async RMW: %s; "
                "proceeding with current_value=0 — other fields may be corrupted",
                self.name,
                exc,
            )

        reg_val_to_write = _build_rmw_value(
            self._fields, {field_name: value}, current_reg_val
        )
        await self.write(reg_val_to_write)


# Backward-compatible alias (DEPRECATED)
# Use RuntimeAccessType directly to avoid confusion with model.memory.AccessType
def __getattr__(name: str) -> Any:
    if name == "AccessType":
        warnings.warn(
            "'AccessType' alias is deprecated. Use 'RuntimeAccessType' instead to avoid "
            "confusion with ipcraft.model.memory_map.AccessType. This alias will be removed "
            "in a future version.",
            DeprecationWarning,
            stacklevel=2,
        )
        return RuntimeAccessType
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


class RegisterArrayAccessor:
    """
    Provides indexed access to a block of registers.
    """

    def __init__(
        self,
        name: str,
        base_offset: int,
        count: int,
        stride: int,
        field_template: List[BitField],
        bus_interface: AbstractBusInterface,
        register_class=Register,
    ):
        self._name = name
        self._bus = bus_interface
        self._base_offset = base_offset
        self._count = count
        self._stride = stride
        self._field_template = field_template
        self._register_class = register_class

    def __getitem__(self, index: int) -> Union[Register, AsyncRegister]:
        if not (0 <= index < self._count):
            raise IndexError(f"Index {index} out of bounds")

        item_offset = self._base_offset + (index * self._stride)
        return self._register_class(
            name=f"{self._name}[{index}]",
            offset=item_offset,
            bus=self._bus,
            fields=self._field_template,
            description=f"Element {index} of {self._name} array",
        )

    def __len__(self) -> int:
        return self._count
