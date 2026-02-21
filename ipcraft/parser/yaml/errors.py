"""Shared parser exceptions for YAML parsing."""

from pathlib import Path
from typing import Optional


class ParseError(Exception):
    """Error during YAML parsing."""

    def __init__(
        self, message: str, file_path: Optional[Path] = None, line: Optional[int] = None
    ):
        self.file_path = file_path
        self.line = line
        super().__init__(self._format_message(message))

    def _format_message(self, message: str) -> str:
        """Format error message with file and line information."""
        parts = []
        if self.file_path:
            parts.append(f"File: {self.file_path}")
        if self.line is not None:
            parts.append(f"Line: {self.line}")
        parts.append(message)
        return " | ".join(parts)
