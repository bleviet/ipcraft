"""Synthesis-vendor toolchains (Vivado, Quartus) — file scaffolding only."""

from __future__ import annotations

from typing import Dict, List, Optional

from .quartus import QuartusToolchain
from .vivado import VivadoToolchain

_TOOLCHAINS = [VivadoToolchain(), QuartusToolchain()]


def get_toolchain(id_: str):
    return next((t for t in _TOOLCHAINS if t.id == id_), None)


def list_all() -> List:
    return list(_TOOLCHAINS)
