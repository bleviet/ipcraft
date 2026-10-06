"""Scaffold-pack utilities: listing, export ("eject") and template preview.

Ports of the ``exportScaffoldPack`` and ``previewTemplateOutput`` VS Code commands.
"""

from __future__ import annotations

import fnmatch
import os
import re
import shutil
from pathlib import Path
from typing import Dict, List, Optional

from .context import build_template_context
from .loader import load_bus_library, load_ip_core_data, check_bus_conformance, blocks_generation
from .packs import BUILTIN_PACKS_DIR, TEMPLATES_DIR, ScaffoldPackLoader, load_pack
from .registers import get_bus_type_for_template, has_memory_mapped_consumer_interface
from .templates_env import TemplateLoader, to_js


def list_packs(builtin_dir: str = str(BUILTIN_PACKS_DIR), extra_dirs: Optional[List[str]] = None) -> List[dict]:
    """Describe every pack found in the built-in directory and ``extra_dirs`` (workspace packs)."""
    out: List[dict] = []
    for directory, workspace in [(builtin_dir, False)] + [(d, True) for d in (extra_dirs or [])]:
        loader = ScaffoldPackLoader(directory)
        for name in loader.list_builtin_packs():
            pack = load_pack(os.path.join(directory, name))
            desc = (pack.get("description") or "").strip().split("\n")[0].strip()
            out.append({"name": pack["name"], "dir": pack["packDir"], "description": desc,
                        "category": pack.get("category") or ("workspace" if workspace else "builtin"),
                        "fullGeneration": pack["fullGeneration"]})
    return out


def _copy_dir(src: str, dest: str) -> None:
    os.makedirs(dest, exist_ok=True)
    for entry in os.scandir(src):
        target = os.path.join(dest, entry.name)
        if entry.is_dir():
            _copy_dir(entry.path, target)
        else:
            shutil.copyfile(entry.path, target)


def copy_referenced_templates(source_expressions: List[str], dest_dir: str, templates_dir: str = str(TEMPLATES_DIR)) -> List[str]:
    """Copy every built-in ``.j2`` template referenced by a pack into ``dest_dir`` (never overwriting)."""
    copied: List[str] = []
    seen = set()
    patterns = []
    for expr in source_expressions:
        if ".j2" not in expr:
            continue
        pattern = re.sub(r"\{\{[^}]+\}\}", "*", expr)
        if pattern not in seen:
            seen.add(pattern)
            patterns.append(pattern)
    names = sorted(f.name for f in os.scandir(templates_dir) if f.is_file())
    for pattern in patterns:
        for filename in fnmatch.filter(names, pattern):
            dest = os.path.join(dest_dir, filename)
            if os.path.exists(dest):
                continue
            shutil.copyfile(os.path.join(templates_dir, filename), dest)
            copied.append(filename)
    return copied


def export_pack(pack_name: str, dest_dir: str, builtin_dir: str = str(BUILTIN_PACKS_DIR)) -> Dict[str, object]:
    """Copy a built-in pack (and the templates it references) to ``dest_dir`` for editing."""
    src = os.path.join(builtin_dir, pack_name)
    if not os.path.exists(os.path.join(src, "scaffold.yml")):
        available = ", ".join(ScaffoldPackLoader(builtin_dir).list_builtin_packs())
        raise ValueError(f"Built-in scaffold pack '{pack_name}' not found. Available: {available}")
    if os.path.exists(os.path.join(dest_dir, "scaffold.yml")):
        raise ValueError(f"{dest_dir} already contains a scaffold pack; refusing to overwrite it")
    _copy_dir(src, dest_dir)
    pack = load_pack(dest_dir)
    copied = copy_referenced_templates([r["source"] for r in pack["files"]], dest_dir)
    return {"dest": dest_dir, "templates": copied}


def preview_template(template_path: str, ip_yml_path: str) -> str:
    """Render one ``.j2`` template against an IP core's template context."""
    ip_core = load_ip_core_data(ip_yml_path)
    library = load_bus_library(ip_yml_path, ip_core)
    report = check_bus_conformance(ip_core, library)
    if blocks_generation(report):
        raise ValueError("Generation blocked by bus interface conformance issues.")
    bus_type = get_bus_type_for_template(ip_core, library)
    ctx = build_template_context(ip_core, bus_type, ip_yml_path, library)
    ctx["has_memory_mapped_slave"] = has_memory_mapped_consumer_interface(ip_core, library)
    loader = TemplateLoader([os.path.dirname(os.path.abspath(template_path)), str(TEMPLATES_DIR)])
    return loader.render(os.path.basename(template_path), to_js(ctx))
