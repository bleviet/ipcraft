"""
Base generator interface for HDL code generation.

Provides abstract interface for language-specific generators (VHDL, Verilog, etc.)
to implement, ensuring consistent API across all generators.

NOTE: This is an intentionally abstract class for future extensibility.
Current implementations:
- IpCoreProjectGenerator: Full VHDL generation support (ipcraft.generator.hdl.ipcore_project_generator)

Future planned implementations:
- VerilogGenerator: For SystemVerilog/Verilog generation
- ChiselGenerator: For Chisel HDL generation
"""

import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Optional, Union

from jinja2 import Environment, FileSystemLoader

# Support both legacy IPCore and new IpCore models
from ipcraft.model.core import IpCore


class BaseGenerator(ABC):
    """
    Abstract base class for HDL code generators.

    Subclasses must implement language-specific generation methods.
    Templates are loaded from a 'templates' subdirectory.
    """

    def __init__(self, template_dir: Optional[str] = None):
        """
        Initialize the generator with Jinja2 environment.

        Args:
            template_dir: Optional custom template directory.
                                                    Defaults to 'templates' subdirectory of concrete generator.
        """
        if template_dir is None:
            # Default: templates directory relative to concrete class file
            template_dir = os.path.join(os.path.dirname(__file__), "templates")

        self.template_dir = template_dir
        self.env = Environment(
            loader=FileSystemLoader(template_dir),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    @abstractmethod
    def generate_package(self, ip_core: IpCore) -> str:
        """
        Generate package file with types, constants, and component declarations.

        Args:
            ip_core: IP core definition

        Returns:
            Package file content as string
        """
        pass

    @abstractmethod
    def generate_top(self, ip_core: IpCore, bus_type: str = "axil") -> str:
        """
        Generate top-level entity that instantiates core and bus wrapper.

        Args:
            ip_core: IP core definition
            bus_type: Bus interface type ('axil', 'avmm', 'apb')

        Returns:
            Top-level file content as string
        """
        pass

    @abstractmethod
    def generate_core(self, ip_core: IpCore) -> str:
        """
        Generate core logic module (bus-agnostic).

        Args:
            ip_core: IP core definition

        Returns:
            Core module file content as string
        """
        pass

    @abstractmethod
    def generate_bus_wrapper(self, ip_core: IpCore, bus_type: str) -> str:
        """
        Generate bus interface wrapper for register access.

        Args:
            ip_core: IP core definition
            bus_type: Bus interface type ('axil', 'avmm', 'apb')

        Returns:
            Bus wrapper file content as string
        """
        pass

    def generate_all(self, ip_core: IpCore, bus_type: str = "axil") -> Dict[str, str]:
        """
        Generate all HDL files for the IP core.

        Args:
            ip_core: IP core definition
            bus_type: Bus interface type

        Returns:
            Dictionary mapping filename to content
        """
        name = ip_core.vlnv.name.lower()
        files = {
            f"{name}_pkg.vhd": self.generate_package(ip_core),
            f"{name}.vhd": self.generate_top(ip_core, bus_type),
            f"{name}_core.vhd": self.generate_core(ip_core),
            f"{name}_{bus_type}.vhd": self.generate_bus_wrapper(ip_core, bus_type),
        }
        return files

    def write_files(
        self, ip_core: IpCore, output_dir: Union[str, Path], bus_type: str = "axil"
    ) -> Dict[str, Path]:
        """
        Generate and write all HDL files to output directory.

        Args:
            ip_core: IP core definition
            output_dir: Output directory path
            bus_type: Bus interface type

        Returns:
            Dictionary mapping filename to written file path
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        files = self.generate_all(ip_core, bus_type)
        written = {}

        for filename, content in files.items():
            file_path = output_path / filename
            # Create parent directories if needed (for structured paths like 'rtl/file.vhd')
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content)
            written[filename] = file_path

        return written
