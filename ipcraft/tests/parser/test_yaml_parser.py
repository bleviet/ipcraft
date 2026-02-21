"""
Tests for the YAML IP Core parser.
"""

# editorconfig-checker-disable-file
# This file contains YAML fixtures that use 2-space indentation per YAML standard

from pathlib import Path

import pytest

from ipcraft.model import AccessType, Polarity, PortDirection
from ipcraft.parser import ParseError, YamlIpCoreParser

# Get the path to the examples directory
EXAMPLES_DIR = Path(__file__).parent.parent.parent.parent / "examples" / "ip"


def test_parse_simple_ip_core(tmp_path):
    """Test parsing a minimal IP core definition."""
    yaml_content = """
apiVersion: my-ip-schema/v2.3
vlnv:
    vendor: "test.com"
    library: "test"
    name: "simple_core"
    version: "1.0.0"
description: "A simple test core"
"""
    yaml_file = tmp_path / "simple.yml"
    yaml_file.write_text(yaml_content)

    parser = YamlIpCoreParser()
    ip_core = parser.parse_file(yaml_file)

    assert ip_core.api_version == "my-ip-schema/v2.3"
    assert ip_core.vlnv.vendor == "test.com"
    assert ip_core.vlnv.library == "test"
    assert ip_core.vlnv.name == "simple_core"
    assert ip_core.vlnv.version == "1.0.0"
    assert ip_core.description == "A simple test core"


def test_parse_with_clocks_and_resets(tmp_path):
    """Test parsing clocks and resets."""
    yaml_content = """
apiVersion: my-ip-schema/v2.3
vlnv:
    vendor: "test.com"
    library: "test"
    name: "clocked_core"
    version: "1.0.0"

clocks:
    - name: "i_clk"
      logicalName: "CLK"
      direction: "in"
      frequency: "100MHz"
      description: "System clock"

resets:
    - name: "i_rst_n"
      logicalName: "RESET_N"
      direction: "in"
      polarity: "activeLow"
      description: "Active low reset"

    - name: "i_rst_p"
      logicalName: "RESET"
      polarity: "activeHigh"
"""
    yaml_file = tmp_path / "clocked.yml"
    yaml_file.write_text(yaml_content)

    parser = YamlIpCoreParser()
    ip_core = parser.parse_file(yaml_file)

    assert len(ip_core.clocks) == 1
    assert ip_core.clocks[0].name == "i_clk"
    assert ip_core.clocks[0].logical_name == "CLK"
    assert ip_core.clocks[0].frequency == "100MHz"

    assert len(ip_core.resets) == 2
    assert ip_core.resets[0].name == "i_rst_n"
    assert ip_core.resets[0].logical_name == "RESET_N"
    assert ip_core.resets[0].polarity == Polarity.ACTIVE_LOW
    assert ip_core.resets[0].is_active_low is True
    assert ip_core.resets[1].polarity == Polarity.ACTIVE_HIGH


def test_parse_with_ports(tmp_path):
    """Test parsing port definitions."""
    yaml_content = """
apiVersion: my-ip-schema/v2.3
vlnv:
    vendor: "test.com"
    library: "test"
    name: "port_core"
    version: "1.0.0"

ports:
    - name: "o_irq"
      logicalName: "irq"
      direction: "out"
      description: "Interrupt output"

    - name: "io_data"
      logicalName: "data_bus"
      direction: "inout"
      width: 32
"""
    yaml_file = tmp_path / "ports.yml"
    yaml_file.write_text(yaml_content)

    parser = YamlIpCoreParser()
    ip_core = parser.parse_file(yaml_file)

    assert len(ip_core.ports) == 2
    assert ip_core.ports[0].name == "o_irq"
    assert ip_core.ports[0].logical_name == "irq"
    assert ip_core.ports[0].direction == PortDirection.OUT
    assert ip_core.ports[1].width == 32
    assert ip_core.ports[1].direction == PortDirection.INOUT


