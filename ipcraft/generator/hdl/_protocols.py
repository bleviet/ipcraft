"""Typing protocols for generator mixins."""

from __future__ import annotations
from typing import Any, Dict, Protocol

from jinja2 import Environment

from ipcraft.model.core import IpCore


class GeneratorHost(Protocol):
    """Protocol for the host class that generator mixins expect."""

    env: Environment

    def _get_template_context(
        self, ip_core: IpCore, bus_type: str = "axil"
    ) -> Dict[str, Any]:
        """Build common template context."""
        ...
