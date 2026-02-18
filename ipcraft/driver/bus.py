from typing import Any

from ipcraft.runtime.register import AsyncBusInterface

# AsyncBusInterface is now imported from runtime.register
# This module only provides concrete implementations


class CocotbBus(AsyncBusInterface):
    """Bus interface implementation for Cocotb simulations using AXI-Lite or Avalon-MM."""

    def __init__(
        self, dut: Any, bus_name: str, clock: Any, reset: Any = None, bus_type: str = "axil"
    ):
        self.bus_type = bus_type

        # Use provided reset or try common reset names
        if reset is None:
            # Try common reset signal names
            for rst_name in ["rst", "rst_n", "i_rst_n", "reset", "reset_n"]:
                if hasattr(dut, rst_name):
                    reset = getattr(dut, rst_name)
                    break
            if reset is None:
                raise AttributeError(f"No reset signal found. Please provide reset explicitly.")

        if bus_type == "axil":
            # delayed import to avoiding forcing cocotb dependency on standard users
            from cocotbext.axi import AxiLiteBus, AxiLiteMaster

            bus = AxiLiteBus.from_prefix(dut, bus_name)
            self._driver = AxiLiteMaster(bus, clock, reset)

        elif bus_type == "avmm":
            from cocotb_bus.drivers.avalon import AvalonMaster

            # AvalonMaster(entity, name, clock, ...)
            self._driver = AvalonMaster(dut, bus_name, clock)

        else:
            raise ValueError(f"Unsupported bus_type: {bus_type}")

    async def read_word(self, address: int) -> int:
        if self.bus_type == "axil":
            val = await self._driver.read(address, 4)
            # val is ReadResult, val.data is bytes
            return int.from_bytes(val.data, byteorder="little")
        elif self.bus_type == "avmm":
            # AvalonMaster.read(address, sync=True) -> returns data (LogicArray/int)
            val = await self._driver.read(address)
            # Ensure proper integer conversion
            return int(val)
        return 0

    async def write_word(self, address: int, data: int) -> None:
        if self.bus_type == "axil":
            await self._driver.write(address, data.to_bytes(4, byteorder="little"))
        elif self.bus_type == "avmm":
            # AvalonMaster.write(address, value)
            await self._driver.write(address, data)
