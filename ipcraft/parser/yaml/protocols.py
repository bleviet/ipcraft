"""Typing protocols for parser mixins."""

from typing import Any, Protocol

from ipcraft.model import AccessType


class ParserHostContext(Protocol):
    """Methods required by parser mixins from the main parser class."""

    def _parse_access(self, access: Any) -> AccessType:
        """Parse an access type string/enum."""
        ...
