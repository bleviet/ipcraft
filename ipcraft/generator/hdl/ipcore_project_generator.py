"""
IP core project generator using modular template structure.

Orchestrates the generation of all files needed for an IP core project:
- VHDL sources (package, top-level, core, bus wrapper, register file)
- Cocotb simulation files (testbench, Makefile)
- Memory map YAML for Python drivers
- Vendor integration files (Intel _hw.tcl, Xilinx component.xml)
- Structured project layout (rtl/, tb/, intel/, xilinx/)
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from jinja2 import Environment, FileSystemLoader

from ipcraft.generator.base_generator import BaseGenerator
from ipcraft.generator.hdl.fileset_manager import FileSetManagerMixin
from ipcraft.generator.hdl.testbench_generator import TestbenchGenerationMixin
from ipcraft.generator.hdl.vendor_generator import VendorGenerationMixin
from ipcraft.model.core import IpCore
from ipcraft.model.memory_map import BitFieldDef, MemoryMap, RegisterDef
from ipcraft.utils import BUS_DEFINITIONS_PATH, normalize_bus_type_key, parse_bit_range


class IpCoreProjectGenerator(
    BaseGenerator, VendorGenerationMixin, TestbenchGenerationMixin, FileSetManagerMixin
):
    """IP core project generator for memory-mapped register designs.

    Generates a complete project scaffold:
    - VHDL sources (package, top-level, core, bus wrapper, register file)
    - Cocotb simulation files (testbench, Makefile) via TestbenchGenerationMixin
    - Vendor integration files (Intel, Xilinx) via VendorGenerationMixin
    - File set management via FileSetManagerMixin
    """

    SUPPORTED_BUS_TYPES = ["axil", "avmm"]

    # Mapping from bus_definitions.yml type names to generator bus_type codes
    BUS_TYPE_MAP = {
        "AXI4L": "axil",
        "AVALON_MM": "avmm",
    }

    def __init__(self, template_dir: Optional[str] = None):
        """Initialize VHDL generator with templates."""
        if template_dir is None:
            template_dir = os.path.join(os.path.dirname(__file__), "templates")
        super().__init__(template_dir)
        self.bus_definitions = self._load_bus_definitions()

    def _load_bus_definitions(self) -> Dict[str, Any]:
        """Load bus definitions from ipcraft-spec/common/bus_definitions.yml."""
        bus_defs_path = BUS_DEFINITIONS_PATH
        if bus_defs_path.exists():
            with open(bus_defs_path) as f:
                return yaml.safe_load(f)
        return {}

    def _get_vhdl_port_type(self, width: int, logical_name: str) -> str:
        """Get VHDL type string for a port based on width.

        For address and data ports, use parameterized widths (C_ADDR_WIDTH, C_DATA_WIDTH).
        """
        # Parameterized ports
        if logical_name in ["AWADDR", "ARADDR", "address"]:
            return "std_logic_vector(C_ADDR_WIDTH-1 downto 0)"
        if logical_name in ["WDATA", "RDATA", "writedata", "readdata"]:
            return "std_logic_vector(C_DATA_WIDTH-1 downto 0)"
        if logical_name == "WSTRB":
            return "std_logic_vector((C_DATA_WIDTH/8)-1 downto 0)"

        # Standard widths
        if width == 1:
            return "std_logic"
        return f"std_logic_vector({width - 1} downto 0)"

    def _get_active_bus_ports(
        self,
        bus_type_name: str,
        use_optional_ports: List[str],
        physical_prefix: str,
        mode: str,
        port_width_overrides: Optional[Dict[str, int]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get list of active bus ports based on required + selected optional ports.

        Args:
            bus_type_name: Bus type name from bus_definitions (e.g., 'AXI4L')
            use_optional_ports: List of optional port names to include
            physical_prefix: Prefix for physical port names (e.g., 's_axi_')
            mode: Interface mode ('master' or 'slave')

        Returns:
            List of port dictionaries for template rendering
        """
        bus_def = self.bus_definitions.get(bus_type_name.upper(), {})
        ports = bus_def.get("ports", [])
        active_ports = []

        for port in ports:
            logical_name = port["name"]

            # Skip clock/reset (handled separately)
            if logical_name in ["ACLK", "ARESETn", "clk", "reset"]:
                continue

            presence = port.get("presence", "required")
            is_required = presence == "required"
            is_selected = logical_name in use_optional_ports

            if is_required or is_selected:
                # Get direction from bus definition
                direction = port.get("direction", "in")

                # Flip direction for slave mode (bus def is from master perspective)
                if mode == "slave":
                    direction = "in" if direction == "out" else "out"

                width = port.get("width", 1)

                # Apply width overrides
                if port_width_overrides and logical_name in port_width_overrides:
                    width = port_width_overrides[logical_name]

                active_ports.append(
                    {
                        "logical_name": logical_name,
                        "name": f"{physical_prefix}{logical_name.lower()}",
                        "direction": direction,
                        "width": width,
                        "type": self._get_vhdl_port_type(width, logical_name),
                    }
                )

        return active_ports

    def _parse_bits(self, bits: str) -> dict:
        """Parse bit string [M:N] or [N] into offset and width."""
        if not bits:
            return {"offset": 0, "width": 1}
        try:
            offset, width = parse_bit_range(bits)
            return {"offset": offset, "width": width}
        except ValueError:
            return {"offset": 0, "width": 1}

    def _prepare_registers(self, ip_core: IpCore) -> List[Dict[str, Any]]:
        """
        Extract and prepare register information from memory maps (recursively).
        """
        registers = []

        def process_register(reg, base_offset, prefix):
            current_offset = base_offset + (
                getattr(reg, "address_offset", None) or getattr(reg, "offset", None) or 0
            )
            reg_name = reg.name if hasattr(reg, "name") else "REG"

            # Check for nested registers (array/group)
            nested_regs = getattr(reg, "registers", [])
            if nested_regs:
                count = getattr(reg, "count", 1) or 1
                stride = getattr(reg, "stride", 0) or 0

                for i in range(count):
                    instance_offset = current_offset + (i * stride)
                    instance_prefix = (
                        f"{prefix}{reg_name}_{i}_" if count > 1 else f"{prefix}{reg_name}_"
                    )

                    for child in nested_regs:
                        process_register(child, instance_offset, instance_prefix)
                return

            # Leaf register processing
            fields = []
            for field in getattr(reg, "fields", []):
                # Handle bit parsing
                bit_offset = getattr(field, "bit_offset", None)
                bit_width = getattr(field, "bit_width", None)

                if bit_offset is None or bit_width is None:
                    bits_str = getattr(field, "bits", "")
                    parsed = self._parse_bits(bits_str)
                    if bit_offset is None:
                        bit_offset = parsed["offset"]
                    if bit_width is None:
                        bit_width = parsed["width"]

                # Access normalization
                acc = getattr(field, "access", "read-write")
                acc_str = acc.value if hasattr(acc, "value") else str(acc)
                reg_acc = getattr(reg, "access", "read-write")
                reg_acc_str = reg_acc.value if hasattr(reg_acc, "value") else str(reg_acc)

                fields.append(
                    {
                        "name": field.name,
                        "offset": bit_offset,
                        "width": bit_width,
                        "access": acc_str.lower() if acc_str else reg_acc_str.lower(),
                        "reset_value": (
                            field.reset_value
                            if getattr(field, "reset_value", None) is not None
                            else 0
                        ),
                        "description": getattr(field, "description", ""),
                    }
                )

            reg_acc = getattr(reg, "access", "read-write")
            reg_acc_str = reg_acc.value if hasattr(reg_acc, "value") else str(reg_acc)

            registers.append(
                {
                    "name": prefix + reg_name,
                    "offset": current_offset,
                    "access": reg_acc_str.lower(),
                    "description": getattr(reg, "description", ""),
                    "fields": fields,
                }
            )

        for mm in ip_core.memory_maps:
            for block in mm.address_blocks:
                block_offset = getattr(block, "base_address", 0) or getattr(block, "offset", 0) or 0
                for reg in block.registers:
                    process_register(reg, block_offset, "")

        return sorted(registers, key=lambda x: x["offset"])

    def _prepare_generics(self, ip_core: IpCore) -> List[Dict[str, Any]]:
        """Prepare generics/parameters for templates."""
        generics = []
        for param in ip_core.parameters:
            generics.append(
                {
                    "name": param.name,
                    "type": (
                        param.data_type.value
                        if hasattr(param.data_type, "value")
                        else str(param.data_type)
                    ),
                    "default_value": param.value,
                }
            )
        return generics

    def _prepare_user_ports(self, ip_core: IpCore) -> List[Dict[str, Any]]:
        """Prepare user-defined ports (non-bus ports)."""
        # Build parameter lookup for default values
        param_defaults = {param.name: param.value for param in ip_core.parameters}

        ports = []
        for port in ip_core.ports:
            direction = (
                port.direction.value if hasattr(port.direction, "value") else str(port.direction)
            )
            width = port.width if hasattr(port, "width") else 1

            # Check if width is a parameter reference (string) or a number
            is_parameterized = isinstance(width, str)
            if is_parameterized:
                # Width is a parameter reference - use it directly in VHDL
                port_type = f"std_logic_vector({width}-1 downto 0)"
                width_expr = width  # Store the parameter name
                numeric_width = None  # No numeric value for XML
                # Get default value for the parameter to use in XML
                default_value = param_defaults.get(width, 32) - 1
            elif width == 1:
                port_type = "std_logic"
                width_expr = None
                numeric_width = 1
                default_value = None
            else:
                port_type = f"std_logic_vector({width-1} downto 0)"
                width_expr = None
                numeric_width = width
                default_value = None

            ports.append(
                {
                    "name": port.name.lower(),
                    "direction": direction.lower(),
                    "type": port_type,
                    "width": numeric_width,
                    "width_expr": width_expr,
                    "is_parameterized": is_parameterized,
                    "default_width": default_value,
                }
            )
        return ports

    def _expand_bus_interfaces(self, ip_core: IpCore) -> List[Dict[str, Any]]:
        """
        Expand bus interfaces (including arrays) into a flat list of interface dictionaries.
        """
        expanded = []
        if not ip_core.bus_interfaces:
            return []

        for iface in ip_core.bus_interfaces:
            array_def = getattr(iface, "array", None)

            if array_def:
                count = getattr(array_def, "count", 1)
                start = getattr(array_def, "index_start", 0)

                for i in range(count):
                    idx = start + i
                    name_pattern = getattr(array_def, "naming_pattern", f"{iface.name}_{{index}}")
                    name = name_pattern.format(index=idx)

                    prefix_pattern = getattr(
                        array_def, "physical_prefix_pattern", f"{iface.physical_prefix}{{index}}_"
                    )
                    prefix = prefix_pattern.format(index=idx)

                    expanded.append(
                        {
                            "name": name,
                            "type": iface.type,
                            "mode": (
                                iface.mode.value
                                if hasattr(iface.mode, "value")
                                else str(iface.mode)
                            ),
                            "physical_prefix": prefix,
                            "use_optional_ports": iface.use_optional_ports or [],
                            "port_width_overrides": iface.port_width_overrides or {},
                            "associated_clock": iface.associated_clock,
                            "associated_reset": iface.associated_reset,
                        }
                    )
            else:
                expanded.append(
                    {
                        "name": iface.name,
                        "type": iface.type,
                        "mode": (
                            iface.mode.value if hasattr(iface.mode, "value") else str(iface.mode)
                        ),
                        "physical_prefix": iface.physical_prefix or "s_axi_",
                        "use_optional_ports": iface.use_optional_ports or [],
                        "port_width_overrides": iface.port_width_overrides or {},
                        "associated_clock": iface.associated_clock,
                        "associated_reset": iface.associated_reset,
                    }
                )
        return expanded

    def _get_template_context(self, ip_core: IpCore, bus_type: str = "axil") -> Dict[str, Any]:
        """Build common template context."""
        registers = self._prepare_registers(ip_core)

        sw_access = ["read-write", "write-only", "rw", "wo"]
        hw_access = ["read-only", "ro"]

        sw_registers = [r for r in registers if r["access"] in sw_access]
        hw_registers = [r for r in registers if r["access"] in hw_access]

        # Extract clock and reset information
        clock_port = ip_core.clocks[0].name if ip_core.clocks else "clk"
        reset_port = ip_core.resets[0].name if ip_core.resets else "rst"
        reset_polarity = ip_core.resets[0].polarity.value if ip_core.resets else "activeHigh"
        reset_active_high = "High" in reset_polarity

        # Generic expansion of ALL bus interfaces
        all_ifaces = self._expand_bus_interfaces(ip_core)
        expanded_bus_interfaces = []
        secondary_bus_ports = []
        bus_ports = []
        bus_prefix = "s_axi"

        if all_ifaces:
            # Primary bus is assumed to be the first one (index 0)
            # This aligns with the 'bus_type' argument which typically controls the Wrapper generation for the Primary bus.
            primary_iface = all_ifaces[0]
            bus_prefix = (
                primary_iface["physical_prefix"][:-1]
                if primary_iface["physical_prefix"].endswith("_")
                else primary_iface["physical_prefix"]
            )

            for i, iface in enumerate(all_ifaces):
                # Map type name
                bus_type_key = normalize_bus_type_key(iface["type"])

                active_ports = self._get_active_bus_ports(
                    bus_type_name=bus_type_key,
                    use_optional_ports=iface["use_optional_ports"],
                    physical_prefix=iface["physical_prefix"],
                    mode=iface["mode"],
                    port_width_overrides=iface["port_width_overrides"],
                )

                # Store ports in the interface dict for templates
                iface["ports"] = active_ports
                expanded_bus_interfaces.append(iface)

                if i == 0:
                    # Primary bus ports (for wrapper)
                    bus_ports = active_ports
                else:
                    # Secondary bus ports (for core entity)
                    secondary_bus_ports.extend(active_ports)

        return {
            "entity_name": ip_core.vlnv.name.lower(),
            "registers": registers,
            "sw_registers": sw_registers,
            "hw_registers": hw_registers,
            "generics": self._prepare_generics(ip_core),
            "user_ports": self._prepare_user_ports(ip_core),
            "bus_type": bus_type,
            "bus_ports": bus_ports,
            "secondary_bus_ports": secondary_bus_ports,
            "expanded_bus_interfaces": expanded_bus_interfaces,
            "bus_prefix": bus_prefix if ip_core.bus_interfaces else "s_axi",
            "data_width": 32,
            "addr_width": 8,
            "reg_width": 4,
            "memory_maps": ip_core.memory_maps,
            "clock_port": clock_port,
            "reset_port": reset_port,
            "reset_active_high": reset_active_high,
            # Relative path from tb/ directory to memmap file (2 levels up for structured output)
            "memmap_relpath": f"../../{ip_core.vlnv.name.lower()}.mm.yml",
        }

    def generate_package(self, ip_core: IpCore) -> str:
        """Generate VHDL package with register types and conversion functions."""
        template = self.env.get_template("package.vhdl.j2")
        context = self._get_template_context(ip_core)
        return template.render(**context)

    def generate_top(self, ip_core: IpCore, bus_type: str = "axil") -> str:
        """Generate top-level entity that instantiates core and bus wrapper."""
        if bus_type not in self.SUPPORTED_BUS_TYPES:
            raise ValueError(
                f"Unsupported bus type: {bus_type}. Supported: {self.SUPPORTED_BUS_TYPES}"
            )

        template = self.env.get_template("top.vhdl.j2")
        context = self._get_template_context(ip_core, bus_type)
        return template.render(**context)

    def generate_core(self, ip_core: IpCore) -> str:
        """Generate core logic module (bus-agnostic)."""
        template = self.env.get_template("core.vhdl.j2")
        context = self._get_template_context(ip_core)
        return template.render(**context)

    def generate_bus_wrapper(self, ip_core: IpCore, bus_type: str) -> str:
        """Generate bus interface wrapper for register access."""
        if bus_type not in self.SUPPORTED_BUS_TYPES:
            raise ValueError(
                f"Unsupported bus type: {bus_type}. Supported: {self.SUPPORTED_BUS_TYPES}"
            )

        template = self.env.get_template(f"bus_{bus_type}.vhdl.j2")
        context = self._get_template_context(ip_core, bus_type)
        return template.render(**context)

    def generate_register_file(self, ip_core: IpCore) -> str:
        """Generate standalone register file (bus-agnostic)."""
        template = self.env.get_template("register_file.vhdl.j2")
        context = self._get_template_context(ip_core)
        return template.render(**context)

    def generate_all(
        self,
        ip_core: IpCore,
        bus_type: str = "axil",
        include_regs: bool = False,
        structured: bool = False,
        vendor: str = "none",
        include_testbench: bool = False,
    ) -> Dict[str, str]:
        """
        Generate all VHDL files for the IP core.

        Args:
            ip_core: IP core definition
            bus_type: Bus interface type ('axil' or 'avmm')
            include_regs: Include standalone register bank
            structured: Use organized folder structure (rtl/, tb/, intel/, xilinx/)
            vendor: Vendor files to include ('none', 'intel', 'xilinx', 'both')
            include_testbench: Include cocotb testbench files

        Returns:
            Dictionary mapping filename to content
        """
        if structured:
            return self.generate_all_with_structure(
                ip_core, bus_type, include_regs, vendor, include_testbench
            )

        name = ip_core.vlnv.name.lower()

        files = {
            f"{name}_pkg.vhd": self.generate_package(ip_core),
            f"{name}.vhd": self.generate_top(ip_core, bus_type),
            f"{name}_core.vhd": self.generate_core(ip_core),
            f"{name}_{bus_type}.vhd": self.generate_bus_wrapper(ip_core, bus_type),
        }

        if include_regs:
            files[f"{name}_regs.vhd"] = self.generate_register_file(ip_core)

        return files

    def generate_all_with_structure(
        self,
        ip_core: IpCore,
        bus_type: str = "axil",
        include_regs: bool = False,
        vendor: str = "none",
        include_testbench: bool = False,
    ) -> Dict[str, str]:
        """
        Generate all files with organized folder structure (VSCode extension compatible).

        Args:
            ip_core: IP core definition
            bus_type: Bus interface type ('axil' or 'avmm')
            include_regs: Include standalone register bank
            vendor: Vendor files to include ('none', 'intel', 'xilinx', 'both')
            include_testbench: Include cocotb testbench files

        Returns:
            Dictionary mapping full path (with subdirs) to content
            Paths use format: 'rtl/file.vhd', 'tb/file.py', etc.
        """
        name = ip_core.vlnv.name.lower()
        files = {}

        # RTL files (VHDL sources)
        files[f"rtl/{name}_pkg.vhd"] = self.generate_package(ip_core)
        files[f"rtl/{name}.vhd"] = self.generate_top(ip_core, bus_type)
        files[f"rtl/{name}_core.vhd"] = self.generate_core(ip_core)
        files[f"rtl/{name}_{bus_type}.vhd"] = self.generate_bus_wrapper(ip_core, bus_type)

        if include_regs:
            files[f"rtl/{name}_regs.vhd"] = self.generate_register_file(ip_core)

        # Testbench files
        if include_testbench:
            files[f"tb/{name}_test.py"] = self.generate_cocotb_test(ip_core, bus_type)
            files[f"tb/Makefile"] = self.generate_cocotb_makefile(ip_core, bus_type)

        # Vendor integration files
        if vendor in ["intel", "both"]:
            files[f"intel/{name}_hw.tcl"] = self.generate_intel_hw_tcl(ip_core, bus_type)

        if vendor in ["xilinx", "both"]:
            files[f"xilinx/component.xml"] = self.generate_xilinx_component_xml(ip_core)
            # Generate XGUI file with version in filename
            version_str = ip_core.vlnv.version.replace(".", "_")
            files[f"xilinx/xgui/{name}_v{version_str}.tcl"] = self.generate_xilinx_xgui(ip_core)

        return files


# Backward compatibility alias
VHDLGenerator = IpCoreProjectGenerator


# Backward compatibility: standalone function
def generate_vhdl(ip_core: IpCore, bus_type: str = "axil") -> Dict[str, str]:
    """
    Generate VHDL files for an IP core.

    Args:
        ip_core: IP core definition
        bus_type: Bus interface type

    Returns:
        Dictionary mapping filename to content
    """
    generator = IpCoreProjectGenerator()
    return generator.generate_all(ip_core, bus_type)
