"""
Test the Pydantic models with example data.

This test demonstrates creating and validating IP core models.
"""

import pytest

from ipcraft.model import (
    VLNV,
    AccessType,
    AddressBlock,
    ArrayConfig,
    BitFieldDef,
    BusInterface,
    Clock,
    File,
    FileSet,
    FileType,
    IpCore,
    MemoryMap,
    Parameter,
    Polarity,
    Port,
    PortDirection,
    RegisterDef,
    Reset,
)
from ipcraft.model.validators import validate_ip_core


def test_basic_ip_core_creation():
    """Test creating a simple IP core."""
    # Create minimal IP core
    ip_core = IpCore(
        api_version="my-ip-schema/v2.3",
        vlnv=VLNV(
            vendor="my-company.com",
            library="processing",
            name="simple_core",
            version="1.0.0",
        ),
        description="A simple test IP core",
    )

    assert ip_core.vlnv.full_name == "my-company.com:processing:simple_core:1.0.0"
    assert ip_core.api_version == "my-ip-schema/v2.3"
    assert ip_core.description == "A simple test IP core"


def test_clocks_and_resets():
    """Test clock and reset definitions."""
    clock = Clock(
        name="i_clk_sys",
        logical_name="CLK",
        direction="in",
        frequency="100MHz",
        description="Main system clock",
    )

    assert clock.name == "i_clk_sys"
    assert clock.logical_name == "CLK"
    assert clock.frequency == "100MHz"

    reset = Reset(
        name="i_rst_n_sys",
        logical_name="RESET_N",
        direction="in",
        polarity=Polarity.ACTIVE_LOW,
        description="System reset, active low",
    )

    assert reset.name == "i_rst_n_sys"
    assert reset.logical_name == "RESET_N"
    assert reset.is_active_low is True
    assert reset.polarity == Polarity.ACTIVE_LOW


def test_bus_interface():
    """Test bus interface definition."""
    print("=" * 80)
    print("Test 3: Bus Interface")
    print("=" * 80)

    # Simple AXI4-Lite slave
    bus = BusInterface(
        name="S_AXI_LITE",
        type="AXI4L",
        mode="slave",
        physical_prefix="s_axi_",
        associated_clock="REG_CLK",
        associated_reset="REG_RST",
        memory_map_ref="CSR_MAP",
        use_optional_ports=["AWPROT", "ARPROT"],
        port_width_overrides={"AWADDR": 12, "ARADDR": 12, "WDATA": 32, "RDATA": 32, "WSTRB": 4},
    )

    print(f"✓ Created bus interface: {bus.name}")
    print(f"  Type: {bus.type}")
    print(f"  Mode: {bus.mode} (is_slave: {bus.is_slave})")
    print(f"  Physical prefix: {bus.physical_prefix}")
    print(f"  Width overrides: {bus.port_width_overrides}")
    print()


def test_bus_interface_array():
    """Test bus interface array configuration."""
    print("=" * 80)
    print("Test 4: Bus Interface Array")
    print("=" * 80)

    # AXI Stream master array
    array_config = ArrayConfig(
        count=4,
        index_start=0,
        naming_pattern="M_AXIS_CH{index}_EVENTS",
        physical_prefix_pattern="m_axis_ch{index}_evt_",
    )

    bus = BusInterface(
        name="M_AXIS_EVENTS",
        type="AXIS",
        mode="master",
        physical_prefix="m_axis_evt_",
        associated_clock="SYS_CLK",
        associated_reset="SYS_RST",
        use_optional_ports=["TLAST", "TUSER"],
        port_width_overrides={"TDATA": 64, "TSTRB": 8, "TKEEP": 8, "TUSER": 4},
        array=array_config,
    )

    print(f"✓ Created bus interface array: {bus.name}")
    print(f"  Type: {bus.type}")
    print(f"  Is array: {bus.is_array}")
    print(f"  Instance count: {bus.instance_count}")
    print(f"  Instances:")
    for idx in bus.array.indices:
        print(
            f"    [{idx}] {bus.array.get_instance_name(idx)} -> {bus.array.get_instance_prefix(idx)}"
        )
    print()


def test_memory_map():
    """Test memory map with registers."""
    print("=" * 80)
    print("Test 5: Memory Map with Registers")
    print("=" * 80)

    # Create registers
    ctrl_reg = RegisterDef(
        name="CTRL",
        address_offset=0x00,
        size=32,
        access=AccessType.READ_WRITE,
        description="Control register",
        fields=[
            BitFieldDef(name="ENABLE", bit_offset=0, bit_width=1, access=AccessType.READ_WRITE),
            BitFieldDef(
                name="MODE",
                bit_offset=1,
                bit_width=1,
                access=AccessType.READ_WRITE,
                description="0=normal, 1=debug",
            ),
            BitFieldDef(name="RESERVED", bit_offset=2, bit_width=30, access=AccessType.READ_ONLY),
        ],
    )

    status_reg = RegisterDef(
        name="STATUS",
        address_offset=0x04,
        size=32,
        access=AccessType.WRITE_1_TO_CLEAR,
        description="Status register",
        fields=[
            BitFieldDef(
                name="IRQ_PENDING",
                bit_offset=0,
                bit_width=1,
                access=AccessType.WRITE_1_TO_CLEAR,
            ),
            BitFieldDef(name="RESERVED", bit_offset=1, bit_width=31, access=AccessType.READ_ONLY),
        ],
    )

    # Create address block
    block = AddressBlock(
        name="CONTROL_REGS",
        base_address=0x0000,
        range=4096,
        description="Control and status registers",
        registers=[ctrl_reg, status_reg],
    )

    # Create memory map
    memory_map = MemoryMap(
        name="CSR_MAP",
        description="Control/Status Register Map",
        address_blocks=[block],
    )

    print(f"✓ Created memory map: {memory_map.name}")
    print(f"  Total registers: {memory_map.total_registers}")
    print(f"  Address space: {memory_map.total_address_space} bytes")
    print(f"\n  Address Block: {block.name}")
    print(f"    Range: {block.hex_range}")
    for reg in block.registers:
        print(f"    Register: {reg.name} @ {reg.hex_address} ({reg.access.value})")
        for field in reg.fields:
            print(f"      Field: {field.name} {field.bit_range} ({field.access.value})")
    print()


