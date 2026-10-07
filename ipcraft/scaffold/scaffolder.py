"""``IpCoreScaffolder`` — pack-driven HDL / testbench / vendor generation (port of
``IpCoreScaffolder.ts``).  The result and option shapes are plain dicts that mirror the
TypeScript ``GenerateOptions`` / ``GenerateResult`` interfaces."""

from __future__ import annotations

import json
import logging
import os
import re
import stat
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from ..generator.reindent import (  # noqa: F401  (indent helpers re-exported for callers)
    DEFAULT_INDENT_SIZE,
    DEFAULT_INDENT_STYLE,
    create_indent_unit,
    reindent_source,
    should_reindent_source,
)
from .context import build_template_context
from .loader import (
    SchemaValidationError,
    blocks_generation,
    bus_definitions_for_templates,
    check_bus_conformance,
    load_bus_library,
    load_ip_core_data,
)
from .packs import (
    TEMPLATES_DIR,
    ScaffoldPackLoader,
    check_pack_api_version,
    check_pack_requirements,
    pack_owns_generated_tree,
    resolve_scaffold_output_path,
    should_generate_framework_testbench,
)
from .registers import get_bus_type_for_template, has_memory_mapped_consumer_interface, resolve_memory_maps
from .templates_env import JDict, TemplateLoader, to_js

log = logging.getLogger("ipcraft.scaffold")

SIM_PREFIXES = ("tb/", "sim/", "simulation/", "testbench/", "test/")
EXTRA_HDL_FILE_TYPES = {"vhdl", "verilog", "systemverilog"}
NON_RTL_FILE_SET_NAMES = {"Simulation_Resources", "Integration"}
DEFAULT_FRAMEWORK = "cocotb"
DEFAULT_ENGINE = "ghdl"


def is_simulation_path(p: str) -> bool:
    return p.startswith(SIM_PREFIXES)


def apply_executable_mode(full_path: str) -> None:
    try:
        mode = os.stat(full_path).st_mode
        new = mode | 0o111
        if new != mode:
            os.chmod(full_path, new)
    except OSError as exc:
        log.warning("Could not set executable bit on %s: %s", full_path, exc)


def extract_active_bus_port_names(context: dict) -> List[str]:
    ports = context.get("bus_ports")
    if not isinstance(ports, list):
        return []
    return [str(p.get("logical_name") or p.get("name") or "") for p in ports if (p.get("logical_name") or p.get("name"))]


def collect_user_managed_paths(ip_core: dict) -> Set[str]:
    paths: Set[str] = set()
    for fset in ip_core.get("fileSets") or []:
        for f in fset.get("files") or []:
            if f.get("managed") is False and f.get("path"):
                paths.add(f["path"])
    return paths


def resolve_memmap_relpath(ip_core: dict, input_path: str, output_dir: str) -> Optional[str]:
    mm = ip_core.get("memoryMaps")
    if mm and not isinstance(mm, list) and isinstance(mm, dict):
        imp = mm.get("import")
        if isinstance(imp, str):
            abs_path = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(input_path)), imp))
            return os.path.relpath(abs_path, os.path.join(output_dir, "tb")).replace("\\", "/")
    return None


def is_within_dir(directory: str, abs_path: str) -> bool:
    rel = os.path.relpath(abs_path, os.path.abspath(directory))
    return rel == "." or (not rel.startswith("..") and not os.path.isabs(rel))


def collect_user_declared_extra_paths(ip_core: dict, files: Dict[str, str]) -> List[str]:
    extras: List[str] = []
    for fset in ip_core.get("fileSets") or []:
        if fset.get("name") in NON_RTL_FILE_SET_NAMES:
            continue
        for f in fset.get("files") or []:
            if f.get("path") and (f.get("type") or "") in EXTRA_HDL_FILE_TYPES and f["path"] not in files:
                extras.append(f["path"])
    return extras


