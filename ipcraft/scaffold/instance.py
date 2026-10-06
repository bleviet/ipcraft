"""Component-instance snippets (port of the ``copyComponentInstance`` VS Code command)."""

from __future__ import annotations

import os
from typing import List

from .importers.verilog import extract_verilog_interface
from .importers.vhdl import extract_vhdl_interface


def build_vhdl_instance(content: str) -> str:
    iface = extract_vhdl_interface(content)
    name = iface["entityName"] or "unknown"
    params, ports = iface["parameters"], iface["ports"]
    lines: List[str] = [f"u_{name} : entity work.{name}"]
    if params:
        col = max(len(p["name"]) for p in params)
        lines.append("  generic map (")
        for i, p in enumerate(params):
            comma = "," if i < len(params) - 1 else ""
            lines.append(f"    {p['name'].ljust(col)} => {p['name']}{comma}")
        lines.append("  )")
    col = max((len(p["name"]) for p in ports), default=0)
    lines.append("  port map (")
    for i, p in enumerate(ports):
        comma = "," if i < len(ports) - 1 else ""
        lines.append(f"    {p['name'].ljust(col)} => {p['name']}{comma}")
    lines.append("  );")
    return "\n".join(lines)


def build_sv_instance(content: str) -> str:
    iface = extract_verilog_interface(content)
    name = iface["moduleName"] or "unknown"
    params, ports = iface["parameters"], iface["ports"]
    lines: List[str] = []
    if params:
        col = max(len(p["name"]) for p in params)
        lines.append(f"{name} #(")
        for i, p in enumerate(params):
            comma = "," if i < len(params) - 1 else ""
            lines.append(f"  .{p['name'].ljust(col)} ({p['name']}){comma}")
        lines.append(f") u_{name} (")
    else:
        lines.append(f"{name} u_{name} (")
    col = max((len(p["name"]) for p in ports), default=0)
    for i, p in enumerate(ports):
        comma = "," if i < len(ports) - 1 else ""
        lines.append(f"  .{p['name'].ljust(col)} ({p['name']}){comma}")
    lines.append(");")
    return "\n".join(lines)


def build_instance(path: str) -> str:
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    with open(path, encoding="utf-8") as fh:
        content = fh.read()
    if ext in ("vhd", "vhdl"):
        return build_vhdl_instance(content)
    if ext in ("sv", "v"):
        return build_sv_instance(content)
    raise ValueError("not a VHDL or SystemVerilog file")
