"""Scaffold packs: manifest loading, compatibility checks and output-path safety.

Port of ``ScaffoldPackLoader.ts``, ``scaffoldPackOwnership.ts`` and ``contract/{version,requirements}.ts``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .context import CONTRACT_VERSION

RESOURCES_DIR = Path(__file__).parent / "resources"
BUILTIN_PACKS_DIR = RESOURCES_DIR / "packs"
TEMPLATES_DIR = RESOURCES_DIR / "templates"


class ScaffoldPack(dict):
    """A scaffold pack manifest; attribute access mirrors the TypeScript interface."""

    def __getattr__(self, item: str) -> Any:
        try:
            return self[item]
        except KeyError:
            raise AttributeError(item) from None


def resolve_scaffold_output_path(output_dir: str, target: str) -> str:
    """Resolve a rendered scaffold target beneath ``output_dir`` or raise."""
    canonical = os.path.abspath(output_dir)

    def fail(reason: str):
        raise ValueError(f"Unsafe scaffold output target {target!r}: {reason}. "
                         f"Target must be a relative file path inside {canonical!r}.")

    if not target.strip():
        fail("target is empty")
    if re.match(r"^[\\/]", target) or re.match(r"^[A-Za-z]:", target):
        fail("absolute, drive-qualified, and UNC paths are not allowed")
    segments = re.split(r"[\\/]", target)
    if ".." in segments:
        fail("path traversal is not allowed")
    relative = os.sep.join(s for s in segments if s not in ("", "."))
    if not relative:
        fail("target resolves to the output directory itself")
    resolved = os.path.abspath(os.path.join(canonical, relative))
    rel = os.path.relpath(resolved, canonical)
    if rel in ("", "..") or rel.startswith(".." + os.sep) or os.path.isabs(rel):
        fail("resolved path is outside the output directory")
    return resolved


def _parse_requirements(raw: Any) -> Optional[dict]:
    if not isinstance(raw, dict):
        return None

    def strs(v: Any) -> Optional[List[str]]:
        return [str(x) for x in v] if isinstance(v, list) else None

    mm = raw.get("memoryMappedSlave")
    return {
        "hdlLanguages": strs(raw.get("hdlLanguages")),
        "busTypes": strs(raw.get("busTypes")),
        "memoryMappedSlave": mm if mm in ("required", "forbidden") else None,
        "logicalPorts": strs(raw.get("logicalPorts")),
    }


def _parse_indentation(raw: Any, pack_name: str) -> Optional[dict]:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError(f"Scaffold pack '{pack_name}' declares an invalid generation.indentation {raw!r}: "
                         f"expected an object with optional 'style' and 'size' fields.")
    out: Dict[str, Any] = {}
    if raw.get("style") is not None:
        if raw["style"] not in ("spaces", "tab"):
            raise ValueError(f"Scaffold pack '{pack_name}' declares an invalid generation.indentation.style "
                             f"{raw['style']!r}: expected 'spaces' or 'tab'.")
        out["style"] = raw["style"]
    if raw.get("size") is not None:
        size = raw["size"]
        if isinstance(size, bool) or not isinstance(size, int) or size < 1:
            raise ValueError(f"Scaffold pack '{pack_name}' declares an invalid generation.indentation.size "
                             f"{size!r}: expected a positive integer.")
        out["size"] = size
    return out


def _parse_generation(raw: Any, pack_name: str) -> Optional[dict]:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError(f"Scaffold pack '{pack_name}' declares an invalid generation block {raw!r}: expected an object.")
    indentation = _parse_indentation(raw.get("indentation"), pack_name)
    return {"indentation": indentation} if indentation is not None else None


def load_pack(pack_dir: str) -> ScaffoldPack:
    manifest = os.path.join(pack_dir, "scaffold.yml")
    parsed = yaml.safe_load(Path(manifest).read_text(encoding="utf-8")) or {}
    name = str(parsed.get("name") if parsed.get("name") is not None else os.path.basename(pack_dir))
    files = []
    for f in parsed.get("files") or []:
        files.append({
            "source": str(f.get("source") if f.get("source") is not None else ""),
            "target": str(f.get("target") if f.get("target") is not None else ""),
            "condition": str(f["condition"]) if f.get("condition") is not None else None,
            "managed": bool(f["managed"]) if f.get("managed") is not None else True,
            "executable": bool(f["executable"]) if f.get("executable") is not None else None,
        })
    return ScaffoldPack(
        name=name,
        description=str(parsed["description"]) if parsed.get("description") is not None else None,
        category=str(parsed["category"]) if parsed.get("category") is not None else None,
        packDir=pack_dir,
        files=files,
        fullGeneration=bool(parsed.get("fullGeneration", False)),
        generateFrameworkTestbench=bool(parsed.get("generateFrameworkTestbench", True)),
        generateFrameworkTestbenchDeclared=parsed.get("generateFrameworkTestbench") is not None,
        apiVersion=str(parsed["apiVersion"]) if parsed.get("apiVersion") is not None else None,
        requirements=_parse_requirements(parsed.get("requirements")),
        generation=_parse_generation(parsed.get("generation"), name),
    )


class ScaffoldPackLoader:
    def __init__(self, builtin_packs_dir: str = str(BUILTIN_PACKS_DIR)):
        self.builtin_packs_dir = str(builtin_packs_dir)

    def resolve(self, pack_name: str, workspace_pack_dirs: Optional[List[str]] = None) -> ScaffoldPack:
        workspace_pack_dirs = workspace_pack_dirs or []
        if os.path.isabs(pack_name) and os.path.exists(os.path.join(pack_name, "scaffold.yml")):
            return load_pack(pack_name)
        search = [*workspace_pack_dirs, self.builtin_packs_dir]
        for d in search:
            candidate = os.path.join(d, pack_name)
            if os.path.exists(os.path.join(candidate, "scaffold.yml")):
                pack = load_pack(candidate)
                if not pack.category and d in workspace_pack_dirs:
                    pack["category"] = "workspace"
                return pack
        raise ValueError(f"Scaffold pack '{pack_name}' not found. "
                         f"Searched: {', '.join(os.path.join(d, pack_name) for d in search)}")

    def resolve_default(self) -> ScaffoldPack:
        pack_dir = os.path.join(self.builtin_packs_dir, "builtin-minimal")
        if not os.path.exists(os.path.join(pack_dir, "scaffold.yml")):
            raise ValueError(f"Built-in scaffold pack 'builtin-minimal' not found at: {pack_dir}")
        return load_pack(pack_dir)

    def list_builtin_packs(self) -> List[str]:
        try:
            return sorted(e for e in os.listdir(self.builtin_packs_dir)
                          if os.path.exists(os.path.join(self.builtin_packs_dir, e, "scaffold.yml")))
        except OSError:
            return []


# ---------------------------------------------------------------------------
# Ownership
# ---------------------------------------------------------------------------

_TB_SOURCE = re.compile(
    r"(?:^|/)(?:tb|testbench|sim|simulation)/[^/]+\.(?:vhd|vhdl|sv|py|tcl)$"
    r"|(?:^|/)(?:tb_|test_).+\.(?:vhd|vhdl|sv|py|tcl)$"
    r"|(?:^|/).+_(?:tb|test)\.(?:vhd|vhdl|sv|py|tcl)$")
_SIM_RUNNER = re.compile(
    r"(?:^|/)(?:makefile|[^/]+\.mk|(?:run|sim|compile)[^/]*\.(?:sh|py|tcl)|[^/]+\.(?:do|gtkw|wcfg)|conftest\.py)$")


def pack_owns_generated_tree(pack: ScaffoldPack) -> bool:
    if pack["fullGeneration"] is not True:
        return False
    targets = [f["target"].replace("\\", "/").lower() for f in pack["files"]]
    sources = [t for t in targets if _TB_SOURCE.search(t)]
    runners = [t for t in targets if _SIM_RUNNER.search(t)]
    return any(r != s for s in sources for r in runners)


def should_generate_framework_testbench(pack: ScaffoldPack) -> bool:
    if pack["generateFrameworkTestbenchDeclared"]:
        return pack["generateFrameworkTestbench"] is not False
    return not pack_owns_generated_tree(pack)


# ---------------------------------------------------------------------------
# Compatibility
# ---------------------------------------------------------------------------


def _satisfies_range(version: str, rng: str) -> bool:
    caret, tilde = rng.startswith("^"), rng.startswith("~")
    rv = rng[1:] if caret or tilde else rng
    v = [int(x) for x in version.split(".")] + [0, 0]
    r = [int(x) for x in rv.strip().split(".")] + [0, 0]
    if caret:
        return v[0] == r[0] and (v[1] > r[1] or (v[1] == r[1] and v[2] >= r[2]))
    if tilde:
        return v[0] == r[0] and v[1] == r[1] and v[2] >= r[2]
    return v[:3] == r[:3]


def check_pack_api_version(pack: ScaffoldPack) -> None:
    if not pack.get("apiVersion"):
        return
    if not _satisfies_range(CONTRACT_VERSION, pack["apiVersion"]):
        raise ValueError(f"Pack '{pack['name']}' targets apiVersion '{pack['apiVersion']}' "
                         f"but this IPCraft provides contract {CONTRACT_VERSION}.")


def check_pack_requirements(pack: ScaffoldPack, hdl_language: str, bus_type: str, has_memory_mapped_slave: bool,
                            active_bus_port_names: List[str]) -> None:
    req = pack.get("requirements")
    if not req:
        return
    reasons: List[str] = []
    active = {n.lower() for n in active_bus_port_names}

    def fmt(vals: List[str]) -> str:
        return f"[{', '.join(vals)}]"

    if req.get("hdlLanguages") and hdl_language not in req["hdlLanguages"]:
        reasons.append(f"requires HDL language {fmt(req['hdlLanguages'])}, but generation targets '{hdl_language}'")
    if req.get("busTypes") and bus_type not in req["busTypes"]:
        reasons.append(f"requires bus type {fmt(req['busTypes'])}, but the IP core's primary slave interface is '{bus_type}'")
    if req.get("memoryMappedSlave") == "required" and not has_memory_mapped_slave:
        reasons.append("requires a memory-mapped slave interface, but the IP core has none")
    if req.get("memoryMappedSlave") == "forbidden" and has_memory_mapped_slave:
        reasons.append("requires no memory-mapped slave interface, but the IP core has one")
    if req.get("logicalPorts"):
        missing = [p for p in req["logicalPorts"] if p.lower() not in active]
        if missing:
            reasons.append(f"requires logical ports {fmt(req['logicalPorts'])}, but the primary bus interface is "
                           f"missing: {', '.join(missing)}")
    if reasons:
        raise ValueError(f"Scaffold pack '{pack['name']}' is incompatible with this IP core:\n"
                         + "\n".join(f"  - {r}" for r in reasons))
