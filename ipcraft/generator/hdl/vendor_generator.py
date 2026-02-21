"""Vendor integration file generation mixin for ``IpCoreProjectGenerator``."""

from __future__ import annotations
from typing import TYPE_CHECKING, Dict

if TYPE_CHECKING:
    from ._protocols import GeneratorHost

from ipcraft.model.core import IpCore


class VendorGenerationMixin:
    """Mixin for Intel/Xilinx integration file generation."""

    def generate_intel_hw_tcl(self: GeneratorHost, ip_core: IpCore, bus_type: str = "axil") -> str:
        """Generate Intel Platform Designer ``_hw.tcl`` component file."""
        template = self.env.get_template("intel_hw_tcl.j2")
        context = self._get_template_context(ip_core, bus_type)
        context["vendor"] = ip_core.vlnv.vendor
        context["library"] = ip_core.vlnv.library
        context["version"] = ip_core.vlnv.version
        context["description"] = (
            ip_core.description if hasattr(ip_core, "description") else ""
        )
        context["author"] = ip_core.vlnv.vendor
        context["display_name"] = ip_core.vlnv.name.replace("_", " ").title()
        return template.render(**context)

    def generate_xilinx_component_xml(self: GeneratorHost, ip_core: IpCore) -> str:
        """Generate Xilinx Vivado IP-XACT ``component.xml``."""
        template = self.env.get_template("xilinx_component_xml.j2")
        context = self._get_template_context(ip_core, "axil")
        context["vendor"] = ip_core.vlnv.vendor
        context["library"] = ip_core.vlnv.library
        context["version"] = ip_core.vlnv.version
        context["description"] = (
            ip_core.description if hasattr(ip_core, "description") else ""
        )
        context["display_name"] = ip_core.vlnv.name.replace("_", " ").title()
        return template.render(**context)

    def generate_xilinx_xgui(self: GeneratorHost, ip_core: IpCore) -> str:
        """Generate Xilinx Vivado XGUI TCL file."""
        template = self.env.get_template("xilinx_xgui.j2")
        context = self._get_template_context(ip_core, "axil")
        return template.render(**context)

    def generate_vendor_files(
        self, ip_core: IpCore, vendor: str = "both", bus_type: str = "axil"
    ) -> Dict[str, str]:
        """Generate vendor-specific integration files."""
        name = ip_core.vlnv.name.lower()
        files: Dict[str, str] = {}

        if vendor in ["intel", "both"]:
            files[f"{name}_hw.tcl"] = self.generate_intel_hw_tcl(ip_core, bus_type)

        if vendor in ["xilinx", "both"]:
            files["component.xml"] = self.generate_xilinx_component_xml(ip_core)
            version_str = ip_core.vlnv.version.replace(".", "_")
            files[f"xilinx/xgui/{name}_v{version_str}.tcl"] = self.generate_xilinx_xgui(
                ip_core
            )

        return files
