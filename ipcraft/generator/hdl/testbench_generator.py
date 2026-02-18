"""Testbench and simulation file generation mixin for ``IpCoreProjectGenerator``."""

from typing import Dict

from ipcraft.model.core import IpCore


class TestbenchGenerationMixin:
    """Mixin for cocotb testbench and simulation file generation.

    Generates:
    - Cocotb Python test files
    - Simulation Makefiles
    - Memory map YAML for Python drivers
    """

    def generate_cocotb_test(self, ip_core: IpCore, bus_type: str = "axil") -> str:
        """Generate cocotb Python test file."""
        template = self.env.get_template("cocotb_test.py.j2")
        context = self._get_template_context(ip_core, bus_type)
        return template.render(**context)

    def generate_cocotb_makefile(self, ip_core: IpCore, bus_type: str = "axil") -> str:
        """Generate Makefile for cocotb simulation."""
        template = self.env.get_template("cocotb_makefile.j2")
        context = self._get_template_context(ip_core, bus_type)
        return template.render(**context)

    def generate_memmap_yaml(self, ip_core: IpCore) -> str:
        """Generate memory map YAML for Python driver."""
        template = self.env.get_template("memmap.yml.j2")
        context = self._get_template_context(ip_core)
        return template.render(**context)

    def generate_testbench(self, ip_core: IpCore, bus_type: str = "axil") -> Dict[str, str]:
        """Generate testbench files for cocotb simulation.

        Args:
            ip_core: IP core definition
            bus_type: Bus interface type

        Returns:
            Dictionary mapping filename to content
        """
        name = ip_core.vlnv.name.lower()
        return {
            f"{name}_test.py": self.generate_cocotb_test(ip_core, bus_type),
            "Makefile": self.generate_cocotb_makefile(ip_core, bus_type),
        }
