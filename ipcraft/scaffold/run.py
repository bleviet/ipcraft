"""CLI-facing helpers for the scaffold engine (port of ``cli/generate.ts`` and ``cli/verify.ts``)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from .scaffolder import IpCoreScaffolder

DEFAULT_QUARTUS_DEVICE = "5CSEBA6U23I7"
DEFAULT_VIVADO_PART = "xc7z020clg484-1"
TARGET_IDS = ["vivado", "quartus"]


def parse_targets(values: Optional[List[str]]) -> List[str]:
    """Flatten repeated / comma-separated ``--target`` values."""
    out: List[str] = []
    for v in values or []:
        out.extend(s.strip() for s in v.split(",") if s.strip())
    return out


def build_generate_options(args: Any) -> Dict[str, Any]:
    """Translate parsed CLI args into ``IpCoreScaffolder.generate_all`` options."""
    targets = parse_targets(getattr(args, "target", None))
    include_quartus = "quartus" in targets
    include_vivado = "vivado" in targets
    opts: Dict[str, Any] = {
        "targets": targets,
        "includeRegs": getattr(args, "regs", True),
        "includeTestbench": getattr(args, "testbench", True),
        "hdlLanguage": getattr(args, "lang", None) or "vhdl",
        "scaffoldPack": getattr(args, "pack", None),
        "indentStyle": getattr(args, "indent_style", None),
        "indentSize": getattr(args, "indent_size", None),
        "includeQuartusProject": include_quartus,
        "includeVivadoProject": include_vivado,
    }
    if getattr(args, "framework", None):
        opts["framework"] = args.framework
    if getattr(args, "engine_sim", None):
        opts["engine"] = args.engine_sim
    if include_quartus:
        opts["quartusDevice"] = getattr(args, "quartus_device", None) or DEFAULT_QUARTUS_DEVICE
    if include_vivado:
        opts["targetPart"] = getattr(args, "vivado_part", None) or DEFAULT_VIVADO_PART
    return opts


def run_generate(args: Any, output_dir: str, dry_run: bool = False) -> Dict[str, Any]:
    """Generate (or preview) with the scaffold engine; raises ``RuntimeError`` on failure."""
    opts = build_generate_options(args)
    if dry_run:
        opts["dryRun"] = True
    result = IpCoreScaffolder().generate_all(os.path.abspath(args.input), os.path.abspath(output_dir), opts)
    if not result["success"]:
        raise RuntimeError(result.get("error") or "generation failed")
    return result


def _list_files_recursive(directory: str, rel_prefix: str = "") -> List[str]:
    files: List[str] = []
    try:
        entries = sorted(os.scandir(directory), key=lambda e: e.name)
    except OSError:
        return files
    for entry in entries:
        rel = f"{rel_prefix}/{entry.name}" if rel_prefix else entry.name
        if entry.is_dir():
            files.extend(_list_files_recursive(entry.path, rel))
        elif entry.is_file():
            files.append(rel)
    return files


def run_verify(args: Any, generated_dir: str) -> Dict[str, Any]:
    """Diff a fresh in-memory generation against ``generated_dir`` (``ipcraft verify``).

    Returns ``{"success": bool, "staleFiles": [...], "warnings": [...]}``; ``success`` is False and
    ``error`` is set when generation itself fails.
    """
    scaffolder = IpCoreScaffolder()
    ip_path = os.path.abspath(args.input)
    out = os.path.abspath(generated_dir)
    opts = build_generate_options(args)
    result = scaffolder.generate_all(ip_path, out, {**opts, "dryRun": True})
    if not result["success"] or "generatedContents" not in result:
        return {"success": False, "error": result.get("error")}
    protected = set(result.get("protectedPaths") or [])
    stale = set()
    for rel, fresh in result["generatedContents"].items():
        if rel in protected:
            continue
        try:
            on_disk = Path(os.path.join(out, rel)).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            stale.add(rel)
            continue
        if on_disk != fresh:
            stale.add(rel)

    user_managed = set(result.get("userManagedPaths") or [])
    union_opts = build_generate_options(_with_targets(args, TARGET_IDS))
    union = scaffolder.generate_all(ip_path, out, {**union_opts, "dryRun": True})
    scan_source = union["generatedContents"] if union["success"] and "generatedContents" in union else result["generatedContents"]
    top_dirs = {p.split("/")[0] for p in scan_source if "/" in p}
    for top in sorted(top_dirs):
        for rel in _list_files_recursive(os.path.join(out, top), top):
            if rel not in result["generatedContents"] and rel not in user_managed:
                stale.add(rel)
    return {"success": not stale, "staleFiles": sorted(stale), "warnings": result.get("warnings") or []}


class _ArgsView:
    def __init__(self, base: Any, **overrides: Any):
        self._base, self._overrides = base, overrides

    def __getattr__(self, name: str) -> Any:
        if name in self._overrides:
            return self._overrides[name]
        return getattr(self._base, name)


def _with_targets(args: Any, targets: List[str]) -> Any:
    return _ArgsView(args, target=targets)