def test_parse_bus_interface(tmp_path):
    """Test parsing bus interface definitions."""
    yaml_content = """
apiVersion: my-ip-schema/v2.3
vlnv:
    vendor: "test.com"
    library: "test"
    name: "bus_core"
    version: "1.0.0"

busInterfaces:
    - name: "S_AXI"
      type: "AXI4L"
      mode: "slave"
      physicalPrefix: "s_axi_"
      associatedClock: "CLK"
      associatedReset: "RST"
      memoryMapRef: "REGS"
      useOptionalPorts:
        - "AWPROT"
        - "ARPROT"
      portWidthOverrides:
        AWADDR: 12
        ARADDR: 12
        WDATA: 32
        RDATA: 32
"""
    yaml_file = tmp_path / "bus.yml"
    yaml_file.write_text(yaml_content)

    parser = YamlIpCoreParser()
    ip_core = parser.parse_file(yaml_file)

    assert len(ip_core.bus_interfaces) == 1
    bus = ip_core.bus_interfaces[0]
    assert bus.name == "S_AXI"
    assert bus.type == "AXI4L"
    assert bus.mode == "slave"
    assert bus.is_slave is True
    assert bus.physical_prefix == "s_axi_"
    assert bus.memory_map_ref == "REGS"
    assert "AWPROT" in bus.use_optional_ports
    assert bus.port_width_overrides["AWADDR"] == 12


def test_parse_bus_interface_array(tmp_path):
    """Test parsing bus interface with array configuration."""
    yaml_content = """
apiVersion: my-ip-schema/v2.3
vlnv:
    vendor: "test.com"
    library: "test"
    name: "array_core"
    version: "1.0.0"

busInterfaces:
    - name: "M_AXIS"
      type: "AXIS"
      mode: "master"
      physicalPrefix: "m_axis_"
      associatedClock: "CLK"
      array:
        count: 4
        indexStart: 0
        namingPattern: "M_AXIS_CH{index}"
        physicalPrefixPattern: "m_axis_ch{index}_"
"""
    yaml_file = tmp_path / "array.yml"
    yaml_file.write_text(yaml_content)

    parser = YamlIpCoreParser()
    ip_core = parser.parse_file(yaml_file)

    assert len(ip_core.bus_interfaces) == 1
    bus = ip_core.bus_interfaces[0]
    assert bus.is_array is True
    assert bus.instance_count == 4
    assert bus.array.get_instance_name(0) == "M_AXIS_CH0"
    assert bus.array.get_instance_prefix(2) == "m_axis_ch2_"


def test_parse_parameters(tmp_path):
    """Test parsing parameter definitions."""
    yaml_content = """
apiVersion: my-ip-schema/v2.3
vlnv:
    vendor: "test.com"
    library: "test"
    name: "param_core"
    version: "1.0.0"

parameters:
    - name: "DATA_WIDTH"
      value: 32
      dataType: "integer"
      description: "Width of data bus"

    - name: "ENABLE_FEATURE"
      value: true
      dataType: "boolean"
"""
    yaml_file = tmp_path / "params.yml"
    yaml_file.write_text(yaml_content)

    parser = YamlIpCoreParser()
    ip_core = parser.parse_file(yaml_file)

    assert len(ip_core.parameters) == 2
    assert ip_core.parameters[0].name == "DATA_WIDTH"
    assert ip_core.parameters[0].value == 32
    assert ip_core.parameters[0].data_type == "integer"
    assert ip_core.parameters[1].value is True


