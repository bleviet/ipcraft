from dataclasses import dataclass

import yaml

from ipcraft.model.memory_map import MemoryMap
from ipcraft.runtime.register import (
    AbstractBusInterface,
    AsyncRegister,
    Register,
    RegisterArrayAccessor,
)


@dataclass
class AddressBlock:
    """Runtime container for registers within an address block."""

    _name: str
    _offset: int
    _bus: AbstractBusInterface


class IpCoreDriver:
    """Root driver object containing address blocks."""

    def __init__(self, bus_interface: AbstractBusInterface):
        self._bus = bus_interface


def load_driver(
    yaml_path: str, bus_interface: AbstractBusInterface, async_driver: bool = True
) -> IpCoreDriver:
    """
    Loads a memory map from a YAML file and returns a configured IpCoreDriver.

    Args:
        yaml_path: Path to the memory map YAML file.
        async_driver:
            If True, uses AsyncRegister for Cocotb compatibility.
            If False, uses valid synchronous Register.

    Returns:
        Configured IpCoreDriver instance with accessible address blocks and registers.
    """
    driver = IpCoreDriver(bus_interface)

    with open(yaml_path, "r") as f:
        data = yaml.safe_load(f)

    # Normalize input to list of maps
    if isinstance(data, dict):
        data_list = [data]
    elif isinstance(data, list):
        data_list = data
    else:
        raise ValueError("Invalid YAML format: expected list or dict at root")

    register_class = AsyncRegister if async_driver else Register

    for map_data in data_list:
        # validate using Pydantic model
        # The input data might be just the fields of MemoryMap.
        memory_map = MemoryMap.model_validate(map_data)

        for block_def in memory_map.address_blocks:
            # Create runtime block container
            block_obj = AddressBlock(
                _name=block_def.name,
                _offset=block_def.base_address or 0,
                _bus=bus_interface,
            )

            # Helper to attach registers to the block
            for reg_def in block_def.registers:
                block_base = block_def.base_address or 0

                # Check for array
                if reg_def.count is not None and reg_def.count > 1:
                    # It's an array
                    # We need to construct the RegisterArrayAccessor manually
                    # because RegisterDef doesn't have a direct to_runtime_array method
                    # (RegisterArrayDef does, but here we have RegisterDef).

                    # Convert fields to runtime BitFields
                    fields_runtime = [f.to_runtime_bitfield() for f in reg_def.fields]

                    reg_base = block_base + (reg_def.address_offset or 0)
                    stride = reg_def.stride
                    if stride is None:
                        # Default stride = 4? Or calculate from size?
                        stride = 4  # Default standard word stride

                    accessor = RegisterArrayAccessor(
                        name=reg_def.name,
                        base_offset=reg_base,
                        count=reg_def.count,
                        stride=stride,
                        field_template=fields_runtime,
                        bus_interface=bus_interface,
                        register_class=register_class,
                    )
                    setattr(block_obj, reg_def.name, accessor)

                else:
                    # Single register
                    reg_obj = reg_def.to_runtime_register(
                        bus=bus_interface,
                        base_offset=block_base,
                        register_class=register_class,
                    )
                    setattr(block_obj, reg_def.name, reg_obj)

            # Attach block to driver
            setattr(driver, block_def.name, block_obj)

    return driver