def test_complete_ip_core():
    """Test creating a complete IP core similar to my_timer_core.yml."""
    # Create the complete IP core
    ip_core = IpCore(
        api_version="my-ip-schema/v2.3",
        vlnv=VLNV(
            vendor="my-company.com",
            library="processing",
            name="my_timer_core",
            version="1.2.0",
        ),
        description="A 4-channel, 32-bit configurable timer IP",
        clocks=[
            Clock(
                name="i_clk_sys",
                logical_name="CLK",
                frequency="100MHz",
                description="Main system clock",
            ),
            Clock(
                name="i_clk_reg",
                logical_name="CLK",
                frequency="50MHz",
                description="Register interface clock",
            ),
        ],
        resets=[
            Reset(
                name="i_rst_n_sys",
                logical_name="RESET_N",
                polarity=Polarity.ACTIVE_LOW,
                description="System reset, active low",
            ),
            Reset(
                name="i_rst_p_reg",
                logical_name="RESET",
                polarity=Polarity.ACTIVE_HIGH,
                description="Register reset, active high",
            ),
        ],
        ports=[
            Port(
                name="o_global_irq",
                logical_name="o_irq",
                direction=PortDirection.OUT,
                width=1,
                description="Global interrupt request",
            )
        ],
        bus_interfaces=[
            BusInterface(
                name="S_AXI_LITE",
                type="AXI4L",
                mode="slave",
                physical_prefix="s_axi_",
                associated_clock="i_clk_reg",
                associated_reset="i_rst_p_reg",
                memory_map_ref="CSR_MAP",
                use_optional_ports=["AWPROT", "ARPROT"],
                port_width_overrides={
                    "AWADDR": 12,
                    "ARADDR": 12,
                    "WDATA": 32,
                    "RDATA": 32,
                    "WSTRB": 4,
                },
            ),
            BusInterface(
                name="M_AXIS_EVENTS",
                type="AXIS",
                mode="master",
                physical_prefix="m_axis_evt_",
                associated_clock="i_clk_sys",
                associated_reset="i_rst_n_sys",
                use_optional_ports=["TLAST", "TUSER"],
                port_width_overrides={"TDATA": 64, "TSTRB": 8, "TKEEP": 8, "TUSER": 4},
                array=ArrayConfig(
                    count=4,
                    index_start=0,
                    naming_pattern="M_AXIS_CH{index}_EVENTS",
                    physical_prefix_pattern="m_axis_ch{index}_evt_",
                ),
            ),
        ],
        parameters=[
            Parameter(
                name="NUM_CHANNELS",
                value=4,
                data_type="integer",
                description="Number of timer channels",
            ),
            Parameter(name="AXI_ADDR_WIDTH", value=32, data_type="integer"),
            Parameter(
                name="EVENT_FIFO_DEPTH",
                value=16,
                data_type="integer",
                description="Event FIFO depth per channel",
            ),
        ],
        file_sets=[
            FileSet(
                name="RTL_Sources",
                description="Verilog source files",
                files=[
                    File(path="rtl/my_timer_core_top.v", type=FileType.VERILOG),
                    File(path="rtl/my_timer_channel.v", type=FileType.VERILOG),
                    File(path="rtl/my_timer_axi_if.v", type=FileType.VERILOG),
                ],
            )
        ],
        use_bus_library="../common/bus_definitions.yml",
    )

    # Assertions
    assert ip_core.vlnv.full_name == "my-company.com:processing:my_timer_core:1.2.0"
    assert len(ip_core.clocks) == 2
    assert ip_core.clocks[0].name == "i_clk_sys"
    assert ip_core.clocks[0].frequency == "100MHz"

    assert len(ip_core.resets) == 2
    assert ip_core.resets[0].polarity == Polarity.ACTIVE_LOW
    assert ip_core.resets[1].polarity == Polarity.ACTIVE_HIGH

    assert len(ip_core.ports) == 1
    assert ip_core.ports[0].name == "o_global_irq"
    assert ip_core.ports[0].direction == PortDirection.OUT

    assert len(ip_core.bus_interfaces) == 2
    assert ip_core.bus_interfaces[0].name == "S_AXI_LITE"
    assert ip_core.bus_interfaces[0].is_slave is True
    assert ip_core.bus_interfaces[1].name == "M_AXIS_EVENTS"
    assert ip_core.bus_interfaces[1].is_array is True
    assert ip_core.bus_interfaces[1].instance_count == 4

    assert len(ip_core.parameters) == 3
    assert ip_core.parameters[0].name == "NUM_CHANNELS"
    assert ip_core.parameters[0].value == 4

    assert len(ip_core.file_sets) == 1
    assert ip_core.file_sets[0].name == "RTL_Sources"
    assert len(ip_core.file_sets[0].files) == 3

    # Validate - should fail because memory map is missing
    is_valid, errors, warnings = validate_ip_core(ip_core)
    assert is_valid is False
    assert len(errors) == 1
    assert "CSR_MAP" in errors[0].message
