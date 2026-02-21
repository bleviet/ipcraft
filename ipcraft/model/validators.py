"""
Validation utilities for IP core models.

Provides validation rules beyond basic Pydantic validation,
including cross-field and semantic validation.
"""

from dataclasses import dataclass
from typing import List, Set

from .core import IpCore
from .memory_map import AddressBlock, MemoryMap, RegisterDef


@dataclass
class ValidationError:
    """Validation error with context."""

    severity: str  # 'error', 'warning', 'info'
    message: str
    location: str  # Where the error occurred (e.g., 'register:CTRL', 'bus:S_AXI_LITE')
    suggestion: str = ""  # Optional fix suggestion


class IpCoreValidator:
    """
    Comprehensive IP core validator.

    Performs semantic validation beyond what Pydantic provides.
    """

    def __init__(self, ip_core: IpCore):
        self.ip_core = ip_core
        self.errors: List[ValidationError] = []
        self.warnings: List[ValidationError] = []

    def validate_all(self) -> bool:
        """
        Run all validation checks.

        Returns:
            True if no errors (warnings are allowed)
        """
        self.errors.clear()
        self.warnings.clear()

        self.validate_unique_names()
        self.validate_references()
        self.validate_memory_maps()
        self.validate_bus_interfaces()
        self.validate_address_alignment()

        return len(self.errors) == 0

    def validate_unique_names(self) -> None:
        """Check for duplicate names within each category."""
        # Check clocks
        clock_names = [c.name for c in self.ip_core.clocks]
        self._check_duplicates(clock_names, "clock")

        # Check resets
        reset_names = [r.name for r in self.ip_core.resets]
        self._check_duplicates(reset_names, "reset")

        # Check ports
        port_names = [p.name for p in self.ip_core.ports]
        self._check_duplicates(port_names, "port")

        # Check bus interfaces
        bus_names = [b.name for b in self.ip_core.bus_interfaces]
        self._check_duplicates(bus_names, "bus_interface")

        # Check memory maps
        mm_names = [mm.name for mm in self.ip_core.memory_maps]
        self._check_duplicates(mm_names, "memory_map")

    def _check_duplicates(self, names: List[str], category: str) -> None:
        """Check for duplicate names in a list."""
        seen: Set[str] = set()
        for name in names:
            if name in seen:
                self.errors.append(
                    ValidationError(
                        severity="error",
                        message=f"Duplicate {category} name: '{name}'",
                        location=f"{category}:{name}",
                        suggestion=f"Rename one of the {category}s with name '{name}'",
                    )
                )
            seen.add(name)

    def validate_references(self) -> None:
        """Validate all internal references."""
        ref_errors = self.ip_core.validate_references()
        for error_msg in ref_errors:
            self.errors.append(
                ValidationError(
                    severity="error",
                    message=error_msg,
                    location="references",
                )
            )

    def validate_memory_maps(self) -> None:
        """Validate memory map structure."""
        for mm in self.ip_core.memory_maps:
            self._validate_memory_map(mm)

    def _validate_memory_map(self, memory_map: MemoryMap) -> None:
        """Validate a single memory map."""
        for block in memory_map.address_blocks:
            self._validate_address_block(memory_map.name, block)

    def _validate_address_block(self, mm_name: str, block: AddressBlock) -> None:
        """Validate an address block."""
        # Check for register overlaps within block
        for i, reg1 in enumerate(block.registers):
            for reg2 in block.registers[i + 1 :]:
                if self._registers_overlap(reg1, reg2):
                    self.errors.append(
                        ValidationError(
                            severity="error",
                            message=f"Overlapping registers: '{reg1.name}' at {reg1.hex_address} "
                            f"and '{reg2.name}' at {reg2.hex_address}",
                            location=f"memory_map:{mm_name}:block:{block.name}",
                        )
                    )

            # Check if register is within block range
            reg_end = block.base_address + reg1.address_offset + (reg1.size // 8)
            if reg_end > block.end_address:
                self.errors.append(
                    ValidationError(
                        severity="error",
                        message=f"Register '{reg1.name}' extends beyond block '{block.name}' "
                        f"(register end: 0x{reg_end:X}, block end: 0x{block.end_address:X})",
                        location=f"memory_map:{mm_name}:block:{block.name}:register:{reg1.name}",
                    )
                )

    @staticmethod
    def _registers_overlap(reg1: RegisterDef, reg2: RegisterDef) -> bool:
        """Check if two registers overlap."""
        size1_bytes = reg1.size // 8
        size2_bytes = reg2.size // 8
        end1 = reg1.address_offset + size1_bytes
        end2 = reg2.address_offset + size2_bytes
        return not (end1 <= reg2.address_offset or end2 <= reg1.address_offset)

    def validate_bus_interfaces(self) -> None:
        """Validate bus interface configuration."""
        for bus in self.ip_core.bus_interfaces:
            # Warn if no clock/reset association
            if not bus.associated_clock:
                self.warnings.append(
                    ValidationError(
                        severity="warning",
                        message=f"Bus interface '{bus.name}' has no associated clock",
                        location=f"bus_interface:{bus.name}",
                        suggestion="Consider associating with a clock for clarity",
                    )
                )

            if not bus.associated_reset:
                self.warnings.append(
                    ValidationError(
                        severity="warning",
                        message=f"Bus interface '{bus.name}' has no associated reset",
                        location=f"bus_interface:{bus.name}",
                        suggestion="Consider associating with a reset for clarity",
                    )
                )

            # Check memory map reference for slave interfaces
            if bus.is_slave and not bus.memory_map_ref:
                self.warnings.append(
                    ValidationError(
                        severity="warning",
                        message=f"Slave bus interface '{bus.name}' has no memory map reference",
                        location=f"bus_interface:{bus.name}",
                        suggestion="Slave interfaces typically expose registers via memory maps",
                    )
                )

    def validate_address_alignment(self) -> None:
        """Check register address alignment."""
        for mm in self.ip_core.memory_maps:
            for block in mm.address_blocks:
                for reg in block.registers:
                    alignment = reg.size // 8  # Byte alignment
                    if reg.address_offset % alignment != 0:
                        self.warnings.append(
                            ValidationError(
                                severity="warning",
                                message=f"Register '{reg.name}' not aligned to {alignment}-byte boundary "
                                f"(offset: 0x{reg.address_offset:X})",
                                location=f"memory_map:{mm.name}:register:{reg.name}",
                                suggestion=f"Consider aligning to 0x{(reg.address_offset // alignment + 1) * alignment:X}",
                            )
                        )

    def get_error_summary(self) -> str:
        """Get human-readable error summary."""
        lines = []

        if self.errors:
            lines.append(f"\n{len(self.errors)} Error(s):")
            for err in self.errors:
                lines.append(
                    f"  [{err.severity.upper()}] {err.location}: {err.message}"
                )
                if err.suggestion:
                    lines.append(f"           → {err.suggestion}")

        if self.warnings:
            lines.append(f"\n{len(self.warnings)} Warning(s):")
            for warn in self.warnings:
                lines.append(
                    f"  [{warn.severity.upper()}] {warn.location}: {warn.message}"
                )
                if warn.suggestion:
                    lines.append(f"           → {warn.suggestion}")

        if not self.errors and not self.warnings:
            lines.append("\n✓ All validation checks passed")

        return "\n".join(lines)


def validate_ip_core(
    ip_core: IpCore,
) -> tuple[bool, List[ValidationError], List[ValidationError]]:
    """
    Convenience function to validate an IP core.

    Args:
        ip_core: IP core to validate

    Returns:
        Tuple of (is_valid, errors, warnings)
    """
    validator = IpCoreValidator(ip_core)
    is_valid = validator.validate_all()
    return is_valid, validator.errors, validator.warnings
