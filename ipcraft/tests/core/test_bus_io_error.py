import logging
import pytest
from ipcraft.runtime.register import (
    AbstractBusInterface, BitField, BusIOError, Register,
)


class FailingBus(AbstractBusInterface):
    """Bus that raises BusIOError on read."""

    def read_word(self, address: int) -> int:
        raise BusIOError("bus timeout")

    def write_word(self, address: int, data: int) -> None:
        pass


class TestRMWWithBusError:
    def test_write_field_logs_warning_on_bus_error(self, caplog):
        fields = [BitField(name="ENABLE", offset=0, width=1, access="rw")]
        reg = Register("CTRL", 0x00, FailingBus(), fields)

        with caplog.at_level(logging.WARNING):
            reg.write_field("ENABLE", 1)

        assert "bus timeout" in caplog.text

    def test_bus_io_error_is_ioerror(self):
        assert issubclass(BusIOError, IOError)

    def test_programming_errors_propagate(self):
        """Non-BusIOError exceptions should NOT be caught."""
        class BrokenBus(AbstractBusInterface):

            def read_word(self, address: int) -> int:
                raise TypeError("this is a bug")

            def write_word(self, address: int, data: int) -> None:
                pass

        fields = [BitField(name="ENABLE", offset=0, width=1, access="rw")]
        reg = Register("CTRL", 0x00, BrokenBus(), fields)
        with pytest.raises(TypeError, match="this is a bug"):
            reg.write_field("ENABLE", 1)
