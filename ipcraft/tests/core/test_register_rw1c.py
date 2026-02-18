"""
Test module for rw1c (read-write-1-to-clear) access type functionality.

This module tests the rw1c access type implementation in the core register module.
It verifies that the driver correctly writes 1s to clear bits, and that it
reads back the correct state from the bus.
"""

from unittest.mock import Mock

import pytest

from ipcraft.runtime.register import AbstractBusInterface, BitField, Register, RuntimeAccessType


class MockBusInterface(AbstractBusInterface):
    """Mock bus interface for testing."""

    def __init__(self):
        self.memory = {}
        self.last_write_address = None
        self.last_write_data = None

    def read_word(self, address: int) -> int:
        return self.memory.get(address, 0)

    def write_word(self, address: int, data: int) -> None:
        self.memory[address] = data & 0xFFFFFFFF
        self.last_write_address = address
        self.last_write_data = data

    def clear_history(self):
        self.last_write_address = None
        self.last_write_data = None


class TestRW1CAccessType:
    """Test cases for rw1c access type functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.bus = MockBusInterface()

        # Create a register with mixed access types including rw1c
        self.fields = [
            BitField(
                name="tx_complete", offset=0, width=1, access="rw1c", description="TX complete flag"
            ),
            BitField(
                name="rx_complete", offset=1, width=1, access="rw1c", description="RX complete flag"
            ),
            BitField(
                name="error_flags", offset=8, width=4, access="rw1c", description="Error flags"
            ),
            BitField(
                name="control", offset=16, width=8, access="rw", description="Control register"
            ),
        ]

        self.reg = Register(name="status", offset=0x10, bus=self.bus, fields=self.fields)

    def test_rw1c_field_creation(self):
        """Test that rw1c fields are created correctly."""
        assert "tx_complete" in self.reg.get_field_names()
        assert "rx_complete" in self.reg.get_field_names()
        assert "error_flags" in self.reg.get_field_names()

        tx_field = self.reg.get_field_info("tx_complete")
        assert tx_field.access == RuntimeAccessType.RW1C.value
        assert tx_field.offset == 0
        assert tx_field.width == 1

    def test_rw1c_single_bit_clear(self):
        """Test clearing a single bit in an rw1c field."""
        # Initial state: everything set
        initial_val = 0x00010F03
        self.bus.write_word(0x10, initial_val)
        self.bus.clear_history()

        # Verify initial read
        assert self.reg.read_field("tx_complete") == 1

        # Clear tx_complete by writing 1
        self.reg.write_field("tx_complete", 1)

        # Verify Driver Action:
        # Should write 1 to bit 0.
        # Should write 0 to bit 1 (rx_complete) to preserve it.
        # Should write 0 to bits 8-11 (error_flags) to preserve them.
        # Should write current value to bit 16-23 (control) to preserve it.

        # Expected write value:
        # tx_complete (0) -> 1 (to clear)
        # rx_complete (1) -> 0 (to preserve)
        # error_flags (8) -> 0 (to preserve)
        # control (16) -> 1 (preserve value 1)

        # Wait, if we preserve control (RW), we write back what we read.
        # Read: control=1. So write 1 << 16 = 0x10000.
        # Total expected write: 0x00010001

        expected_write = 0x00010001
        assert self.bus.last_write_data == expected_write

        # Simulate HW Behavior:
        # Writing 1 to bit 0 clears it.
        # Writing 0 to bit 1 preserves it.
        # Writing 0 to bits 8-11 preserves them.
        # Writing 1 to bit 16 (RW) sets/keeps it as 1.

        # Update mock memory to reflect HW action
        new_val = initial_val & ~0x1  # Clear bit 0
        self.bus.memory[0x10] = new_val

        # Verify read back
        assert self.reg.read_field("tx_complete") == 0
        assert self.reg.read_field("rx_complete") == 1
        assert self.reg.read_field("error_flags") == 15
        assert self.reg.read_field("control") == 1

    def test_rw1c_write_zero_no_effect(self):
        """Test that writing 0 to rw1c field sends 0 to bus (no effect on HW)."""
        # Initial: rx_complete=1
        initial_val = 0x00000002
        self.bus.write_word(0x10, initial_val)
        self.bus.clear_history()

        # Write 0 to rx_complete
        self.reg.write_field("rx_complete", 0)

        # Expected write:
        # rx_complete (1) -> 0 (to do nothing)
        # tx_complete (0) -> 0 (preserve)
        # error_flags -> 0
        # control -> 0

        assert self.bus.last_write_data == 0x00000000

        # HW matches bus for RW1C (0 clears nothing)
        # So memory remains same
        self.bus.memory[0x10] = initial_val

        assert self.reg.read_field("rx_complete") == 1

    def test_rw1c_multi_bit_field(self):
        """Test rw1c behavior with multi-bit fields."""
        # error_flags=15 (1111)
        initial_val = 0x00000F00
        self.bus.write_word(0x10, initial_val)

        # Clear bits 0 and 2 (val 5 -> 0101) of error_flags
        self.reg.write_field("error_flags", 5)

        # offset 8. 5 << 8 = 0x500.
        # Expected write: 0x500.
        assert self.bus.last_write_data == 0x500

        # Simulate HW: clear bits that were 1 in write
        # 0xF00 & ~(0x500) = 0xA00 (1010)
        self.bus.memory[0x10] = 0xA00

        assert self.reg.read_field("error_flags") == 10

    def test_rw1c_mixed_with_normal_rw(self):
        """Test that rw1c fields don't affect normal rw fields."""
        # control=1, error=15, rx=1, tx=1
        initial_val = 0x00010F03
        self.bus.write_word(0x10, initial_val)

        # Modify control (RW) to 42
        self.reg.write_field("control", 42)

        # Expected write:
        # control -> 42 << 16 = 0x002A0000
        # error_flags (RW1C) -> 0 (preserve)
        # rx (RW1C) -> 0 (preserve)
        # tx (RW1C) -> 0 (preserve)

        expected_write = 0x002A0000
        assert self.bus.last_write_data == expected_write

        # Simulate HW:
        # Control becomes 42.
        # RW1C fields receive 0 -> No change.
        new_mem = (initial_val & 0xFFFF) | expected_write
        self.bus.memory[0x10] = new_mem

        assert self.reg.read_field("control") == 42
        assert self.reg.read_field("tx_complete") == 1

    def test_rw1c_multiple_fields_write(self):
        """Test writing to multiple fields."""
        # initial: error=15, rx=1, tx=1. control=0
        initial_val = 0x00000F03
        self.bus.write_word(0x10, initial_val)

        # Clear tx (bit 0) -> write 1
        # Clear error bits 0,1 (val 3) -> write 3 << 8

        self.reg.write_multiple_fields({"tx_complete": 1, "error_flags": 3})

        # Expected:
        # tx -> 1
        # error -> 3 << 8 = 0x300
        # rx -> 0 (preserve)

        expected = 0x00000301
        assert self.bus.last_write_data == expected

        # Simulate HM
        # Clear tx bit 0
        # Clear error bits 8,9
        mask = expected
        new_mem = initial_val & ~mask
        self.bus.memory[0x10] = new_mem

        assert self.reg.read_field("tx_complete") == 0
        assert self.reg.read_field("error_flags") == 12  # 1100

    def test_rw1c_read_all_fields(self):
        val = 0x00AA0F03
        self.bus.write_word(0x10, val)

        fields = self.reg.read_all_fields()
        assert fields["control"] == 170
        assert fields["error_flags"] == 15
        assert fields["tx_complete"] == 1

    def test_rw1c_dynamic_access(self):
        # rx=1, tx=1
        initial_val = 0x00000003
        self.bus.write_word(0x10, initial_val)

        assert self.reg.tx_complete.read() == 1

        # Write 1 to clear tx
        self.reg.tx_complete.write(1)

        # Check bus write
        assert self.bus.last_write_data == 1

        # Simulate HW
        self.bus.memory[0x10] = initial_val & ~1

        assert self.reg.tx_complete.read() == 0

    def test_rw1c_field_validation(self):
        # Valid
        f = BitField(name="test", offset=0, width=1, access="rw1c")
        assert f.access == "rw1c"

        # Invalid
        with pytest.raises(ValueError):
            BitField(name="test", offset=0, width=1, access="invalid")


if __name__ == "__main__":
    t = TestRW1CAccessType()
    t.setup_method()
    t.test_rw1c_single_bit_clear()
    print("Passed")