def test_parse_memory_map_inline(tmp_path):
    """Test parsing inline memory map definitions."""
    yaml_content = """
apiVersion: my-ip-schema/v2.3
vlnv:
    vendor: "test.com"
    library: "test"
    name: "reg_core"
    version: "1.0.0"

memoryMaps:
    - name: "CSR"
      description: "Control/Status Registers"
      addressBlocks:
        - name: "REGS"
          baseAddress: 0x0
          range: 4096
          defaultRegWidth: 32
          registers:
            - name: "CTRL"
              addressOffset: 0x00
              size: 32
              access: "read-write"
              description: "Control register"
              fields:
                - name: "ENABLE"
                  bitOffset: 0
                  bitWidth: 1
                  access: "read-write"
                - name: "MODE"
                  bitOffset: 1
                  bitWidth: 2

            - name: "STATUS"
              addressOffset: 0x04
              size: 32
              access: "write-1-to-clear"
              fields:
                - name: "IRQ"
                  bitWidth: 1
"""
    yaml_file = tmp_path / "regs.yml"
    yaml_file.write_text(yaml_content)

    parser = YamlIpCoreParser()
    ip_core = parser.parse_file(yaml_file)

    assert len(ip_core.memory_maps) == 1
    mem_map = ip_core.memory_maps[0]
    assert mem_map.name == "CSR"
    assert len(mem_map.address_blocks) == 1

    block = mem_map.address_blocks[0]
    assert block.name == "REGS"
    assert block.range == 4096
    assert len(block.registers) == 2

    ctrl_reg = block.registers[0]
    assert ctrl_reg.name == "CTRL"
    assert ctrl_reg.address_offset == 0x00
    assert ctrl_reg.access == AccessType.READ_WRITE
    assert len(ctrl_reg.fields) == 2
    assert ctrl_reg.fields[0].name == "ENABLE"
    assert ctrl_reg.fields[0].bit_offset == 0

    status_reg = block.registers[1]
    assert status_reg.access == AccessType.WRITE_1_TO_CLEAR
    # Test auto-calculated bit offset
    assert status_reg.fields[0].bit_offset == 0


def test_parse_file_sets(tmp_path):
    """Test parsing file set definitions."""
    yaml_content = """
apiVersion: my-ip-schema/v2.3
vlnv:
    vendor: "test.com"
    library: "test"
    name: "files_core"
    version: "1.0.0"

fileSets:
    - name: "RTL"
      description: "RTL source files"
      files:
        - path: "rtl/top.v"
          type: "verilog"
        - path: "rtl/sub.vhd"
          type: "vhdl"

    - name: "SIM"
      files:
        - path: "tb/testbench.sv"
          type: "systemverilog"
"""
    yaml_file = tmp_path / "files.yml"
    yaml_file.write_text(yaml_content)

    parser = YamlIpCoreParser()
    ip_core = parser.parse_file(yaml_file)

    assert len(ip_core.file_sets) == 2
    assert ip_core.file_sets[0].name == "RTL"
    assert len(ip_core.file_sets[0].files) == 2
    assert ip_core.file_sets[0].files[0].path == "rtl/top.v"
    assert ip_core.file_sets[0].files[1].type.value == "vhdl"


def test_parse_memory_map_with_import(tmp_path):
    """Test parsing memory map with external file import."""
    # Create memory map file
    memmap_content = """
- name: "CSR_MAP"
  description: "Control registers"
  addressBlocks:
    - name: "REGS"
      baseAddress: 0x0
      range: 1024
      registers:
        - name: "ID"
          size: 32
"""
    memmap_file = tmp_path / "regs.mm.yml"
    memmap_file.write_text(memmap_content)

    # Create main IP core file
    yaml_content = f"""
apiVersion: my-ip-schema/v2.3
vlnv:
    vendor: "test.com"
    library: "test"
    name: "import_core"
    version: "1.0.0"

memoryMaps:
    import: "{memmap_file.name}"
"""
    yaml_file = tmp_path / "core.yml"
    yaml_file.write_text(yaml_content)

    parser = YamlIpCoreParser()
    ip_core = parser.parse_file(yaml_file)

    assert len(ip_core.memory_maps) == 1
    assert ip_core.memory_maps[0].name == "CSR_MAP"


def test_parse_real_timer_core():
    """Test parsing the actual my_timer_core.yml example."""
    timer_yml = EXAMPLES_DIR / "my_timer_core.yml"

    if not timer_yml.exists():
        pytest.skip(f"Example file not found: {timer_yml}")

    parser = YamlIpCoreParser()
    ip_core = parser.parse_file(timer_yml)

    # Verify core structure
    assert ip_core.vlnv.vendor == "my-company.com"
    assert ip_core.vlnv.library == "processing"
    assert ip_core.vlnv.name == "my_timer_core"
    assert ip_core.vlnv.version == "1.2.0"

    # Verify clocks
    assert len(ip_core.clocks) == 2
    assert ip_core.clocks[0].name == "i_clk_sys"
    assert ip_core.clocks[0].frequency == "100MHz"

    # Verify resets
    assert len(ip_core.resets) == 2
    assert ip_core.resets[0].polarity == Polarity.ACTIVE_LOW

    # Verify ports
    assert len(ip_core.ports) == 1
    assert ip_core.ports[0].name == "o_global_irq"

    # Verify bus interfaces
    assert len(ip_core.bus_interfaces) == 2
    assert ip_core.bus_interfaces[0].name == "S_AXI_LITE"
    assert ip_core.bus_interfaces[0].mode == "slave"
    assert ip_core.bus_interfaces[1].is_array is True
    assert ip_core.bus_interfaces[1].instance_count == 4

    # Verify parameters
    assert len(ip_core.parameters) == 4
    param_dict = {p.name: p.value for p in ip_core.parameters}
    assert param_dict["NUM_CHANNELS"] == 4

    # Verify file sets
    assert len(ip_core.file_sets) >= 1