class IpCoreScaffolder:
    def __init__(self, templates_dir: Optional[str] = None, builtin_packs_dir: Optional[str] = None,
                 bus_library_dirs: Optional[List[str]] = None):
        self.templates_dir = str(templates_dir or TEMPLATES_DIR)
        self.pack_loader = ScaffoldPackLoader(str(builtin_packs_dir)) if builtin_packs_dir else ScaffoldPackLoader()
        self.bus_library_dirs = bus_library_dirs or []

    # -- public ------------------------------------------------------------

    def generate_all(self, input_path: str, output_dir: str, options: Optional[dict] = None) -> dict:
        options = options or {}
        try:
            return self._generate_all(input_path, output_dir, options)
        except Exception as exc:  # noqa: BLE001 - result-style error reporting like the TS API
            log.debug("HDL generation failed", exc_info=True)
            result = {"success": False, "error": str(exc)}
            if isinstance(exc, SchemaValidationError):
                result["issues"] = exc.issues
            return result

    # -- implementation ----------------------------------------------------

    def _generate_all(self, input_path: str, output_dir: str, options: dict) -> dict:
        input_path = os.path.abspath(input_path)
        output_dir = os.path.abspath(output_dir)
        ip_core = load_ip_core_data(input_path, options.get("sourceText"))
        library = load_bus_library(input_path, ip_core, list(options.get("busLibraryDirs") or []) + self.bus_library_dirs)
        # Resolve memory maps once: shared by the conformance check (memoryMapRef), the template
        # context (RTL/testbench) and the vendor packaging step (component.xml <spirit:memoryMaps>).
        resolved_maps = resolve_memory_maps(ip_core, input_path)
        conformance = check_bus_conformance(ip_core, library, [m["name"] for m in resolved_maps])
        if blocks_generation(conformance):
            return {"success": False, "error": "Generation blocked by bus interface conformance issues.",
                    "issues": conformance["issues"]}
        ip_core_dir = os.path.dirname(input_path)
        bus_type = get_bus_type_for_template(ip_core, library)
        has_mm_slave = has_memory_mapped_consumer_interface(ip_core, library)
        context = build_template_context(ip_core, bus_type, input_path, library, resolved_maps)
        context["has_memory_mapped_slave"] = has_mm_slave
        memmap_relpath = resolve_memmap_relpath(ip_core, input_path, output_dir)
        if memmap_relpath is not None:
            context["memmap_relpath"] = memmap_relpath
        assert_valid_context(context)

        include_regs = options.get("includeRegs") is not False and has_mm_slave
        include_testbench = options.get("includeTestbench") is not False
        include_docs = options.get("includeDocs") is True
        targets = options.get("targets") or []
        sim_cfg = ip_core.get("simulation") or {}
        framework = sim_cfg.get("framework") or options.get("framework") or DEFAULT_FRAMEWORK
        engine = sim_cfg.get("engine") or options.get("engine") or DEFAULT_ENGINE
        include_vhdl = options.get("includeVhdl") is not False
        hdl_language = options.get("hdlLanguage") or "vhdl"
        is_sv = hdl_language == "systemverilog"
        context["hdl_language"] = hdl_language
        context["is_systemverilog"] = is_sv
        context["includeRegs"] = include_regs

        pack_name = options.get("scaffoldPack") or (ip_core.get("scaffold_pack") if isinstance(ip_core.get("scaffold_pack"), str) else None)
        workspace_pack_dirs = options.get("workspacePackDirs") or []
        pack = self.pack_loader.resolve(pack_name, workspace_pack_dirs) if pack_name else self.pack_loader.resolve_default()
        check_pack_api_version(pack)
        check_pack_requirements(pack, hdl_language, bus_type, has_mm_slave, extract_active_bus_port_names(context))
        resolved_pack_name = os.path.basename(pack["packDir"])
        pack_owns_output = pack_owns_generated_tree(pack)
        pack_templates = TemplateLoader([pack["packDir"], self.templates_dir])

        files: Dict[str, str] = {}
        pack_managed_false: Set[str] = set()
        executable_targets: Set[str] = set()
        name = str((ip_core.get("vlnv") or {}).get("name") or "ip_core").lower()
        user_managed = collect_user_managed_paths(ip_core)

        if pack["fullGeneration"]:
            rtl_ctx = context
        else:
            rtl_ctx = {**context, "has_memory_mapped_slave": False, "has_endian_swap": False, "endian_swap_ports": [],
                       "endian_swap_widths": [], "has_boundary_transform": False, "boundary_transform_ports": []}
        rtl_ctx = to_js(rtl_ctx)
        full_ctx = to_js(context)

        if include_vhdl:
            for rule in pack["files"]:
                if not pack_templates.evaluate_condition(rule["condition"], rtl_ctx):
                    continue
                source_name = pack_templates.render_string(rule["source"], rtl_ctx)
                relative = pack_templates.render_string(rule["target"], rtl_ctx)
                if relative in user_managed:
                    log.info("Skipping scaffold target owned by fileSets managed:false: %s", relative)
                    continue
                files[relative] = pack_templates.render(source_name, rtl_ctx)
                if rule["managed"] is False:
                    pack_managed_false.add(relative)
                if rule["executable"] is True:
                    executable_targets.add(relative)

        tb_ctx = full_ctx if pack["fullGeneration"] else to_js({**context, "has_memory_mapped_slave": False})
        pack_own_sim_paths = [p for p in files if is_simulation_path(p)]
        warnings: List[str] = []
        framework_tb_paths: List[str] = []

        if include_testbench and should_generate_framework_testbench(pack):
            from .testbench import generate_testbench_files

            tb_files = generate_testbench_files(framework, engine, {
                "name": name, "templateContext": tb_ctx, "templates": pack_templates, "isSv": is_sv,
                "hasMmSlave": has_mm_slave if pack["fullGeneration"] else False,
                "memoryMaps": resolved_maps if pack["fullGeneration"] else [],
                "topLevel": sim_cfg.get("topLevel"), "extraCompileArgs": sim_cfg.get("compileArgs"),
                "extraSimArgs": sim_cfg.get("simArgs"), "extraEnv": sim_cfg.get("env"),
                "fileSets": ip_core.get("fileSets"),
                "rtlSourceFiles": collect_testbench_rtl_files(files, ip_core, input_path, output_dir),
            })
            framework_tb_paths = list(tb_files)
            files.update(tb_files)
            if not pack["generateFrameworkTestbenchDeclared"] and pack_own_sim_paths:
                warnings.append(
                    f"Scaffold pack '{resolved_pack_name}' renders its own simulation-looking output "
                    f"(e.g. {pack_own_sim_paths[0]}) but does not declare 'generateFrameworkTestbench' in scaffold.yml. "
                    f"IPCraft's default framework testbench (tb/*, .vscode/settings.json) will also be generated "
                    f"alongside it. If this pack owns its complete simulation environment, set "
                    f"'generateFrameworkTestbench: false' in the pack manifest.")

        if include_docs and not pack_owns_output:
            doc_target = f"docs/{name}_datasheet.md"
            if doc_target not in user_managed:
                files[doc_target] = pack_templates.render("ip_datasheet.md.j2", full_ctx)

        cached_rtl: Optional[List[str]] = None

        def get_rtl_files() -> List[str]:
            nonlocal cached_rtl
            if cached_rtl is None:
                cached_rtl = collect_rtl_files(files, ip_core, input_path, output_dir)
            return cached_rtl

        if not pack_owns_output and targets:
            from .toolchains import get_toolchain

            for target_id in targets:
                toolchain = get_toolchain(target_id)
                if toolchain is None:
                    log.warning("Unknown target '%s' — skipping", target_id)
                    continue
                is_vivado, is_quartus = target_id == "vivado", target_id == "quartus"
                include_project = (is_vivado and options.get("includeVivadoProject", False)) or \
                                  (is_quartus and options.get("includeQuartusProject", False))
                rtl = get_rtl_files()
                vendor_files = toolchain.scaffold({
                    "name": name, "templateContext": full_ctx, "templates": pack_templates, "ipCoreData": ip_core,
                    "busDefinitions": bus_definitions_for_templates(library), "busLibrary": library, "isSv": is_sv,
                    "memoryMaps": resolved_maps, "ipCoreDir": ip_core_dir,
                }, {
                    "includeProject": include_project, "rtlFiles": rtl if rtl else None,
                    "targetPart": options.get("targetPart"), "quartusDevice": options.get("quartusDevice"),
                })
                files.update(vendor_files)

        indentation = resolve_indentation_defaults(
            {"style": options.get("indentStyle"), "size": options.get("indentSize")},
            (pack.get("generation") or {}).get("indentation"), options.get("workspaceIndentation"))
        files = reindent_generated_sources(files, indentation)

        extra_user_paths: Set[str] = set()
        if os.path.abspath(output_dir) == os.path.abspath(ip_core_dir):
            for rel in collect_user_declared_extra_paths(ip_core, files):
                if not is_within_dir(output_dir, os.path.abspath(os.path.join(ip_core_dir, rel))):
                    continue
                try:
                    files[rel] = Path(os.path.join(ip_core_dir, rel)).read_text(encoding="utf-8")
                    extra_user_paths.add(rel)
                except OSError:
                    pass

        protected = set(pack_managed_false) | user_managed | extra_user_paths
        output_paths = {rel: resolve_scaffold_output_path(output_dir, rel) for rel in files}

        if options.get("dryRun"):
            protected_on_disk = [p for p in protected if p in files and os.path.exists(output_paths[p])]
            return {
                "success": True, "ipCoreName": name, "generatedContents": dict(files),
                "protectedPaths": protected_on_disk, "userManagedPaths": sorted(user_managed),
                "executablePaths": [p for p in executable_targets if p in files],
                "frameworkTestbenchPaths": framework_tb_paths, "warnings": warnings,
                "resolvedPackName": resolved_pack_name, "count": len(files), "busType": bus_type,
            }

        written: Dict[str, str] = {}
        for rel, content in files.items():
            full = output_paths[rel]
            if rel in protected and os.path.exists(full):
                log.info("Skipping managed:false file: %s", rel)
                continue
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8", newline="") as fh:
                fh.write(content)
            written[rel] = full
            if rel in executable_targets:
                apply_executable_mode(full)
        return {
            "success": True, "ipCoreName": name, "files": written, "generatedContents": dict(files),
            "executablePaths": [p for p in executable_targets if p in written],
            "frameworkTestbenchPaths": framework_tb_paths, "warnings": warnings,
            "resolvedPackName": resolved_pack_name, "count": len(written), "busType": bus_type,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def resolve_indentation_defaults(explicit: dict, pack_default: Optional[dict], workspace_default: Optional[dict]) -> dict:
    def pick(field: str, fallback: Any) -> Any:
        for src in (explicit, pack_default, workspace_default):
            if src and src.get(field) is not None:
                return src[field]
        return fallback

    return {"style": pick("style", DEFAULT_INDENT_STYLE), "size": pick("size", DEFAULT_INDENT_SIZE)}


# The scaffold templates are written with a two-space indentation unit.
_SCAFFOLD_TEMPLATE_INDENT = 2


def reindent_generated_sources(files: Dict[str, str], resolved: dict) -> Dict[str, str]:
    unit = create_indent_unit(resolved["style"], resolved["size"])
    return {p: reindent_source(c, unit, _SCAFFOLD_TEMPLATE_INDENT) if should_reindent_source(p) else c
            for p, c in files.items()}


def assert_valid_context(context: dict) -> None:
    from .loader import SCHEMAS_DIR, validate_against_schema

    result = validate_against_schema(json.loads(json.dumps(context, default=str)), str(SCHEMAS_DIR / "template_context.schema.json"))
    if result["valid"]:
        return
    detail = "\n".join(f"  - context{('/' + '/'.join(str(p) for p in d['path'])) if d['path'] else ''} {d['message']}"
                       for d in result.get("details", [])) or f"  - {result.get('error')}"
    raise ValueError(f"Template context failed contract v{context.get('contract_version', '?')} validation:\n{detail}")


def collect_rtl_abs_paths(files: Dict[str, str], ip_core: dict, input_path: str, output_dir: str) -> List[str]:
    from .compilation_order import sort_by_compilation_order, hdl_language_from_path

    ip_core_dir = os.path.dirname(os.path.abspath(input_path))
    generated = [f for f in files if f.startswith("rtl/")]
    strip_ext = lambda p: re.sub(r"\.[^./]+$", "", p)  # noqa: E731
    generated_stems = {strip_ext(p) for p in generated}

    def resolve_lang(f: dict) -> Optional[str]:
        t = f.get("type")
        if t in ("vhdl", "systemverilog"):
            return t
        if t == "verilog":
            return "verilog"
        return hdl_language_from_path(f["path"])

    extra = []
    for fs_ in ip_core.get("fileSets") or []:
        if fs_.get("name") and fs_["name"] in NON_RTL_FILE_SET_NAMES:
            continue
        for f in fs_.get("files") or []:
            p = f.get("path")
            if not isinstance(p, str) or not p or is_simulation_path(p) or strip_ext(p) in generated_stems:
                continue
            lang = resolve_lang(f)
            if lang is None:
                continue
            extra.append({"absPath": os.path.abspath(os.path.join(ip_core_dir, p)), "language": lang,
                          "logicalName": f.get("logicalName")})
    if not generated and not extra:
        return []
    if not extra:
        return [os.path.abspath(os.path.join(output_dir, f)) for f in generated]
    items = [{"absPath": os.path.abspath(os.path.join(output_dir, rel)), "relPath": rel,
              "language": "systemverilog" if rel.endswith(".sv") else "vhdl", "logicalName": None} for rel in generated]
    items += [{**e, "relPath": None} for e in extra]
    rel_by_abs = {i["absPath"]: i["relPath"] for i in items}

    def read(p: str) -> Optional[str]:
        rel = rel_by_abs.get(p)
        if rel is not None:
            return files.get(rel)
        try:
            return Path(p).read_text(encoding="utf-8")
        except OSError:
            return None

    return sort_by_compilation_order([{"path": i["absPath"], "language": i["language"], "logicalName": i["logicalName"]}
                                      for i in items], read)


def collect_rtl_files(files, ip_core, input_path, output_dir) -> List[str]:
    sub = os.path.join(output_dir, "_sub")
    return [os.path.relpath(p, sub).replace("\\", "/") for p in collect_rtl_abs_paths(files, ip_core, input_path, output_dir)]


def collect_testbench_rtl_files(files, ip_core, input_path, output_dir) -> List[str]:
    return [os.path.relpath(p, output_dir).replace("\\", "/") for p in collect_rtl_abs_paths(files, ip_core, input_path, output_dir)]
