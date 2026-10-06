"""Indentation control for generated HDL and tool-script sources.

Port of ``reindent.ts`` from ipcraft-vscode. The built-in templates are written with
``TEMPLATE_INDENT_UNIT_SIZE`` spaces per level; each leading run of spaces is rewritten
to the requested unit while a trailing alignment remainder is preserved.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Dict, Optional

DEFAULT_INDENT_STYLE = "spaces"
DEFAULT_INDENT_SIZE = 2

# Spaces per indentation level baked into the built-in .j2 templates.
TEMPLATE_INDENT_UNIT_SIZE = 4

REINDENTED_EXTENSIONS = {".vhd", ".vhdl", ".v", ".vh", ".sv", ".svh", ".tcl", ".xdc", ".sdc"}

_LEADING_SPACES = re.compile(r"^ +", re.MULTILINE)


def create_indent_unit(style: str, size: int) -> str:
    if style == "tab":
        return "\t"
    if style != "spaces":
        raise ValueError(f"Indent style must be 'spaces' or 'tab', received {style!r}")
    if not isinstance(size, int) or size < 1:
        raise ValueError(f"Indent size must be a positive integer, received {size}")
    return " " * size


def reindent_source(text: str, unit: str, template_unit_size: int = TEMPLATE_INDENT_UNIT_SIZE) -> str:
    if unit == " " * template_unit_size:
        return text

    def repl(match: "re.Match[str]") -> str:
        n = len(match.group(0))
        return unit * (n // template_unit_size) + " " * (n % template_unit_size)

    return _LEADING_SPACES.sub(repl, text)


def should_reindent_source(file_path: str) -> bool:
    return PurePosixPath(file_path).suffix.lower() in REINDENTED_EXTENSIONS


def reindent_generated_sources(
    files: Dict[str, str],
    style: Optional[str] = None,
    size: Optional[int] = None,
    template_unit_size: int = TEMPLATE_INDENT_UNIT_SIZE,
) -> Dict[str, str]:
    """Reindent every source file in ``files``; a no-op when neither option is given."""
    if style is None and size is None:
        return files
    unit = create_indent_unit(style or DEFAULT_INDENT_STYLE, size or DEFAULT_INDENT_SIZE)
    return {
        path: reindent_source(content, unit, template_unit_size)
        if should_reindent_source(path)
        else content
        for path, content in files.items()
    }