def test_error_missing_required_field(tmp_path):
    """Test error handling for missing required fields."""
    yaml_content = """
apiVersion: my-ip-schema/v2.3
description: "Missing VLNV"
"""
    yaml_file = tmp_path / "invalid.yml"
    yaml_file.write_text(yaml_content)

    parser = YamlIpCoreParser()
    with pytest.raises(ParseError) as exc_info:
        parser.parse_file(yaml_file)

    assert "vlnv" in str(exc_info.value).lower()


def test_error_invalid_yaml(tmp_path):
    """Test error handling for invalid YAML syntax."""
    yaml_content = """
apiVersion: my-ip-schema/v2.3
vlnv:
    vendor: "test.com
    # Missing closing quote
"""
    yaml_file = tmp_path / "bad_syntax.yml"
    yaml_file.write_text(yaml_content)

    parser = YamlIpCoreParser()
    with pytest.raises(ParseError) as exc_info:
        parser.parse_file(yaml_file)

    assert "syntax error" in str(exc_info.value).lower()


def test_error_file_not_found():
    """Test error handling for non-existent file."""
    parser = YamlIpCoreParser()
    with pytest.raises(ParseError) as exc_info:
        parser.parse_file("/non/existent/file.yml")

    assert "not found" in str(exc_info.value).lower()


def test_auto_offset_calculation(tmp_path):
    """Test automatic offset calculation for registers."""
    yaml_content = """
apiVersion: my-ip-schema/v2.3
vlnv:
    vendor: "test.com"
    library: "test"
    name: "offset_test"
    version: "1.0.0"

memoryMaps:
    - name: "REGS"
      addressBlocks:
        - name: "BLOCK"
          baseAddress: 0x0
          range: 1024
          registers:
            - name: "REG0"
              size: 32
            - name: "REG1"
              size: 32
            - reserved: 8
            - name: "REG2"
              size: 32
"""
    yaml_file = tmp_path / "offsets.yml"
    yaml_file.write_text(yaml_content)

    parser = YamlIpCoreParser()
    ip_core = parser.parse_file(yaml_file)

    regs = ip_core.memory_maps[0].address_blocks[0].registers
    assert regs[0].address_offset == 0
    assert regs[1].address_offset == 4  # 32 bits = 4 bytes
    assert regs[2].address_offset == 16  # 4 + 4 + 8 (reserved)


def test_bit_field_auto_offset(tmp_path):
    """Test automatic bit offset calculation for fields."""
    yaml_content = """
apiVersion: my-ip-schema/v2.3
vlnv:
    vendor: "test.com"
    library: "test"
    name: "field_test"
    version: "1.0.0"

memoryMaps:
    - name: "REGS"
      addressBlocks:
        - name: "BLOCK"
          baseAddress: 0x0
          range: 1024
          registers:
            - name: "REG"
              size: 32
              fields:
                - name: "FIELD0"
                  bitWidth: 1
                - name: "FIELD1"
                  bitWidth: 3
                - name: "FIELD2"
                  bitWidth: 8
"""
    yaml_file = tmp_path / "fields.yml"
    yaml_file.write_text(yaml_content)

    parser = YamlIpCoreParser()
    ip_core = parser.parse_file(yaml_file)

    fields = ip_core.memory_maps[0].address_blocks[0].registers[0].fields
    assert fields[0].bit_offset == 0
    assert fields[0].bit_width == 1
    assert fields[1].bit_offset == 1
    assert fields[1].bit_width == 3
    assert fields[2].bit_offset == 4  # 1 + 3
    assert fields[2].bit_width == 8
