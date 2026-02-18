"""
FileSet definitions for IP cores.
"""

from enum import Enum
from pathlib import Path
from typing import List

from pydantic import Field, field_validator

from .base import StrictModel


class FileType(str, Enum):
    """File type enumeration."""

    # HDL Sources
    VHDL = "vhdl"
    VERILOG = "verilog"
    SYSTEMVERILOG = "systemverilog"

    # Constraints
    XDC = "xdc"
    SDC = "sdc"
    UCF = "ucf"

    # Software/Scripts
    C_HEADER = "cHeader"
    C_SOURCE = "cSource"
    CPP_HEADER = "cppHeader"
    CPP_SOURCE = "cppSource"
    PYTHON = "python"
    MAKEFILE = "makefile"

    # Documentation
    PDF = "pdf"
    MARKDOWN = "markdown"
    TEXT = "text"

    # Configuration
    TCL = "tcl"
    YAML = "yaml"
    JSON = "json"
    XML = "xml"

    # Other
    UNKNOWN = "unknown"


class File(StrictModel):
    """
    File reference within a file set.

    Represents a file that is part of the IP core (source, constraint, doc, etc.).
    """

    path: str = Field(..., description="Relative or absolute file path")
    type: FileType = Field(..., description="File type")
    description: str = Field(default="", description="File description")
    is_include_file: bool = Field(default=False, description="Whether file is an include file")
    logical_name: str = Field(default="", description="Logical name (e.g., library name for VHDL)")

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: str) -> str:
        """Ensure path is not empty."""
        if not v or not v.strip():
            raise ValueError("File path cannot be empty")
        return v.strip()

    @property
    def file_name(self) -> str:
        """Get file name from path."""
        return Path(self.path).name

    @property
    def file_extension(self) -> str:
        """Get file extension."""
        return Path(self.path).suffix.lstrip(".")

    @property
    def is_hdl(self) -> bool:
        """Check if file is HDL source."""
        return self.type in [FileType.VHDL, FileType.VERILOG, FileType.SYSTEMVERILOG]

    @property
    def is_constraint(self) -> bool:
        """Check if file is constraint."""
        return self.type in [FileType.XDC, FileType.SDC, FileType.UCF]

    @property
    def is_software(self) -> bool:
        """Check if file is software source."""
        return self.type in [
            FileType.C_HEADER,
            FileType.C_SOURCE,
            FileType.CPP_HEADER,
            FileType.CPP_SOURCE,
        ]

    @property
    def is_documentation(self) -> bool:
        """Check if file is documentation."""
        return self.type in [FileType.PDF, FileType.MARKDOWN, FileType.TEXT]


class FileSet(StrictModel):
    """
    Named collection of files for an IP core.

    Groups related files together (e.g., RTL sources, C API, documentation).
    """

    name: str = Field(..., description="File set name")
    description: str = Field(default="", description="File set description")
    files: List[File] = Field(default_factory=list, description="Files in this set")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Ensure name is not empty."""
        if not v or not v.strip():
            raise ValueError("FileSet name cannot be empty")
        return v.strip()

    @property
    def hdl_files(self) -> List[File]:
        """Get all HDL files in this set."""
        return [f for f in self.files if f.is_hdl]

    @property
    def constraint_files(self) -> List[File]:
        """Get all constraint files in this set."""
        return [f for f in self.files if f.is_constraint]

    @property
    def software_files(self) -> List[File]:
        """Get all software files in this set."""
        return [f for f in self.files if f.is_software]

    @property
    def documentation_files(self) -> List[File]:
        """Get all documentation files in this set."""
        return [f for f in self.files if f.is_documentation]
