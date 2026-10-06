#!/usr/bin/env python3
"""
ipcraft - IP Core scaffolding and generation tool.

Usage:
    ipcraft init                                     # interactive wizard (recommended for new users)
    ipcraft new my_core --bus AXI4_LITE -o ./my_core
    ipcraft generate my_core.ip.yml --output ./build
    ipcraft generate my_core.ip.yml --dry-run        # preview changes without writing
    ipcraft generate my_core.ip.yml --watch          # re-generate on file change
    ipcraft parse my_core.vhd -o my_core.ip.yml
    ipcraft validate my_core.ip.yml
    ipcraft verify my_core.ip.yml ./build            # fail if ./build is stale
    ipcraft migrate my_core.ip.yml --check
    ipcraft list-buses AXI4_LITE --ports

Global flags (work on every subcommand):
    --debug        Show full Python traceback on errors
    -v / --verbose Verbose per-step output
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

try:
    from importlib.metadata import version as _pkg_version
    _VERSION = _pkg_version("ipcraft")
except Exception:
    _VERSION = "dev"

from ipcraft.generator.hdl.ipcore_project_generator import IpCoreProjectGenerator
from ipcraft.generator.reindent import reindent_generated_sources
from ipcraft.generator.yaml.ip_yaml_generator import IpYamlGenerator
from ipcraft.model.bus_library import get_bus_library
from ipcraft.parser.yaml.ip_yaml_parser import YamlIpCoreParser
from ipcraft.generator.yaml.boilerplate import generate_new_ip
from ipcraft.utils.diagram import generate_ascii_diagram


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _add_indent_args(p: argparse.ArgumentParser) -> None:
    """Add --indent-style / --indent-size (generate and verify)."""
    p.add_argument(
        "--indent-style", choices=["spaces", "tab"],
        help="Indentation style for generated HDL and synthesis-tool sources (default: templates as-is)",
    )
    p.add_argument(
        "--indent-size", type=_positive_int, metavar="N",
        help="Spaces per indentation level when --indent-style is 'spaces' (default: 2 once an indent option is given)",
    )


def _add_scaffold_args(p: argparse.ArgumentParser) -> None:
    """Options of the pack-driven generation engine (shared with the ipcraft-vscode CLI)."""
    g = p.add_argument_group(
        "scaffold engine",
        "Giving any of these options selects the pack-driven engine used by the ipcraft-vscode CLI "
        "(layout: rtl/, tb/, altera/, xilinx/); without them the classic generator is used.",
    )
    g.add_argument("--target", action="append", metavar="VENDOR",
                   help="Vendor target(s) to scaffold a project for: quartus, vivado "
                        "(repeatable or comma-separated). Omit for RTL + testbench only.")
    g.add_argument("--lang", choices=["vhdl", "systemverilog"],
                   help="HDL language to generate (default: vhdl)")
    g.add_argument("--pack", metavar="NAME_OR_DIR",
                   help="Scaffold pack to use (built-in name or pack directory); overrides scaffold_pack "
                        "in the .ip.yml. Built-ins: builtin-minimal (default), builtin-ipcraft, example-*")
    g.add_argument("--quartus-device", metavar="PART", help="Quartus device part (default: 5CSEBA6U23I7)")
    g.add_argument("--vivado-part", metavar="PART", help="Vivado part (default: xc7z020clg484-1)")
    g.add_argument("--bus-library", action="append", metavar="DIR",
                   help="Extra directory of bus-definition YAML files (repeatable; like ipcraft.busLibraryPaths)")
    g.add_argument("--pack-dir", action="append", metavar="DIR",
                   help="Extra directory searched for scaffold packs by name (repeatable)")
    g.add_argument("--docs", action="store_true", help="Also generate the Markdown IP datasheet (docs/<name>_datasheet.md)")
    g.add_argument("--framework", choices=["cocotb", "vunit"], help="Testbench framework (default: cocotb)")
    g.add_argument("--engine-sim", dest="engine_sim", choices=["ghdl", "icarus", "verilator", "questa"],
                   help="Simulation engine (default: ghdl)")


def _uses_scaffold_engine(args) -> bool:
    return any(getattr(args, name, None) for name in
               ("target", "lang", "pack", "quartus_device", "vivado_part", "framework", "engine_sim", "docs",
                "bus_library", "pack_dir"))


def _positive_int(value: str) -> int:
    n = int(value)
    if n < 1:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return n


def _add_common_args(p: argparse.ArgumentParser) -> None:
    """Add --debug / -v flags that every subcommand shares."""
    p.add_argument(
        "--debug", action="store_true",
        help="Show full Python traceback on errors",
    )
    p.add_argument(
        "-v", "--verbose", action="store_true",
        help="Enable verbose per-step output",
    )


def log(msg: str, args, level: str = "progress") -> None:
    """Emit a progress message.

    JSON mode  → JSON Lines to stderr: {"type": level, "message": msg}
    Verbose    → plain text to stdout
    Otherwise  → silent
    """
    use_verbose = getattr(args, "verbose", False) or getattr(args, "progress", False)
    if getattr(args, "json", False):
        print(json.dumps({"type": level, "message": msg}), file=sys.stderr, flush=True)
    elif use_verbose:
        print(msg)


def err(msg: str, args, exc: Exception = None) -> None:
    """Print a user-facing error to stderr, then exit 1.

    Full traceback is shown only when --debug is set.
    """
    if getattr(args, "json", False):
        print(json.dumps({"success": False, "error": msg}))
    else:
        print(f"✗ {msg}", file=sys.stderr)
        if exc is not None:
            if getattr(args, "debug", False):
                import traceback
                traceback.print_exc(file=sys.stderr)
            else:
                print("  Run with --debug for a full traceback.", file=sys.stderr)
    sys.exit(1)


def get_bus_type(ip_core) -> str:
    """Extract bus type from IP core's bus interfaces."""
    for bus in ip_core.bus_interfaces:
        if bus.mode == "slave" and bus.memory_map_ref:
            from ipcraft.utils import bus_type_to_generator_code, enum_value
            bus_type_str = enum_value(bus.type)
            return bus_type_to_generator_code(bus_type_str)
    return "axil"


def _get_unmanaged_files(ip_core) -> set:
    """Return the set of filenames (basename only) marked managed=False."""
    unmanaged: set = set()
    for fileset in ip_core.file_sets:
        for f in fileset.files:
            if not getattr(f, "managed", True):
                unmanaged.add(Path(f.path).name)
    return unmanaged


def _print_file_tree(written: dict, output_base: Path) -> None:
    """Print a grouped directory tree derived from the written-files dict."""
    from collections import defaultdict

    dirs: dict = defaultdict(list)
    root_files = []
    for filepath in sorted(written):
        parts = Path(filepath).parts
        if len(parts) == 1:
            root_files.append(parts[0])
        else:
            dirs[parts[0]].append(str(Path(*parts[1:])))

    for f in root_files:
        print(f"  {f}")
    for dirname in sorted(dirs):
        print(f"  {dirname}/")
        for f in sorted(dirs[dirname]):
            print(f"    {f}")


# ---------------------------------------------------------------------------
# Subcommand: validate
# ---------------------------------------------------------------------------

def _validate_contracts(args) -> None:
    """Schema + bus-contract validation, as performed by the ipcraft-vscode extension."""
    from ipcraft.scaffold.loader import SchemaValidationError, check_bus_conformance, load_bus_library, load_ip_core_data

    try:
        issues = []
        try:
            ip_core = load_ip_core_data(args.input)
        except SchemaValidationError as exc:
            issues.extend(exc.issues)
            ip_core = None
        if ip_core is not None:
            library = load_bus_library(args.input, ip_core, getattr(args, "bus_library", None))
            issues.extend(check_bus_conformance(ip_core, library)["issues"])
        errors = [i for i in issues if i["severity"] == "error"]
        if args.json:
            print(json.dumps({"success": True, "valid": not errors, "issues": issues}))
        elif not issues:
            print(f"✓ {args.input} is valid")
        else:
            print(f"{'✗' if errors else '!'} {args.input}: {len(errors)} error(s), {len(issues) - len(errors)} warning(s)")
            for i in issues:
                where = ".".join(str(p) for p in i["path"])
                print(f"  - [{i['severity']}] {i['code']}{' at ' + where if where else ''}: {i['message']}")
        if errors:
            sys.exit(1)
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        err(f"Validation failed: {e}", args, e)


def cmd_validate(args):
    """Validate IP core YAML."""
    from ipcraft.model.validators import IpCoreValidator

    if getattr(args, "contracts", False):
        return _validate_contracts(args)
    try:
        if getattr(args, "verbose", False):
            print(f"Validating {args.input}...")
        ip_core = YamlIpCoreParser().parse_file(args.input)
        validator = IpCoreValidator(ip_core)
        is_valid = validator.validate_all()

        if args.json:
            print(json.dumps({"success": True, "valid": is_valid, "errors": validator.errors}))
            if not is_valid:
                sys.exit(1)
        else:
            if is_valid:
                print(f"✓ {args.input} is valid")
            else:
                print(f"✗ {args.input} is invalid:")
                for error in validator.errors:
                    print(f"  - {error}")
                sys.exit(1)

    except SystemExit:
        raise
    except Exception as e:
        err(f"Validation failed: {e}", args, e)


# ---------------------------------------------------------------------------
# Subcommand: new
# ---------------------------------------------------------------------------

def cmd_new(args):
    """Scaffold a new IP core YAML from templates."""
    # Validate bus type early, with a helpful message listing available choices.
    if args.bus:
        from ipcraft.utils import normalize_bus_type_key
        library = get_bus_library()
        known = set(library.list_bus_types())
        normalized = normalize_bus_type_key(args.bus)
        if normalized not in known:
            primary = sorted(t for t in known if "_" in t)
            err(
                f"Unknown bus type: '{args.bus}'\n"
                f"  Available: {', '.join(primary)}\n"
                f"  Run 'ipcraft list-buses' for full details.",
                args,
            )

    try:
        ip_path, mm_path = generate_new_ip(
            name=args.name,
            vendor=args.vendor,
            library=args.library,
            version=args.version,
            bus_type=args.bus,
            output_dir=args.output,
        )

        files_created = [str(ip_path)]
        if mm_path:
            files_created.append(str(mm_path))

        # Parse the newly generated IP to render the ASCII diagram.
        # parse_file() resolves the path internally, so no chdir needed.
        diagram = None
        ip_core = YamlIpCoreParser().parse_file(ip_path)
        diagram = generate_ascii_diagram(ip_core)

        if args.json:
            print(json.dumps({
                "success": True,
                "files": files_created,
                "diagram": diagram,
            }))
        else:
            print(f"✓ Generated {ip_path}")
            if mm_path:
                print(f"✓ Generated {mm_path}")
            if diagram:
                print("\nIP Core Symbol:")
                print(diagram)
                print()

    except SystemExit:
        raise
    except Exception as e:
        err(f"Failed to scaffold IP core: {e}", args, e)


def _build_files(args, output_base: Path):
    """Parse the IP YAML and render every file in memory.

    Returns ``(ip_core, bus_type, generator, {relpath: content})``. Nothing is written.
    """
    ip_core = YamlIpCoreParser().parse_file(args.input)

    bus_type = get_bus_type(ip_core)
    log(f"Detected bus type: {bus_type}", args)

    log("Generating files...", args)
    gen = IpCoreProjectGenerator(template_dir=getattr(args, "template_dir", None))

    # Compute the relative path from tb/ to the .mm.yml file.
    # The .mm.yml lives beside the .ip.yml (ip_dir); tb/ lives under output_base.
    ip_dir = Path(args.input).resolve().parent
    mm_file = ip_dir / f"{ip_core.vlnv.name.lower()}.mm.yml"
    tb_dir = output_base.resolve() / "tb"
    gen.mm_yaml_relpath = str(Path(os.path.relpath(mm_file, tb_dir)).as_posix())

    all_files = gen.generate_all(
        ip_core,
        bus_type=bus_type,
        structured=True,
        vendor=args.vendor,
        include_testbench=args.testbench,
        include_regs=args.regs,
        dump_context=getattr(args, "dump_context", False),
    )
    all_files = reindent_generated_sources(
        all_files, getattr(args, "indent_style", None), getattr(args, "indent_size", None)
    )
    return ip_core, bus_type, gen, all_files


def _run_scaffold_generate(args, output_base: Path) -> dict:
    """Generate with the pack-driven engine (feature parity with the ipcraft-vscode CLI)."""
    from ipcraft.scaffold.run import run_generate

    t_start = time.monotonic()
    log(f"Generating from {args.input} with the scaffold engine...", args)
    if getattr(args, "dry_run", False):
        result = run_generate(args, str(output_base), dry_run=True)
        contents = result["generatedContents"]
        protected = set(result.get("protectedPaths") or [])
        changed, unchanged, skipped = [], [], []
        for rel in sorted(contents):
            full = output_base / rel
            if rel in protected:
                skipped.append(rel)
            elif full.exists() and full.read_text(encoding="utf-8", errors="replace") == contents[rel]:
                unchanged.append(rel)
            else:
                changed.append(rel)
        if getattr(args, "json", False):
            print(json.dumps({"success": True, "dryRun": True, "wouldWrite": changed, "unchanged": unchanged,
                              "protected": skipped}))
        else:
            print(f"Dry run — nothing written.  Target: {output_base}\n")
            for title, group in (("Would write (new or changed):", changed), ("\nWould skip (content unchanged):", unchanged),
                                 ("\nWould skip (unmanaged — user-owned):", skipped)):
                if group:
                    print(title)
                    for f in group:
                        print(f"  {f}")
        return {}
    result = run_generate(args, str(output_base))
    written = {rel: path for rel, path in (result.get("files") or {}).items()}
    for w in result.get("warnings") or []:
        print(f"Warning: {w}", file=sys.stderr)
    if getattr(args, "dump_context", False):
        _dump_scaffold_context(args, output_base)
    if getattr(args, "json", False):
        print(json.dumps({"success": True, "files": written, "count": len(written), "busType": result.get("busType"),
                          "warnings": result.get("warnings") or []}))
    else:
        print(f"Generated {len(written)} file(s) into {output_base.resolve()}")
        for f in sorted(written):
            print(f"  {f}")
        log(f"done in {time.monotonic() - t_start:.1f}s", args)
    return written


def _dump_scaffold_context(args, output_base: Path) -> None:
    from ipcraft.scaffold.context import build_template_context
    from ipcraft.scaffold.loader import load_bus_library, load_ip_core_data
    from ipcraft.scaffold.registers import get_bus_type_for_template

    ip_core = load_ip_core_data(args.input)
    library = load_bus_library(args.input, ip_core)
    ctx = build_template_context(ip_core, get_bus_type_for_template(ip_core, library), args.input, library)
    out = output_base / "template_context.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(ctx, indent=2, default=str), encoding="utf-8")


# ---------------------------------------------------------------------------
# Subcommand: generate  (core logic extracted for reuse by --watch and init)
# ---------------------------------------------------------------------------

def _run_generate_core(args, output_base: Path) -> dict:
    """Run generation and return the written-files dict.

    Raises on error; does not call sys.exit directly.
    Returns an empty dict on --dry-run (nothing written).
    """
    t_start = time.monotonic()

    if _uses_scaffold_engine(args):
        return _run_scaffold_generate(args, output_base)

    if not getattr(args, "json", False):
        print(f"Generating from {args.input}...", end=" ", flush=True)

    log("Parsing IP core YAML...", args)
    ip_core, bus_type, gen, all_files = _build_files(args, output_base)

    # ---- Dry-run: report and return without writing ----
    if getattr(args, "dry_run", False):
        print()
        _dry_run_report(all_files, output_base, ip_core)
        return {}

    log(f"Writing {len(all_files)} files...", args)

    unmanaged_files = _get_unmanaged_files(ip_core)

    written = {}
    skipped_unmanaged = []
    for filepath, content in all_files.items():
        full_path = output_base / filepath
        if full_path.exists() and Path(filepath).name in unmanaged_files:
            skipped_unmanaged.append(filepath)
            log(f"  Skipped (unmanaged): {filepath}", args)
            continue
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content)
        written[filepath] = str(full_path)
        log(f"  Written: {filepath}", args)

    if args.update_yaml:
        gen.update_ipcore_filesets(
            str(Path(args.input).resolve()),
            all_files,
            include_regs=args.regs,
            vendor=args.vendor,
            include_testbench=args.testbench,
        )

    elapsed = time.monotonic() - t_start
    log("Generation complete!", args)

    if getattr(args, "json", False):
        print(json.dumps({
            "success": True,
            "files": written,
            "count": len(written),
            "busType": bus_type,
        }))
    else:
        print(f"done ({elapsed:.1f}s)")
        print(f"✓ {len(written)} files written to: {output_base}")
        if skipped_unmanaged:
            print(f"  {len(skipped_unmanaged)} unmanaged file(s) preserved.")
        _print_file_tree(written, output_base)

    return written


def _dry_run_report(all_files: dict, output_base: Path, ip_core) -> None:
    """Print which files would be written, unchanged, or skipped."""
    unmanaged_files = _get_unmanaged_files(ip_core)

    changed, unchanged, unmanaged = [], [], []
    for filepath, content in sorted(all_files.items()):
        full_path = output_base / filepath
        if Path(filepath).name in unmanaged_files and full_path.exists():
            unmanaged.append(filepath)
        elif full_path.exists() and full_path.read_text() == content:
            unchanged.append(filepath)
        else:
            changed.append(filepath)

    print(f"Dry run — nothing written.  Target: {output_base}\n")
    if changed:
        print("Would write (new or changed):")
        for f in changed:
            print(f"  {f}")
    if unchanged:
        print("\nWould skip (content unchanged):")
        for f in unchanged:
            print(f"  {f}")
    if unmanaged:
        print("\nWould skip (unmanaged — user-owned):")
        for f in unmanaged:
            print(f"  {f}")


def cmd_generate(args):
    """Generate VHDL files from IP core YAML."""
    output_base = Path(args.output) if args.output else Path(args.input).parent

    try:
        _run_generate_core(args, output_base)
    except SystemExit:
        raise
    except Exception as e:
        # Print the newline that the "Generating..." line left open.
        if not getattr(args, "json", False):
            print()
        err(f"Generation failed: {e}", args, e)

    if getattr(args, "watch", False):
        _watch_loop(args, output_base)


def _watch_loop(args, output_base: Path) -> None:
    """Poll input files for mtime changes and re-run generation (blocking)."""
    ip_path = Path(args.input).resolve()
    watch_paths = {ip_path}

    # Include any referenced mm.yml files.
    try:
        import yaml as yaml_lib
        data = yaml_lib.safe_load(ip_path.read_text())
        mm_import = (data.get("memoryMaps") or {}).get("import") or ""
        if mm_import:
            mm_path = ip_path.parent / mm_import
            if mm_path.exists():
                watch_paths.add(mm_path.resolve())
    except Exception:
        pass

    watch_strs = ", ".join(p.name for p in sorted(watch_paths, key=lambda p: p.name))
    print(f"\nWatching {watch_strs} for changes... (Ctrl+C to stop)")

    last_mtimes = {p: p.stat().st_mtime for p in watch_paths if p.exists()}

    try:
        while True:
            time.sleep(0.5)
            for p in list(watch_paths):
                try:
                    mtime = p.stat().st_mtime
                except FileNotFoundError:
                    continue
                if mtime != last_mtimes.get(p):
                    last_mtimes[p] = mtime
                    ts = time.strftime("%H:%M:%S")
                    print(f"\n[{ts}] Change detected: {p.name}")
                    try:
                        _run_generate_core(args, output_base)
                    except Exception as e:
                        print(f"✗ {e}", file=sys.stderr)
                        if getattr(args, "debug", False):
                            import traceback
                            traceback.print_exc(file=sys.stderr)
                    break  # Restart mtime scan after regen.
    except KeyboardInterrupt:
        print("\nStopped watching.")


# ---------------------------------------------------------------------------
# Subcommand: verify
# ---------------------------------------------------------------------------

def _list_files(root: Path, prefix: str) -> list:
    base = root / prefix
    if not base.is_dir():
        return []
    return sorted(p.relative_to(root).as_posix() for p in base.rglob("*") if p.is_file())


def _cmd_verify_scaffold(args, generated_dir: Path) -> None:
    from ipcraft.scaffold.run import run_verify

    try:
        result = run_verify(args, str(generated_dir))
    except Exception as e:  # noqa: BLE001
        err(f"Verification failed: {e}", args, e)
        return
    if result.get("error") is not None and not result["success"] and "staleFiles" not in result:
        err(f"Verification failed: {result['error']}", args)
        return
    for w in result.get("warnings") or []:
        print(f"Warning: {w}", file=sys.stderr)
    stale = result["staleFiles"]
    if args.json:
        print(json.dumps({"success": not stale, "staleFiles": stale}))
    elif stale:
        print(f"Stale: {len(stale)} file(s) differ from a fresh generation:", file=sys.stderr)
        for f in stale:
            print(f"  {f}", file=sys.stderr)
    else:
        print(f"Up to date: {generated_dir.resolve()} matches a fresh generation.")
    if stale:
        sys.exit(1)


def cmd_verify(args):
    """Check that a generated directory matches a fresh generation (drift check)."""
    generated_dir = Path(args.generated_dir)
    if _uses_scaffold_engine(args):
        return _cmd_verify_scaffold(args, generated_dir)
    try:
        ip_core, _bus, _gen, fresh = _build_files(args, generated_dir)
        unmanaged = _get_unmanaged_files(ip_core)

        stale = set()
        for rel, content in fresh.items():
            if Path(rel).name in unmanaged:
                continue
            disk = generated_dir / rel
            try:
                if disk.read_text() != content:
                    stale.add(rel)
            except (OSError, UnicodeDecodeError):
                stale.add(rel)

        # Orphans: files in a generated top-level dir that a fresh run no longer produces.
        for top in {r.split("/")[0] for r in fresh if "/" in r}:
            for rel in _list_files(generated_dir, top):
                if rel not in fresh and Path(rel).name not in unmanaged:
                    stale.add(rel)
    except SystemExit:
        raise
    except Exception as e:
        err(f"Verification failed: {e}", args, e)
        return

    stale_sorted = sorted(stale)
    if args.json:
        print(json.dumps({"success": not stale_sorted, "staleFiles": stale_sorted}))
    elif stale_sorted:
        print(f"Stale: {len(stale_sorted)} file(s) differ from a fresh generation:", file=sys.stderr)
        for f in stale_sorted:
            print(f"  {f}", file=sys.stderr)
    else:
        print(f"Up to date: {generated_dir.resolve()} matches a fresh generation.")
    if stale_sorted:
        sys.exit(1)


# ---------------------------------------------------------------------------
# Subcommand: migrate
# ---------------------------------------------------------------------------

def cmd_migrate(args):
    """Upgrade .ip.yml files to the latest format and convert legacy snake_case keys."""
    from ipcraft.migrate import migrate_ip_core_yaml, migrate_memory_map_yaml, migrate_vendor_to_targets
    from ipcraft.scaffold.loader import load_bus_library

    exit_code = 0
    results = []
    for name in args.paths:
        path = Path(name)
        entry = {"path": name}
        try:
            text = path.read_text()
            is_mm = name.lower().endswith((".mm.yml", ".mm.yaml"))
            notes: list = []
            if is_mm:
                res = migrate_memory_map_yaml(text)
                new_text, changed = res.text, res.changed
                from_v = to_v = None
            else:
                import yaml as _yaml

                data = _yaml.safe_load(text)
                if not isinstance(data, dict):
                    raise ValueError("Invalid YAML: must be an object")
                library = load_bus_library(str(path.resolve()), data)
                res = migrate_ip_core_yaml(text, library)
                new_text, changed, from_v, to_v = res.text, res.changed, res.from_version, res.to_version
                if args.vendor_targets:
                    v_changed, v_text, notes = migrate_vendor_to_targets(new_text)
                    if v_changed:
                        new_text, changed = v_text, True
            versions = f" ({from_v} -> {to_v}, {res.mutation_count} change(s))" if from_v and from_v != to_v else None
            if not changed:
                status = "upToDate"
                entry.update(version=to_v)
                if not args.json:
                    print(f"Up to date: {name}" + (f" ({to_v})" if to_v else ""))
            elif args.check:
                status = "needsUpgrade"
                exit_code = 1
                entry.update(fromVersion=from_v, toVersion=to_v)
                if not args.json:
                    print(f"Needs upgrade: {name}" + (f" ({from_v} -> {to_v})" if from_v and from_v != to_v else ""))
            else:
                path.write_text(new_text)
                status = "upgraded"
                entry.update(fromVersion=from_v, toVersion=to_v, mutationCount=res.mutation_count, notes=notes)
                if not args.json:
                    if versions:
                        print(f"Upgraded {name}{versions}")
                    else:
                        print(f"Converted legacy keys in {name} ({res.mutation_count} change(s))")
                    for n in notes:
                        print(f"  {n}")
            entry["status"] = status
        except Exception as e:  # noqa: BLE001 - report per file, keep going
            exit_code = 1
            entry.update(status="error", error=str(e))
            if not args.json:
                print(f"Error: {name}: {e}", file=sys.stderr)
        results.append(entry)
    if args.json:
        print(json.dumps({"success": exit_code == 0, "results": results}))
    if exit_code:
        sys.exit(exit_code)


# ---------------------------------------------------------------------------
# Subcommand: pack / preview-template  (scaffold-pack tooling)
# ---------------------------------------------------------------------------

def cmd_pack(args):
    """List built-in scaffold packs or export one for editing."""
    from ipcraft.scaffold import packtools

    try:
        if args.pack_command == "list":
            packs = packtools.list_packs(extra_dirs=args.pack_dir or [])
            if args.json:
                print(json.dumps({"success": True, "packs": packs}))
            else:
                width = max((len(p["name"]) for p in packs), default=0)
                for p in packs:
                    print(f"  {p['name']:<{width}}  [{p['category']}]  {p['description']}")
        else:
            result = packtools.export_pack(args.name, args.dest)
            if args.json:
                print(json.dumps({"success": True, **result}))
            else:
                n = len(result["templates"])
                print(f"✓ Exported pack '{args.name}' to {result['dest']}"
                      + (f" (copied {n} template{'s' if n != 1 else ''} for editing)" if n else ""))
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        err(f"Pack command failed: {e}", args, e)


def cmd_preview_template(args):
    """Render a .j2 template against an IP core's template context."""
    from ipcraft.scaffold import packtools

    try:
        print(packtools.preview_template(args.template, args.input), end="")
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        err(f"Template preview failed: {e}", args, e)


# ---------------------------------------------------------------------------
# Subcommand: import  (VHDL / SystemVerilog / _hw.tcl / component.xml -> .ip.yml)
# ---------------------------------------------------------------------------

def cmd_import(args):
    """Import an HDL file, Platform Designer _hw.tcl or Vivado component.xml as .ip.yml (+ .mm.yml)."""
    from ipcraft.scaffold.importers import import_source

    src = Path(args.input)
    if not src.exists():
        err(f"File not found: {src}", args)
    try:
        result = import_source(str(src), {
            "vendor": args.vendor, "library": args.library, "version": args.version,
            "detectBus": not args.no_detect_bus, "outputDir": args.output,
            "busLibraryDirs": args.bus_library,
        })
        report = result["report"]
        if report["hasKnownErrors"]:
            detail = " ".join(i["message"] for i in report["issues"] if i["severity"] == "error")
            err(f"Import blocked by bus conformance: {detail}", args)
        notes = [i["message"] for i in report["issues"]]
        targets = []
        for f in result["files"]:
            out = Path(f["dir"]) / f["name"]
            existing = out.read_text(encoding="utf-8") if out.exists() else None
            targets.append((out, f["content"], "created" if existing is None else "unchanged" if existing == f["content"] else "differs"))
        if args.dry_run:
            for out, _c, state in targets:
                print(f"Would write: {out}  ({state})")
            return
        written = []
        for out, content, state in targets:
            if state == "differs" and not args.force:
                err(f"Output file already exists and differs: {out}\n  Use --force / -f to overwrite.", args)
            if state != "unchanged":
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(content, encoding="utf-8")
            written.append((out, state))
        if args.json:
            print(json.dumps({"success": True, "kind": result["kind"], "summary": result["summary"],
                              "files": [{"path": str(o), "status": st} for o, st in written],
                              "warnings": result["warnings"] + notes}))
        else:
            for o, st in written:
                print(f"✓ {st if st != 'unchanged' else 'already up to date'}: {o}")
            if result["summary"]:
                print(f"  {result['summary']}")
            for w in result["warnings"] + notes:
                print(f"  Warning: {w}", file=sys.stderr)
            print("  Review the .ip.yml carefully before generating code.")
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        err(f"Import failed: {e}", args, e)


def cmd_instance(args):
    """Print a component-instantiation snippet for a VHDL / (System)Verilog file."""
    from ipcraft.scaffold.instance import build_instance

    try:
        snippet = build_instance(args.input)
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        err(f"Copy component instance failed: {e}", args, e)
        return
    if args.json:
        print(json.dumps({"success": True, "snippet": snippet}))
    else:
        print(snippet)


def cmd_busdef(args):
    """Convert IP-XACT bus/abstraction definitions (XML) to IPCraft bus-definition YAML."""
    import shutil

    from ipcraft.scaffold.importers.busdef_xml import convert_interfaces
    from ipcraft.scaffold.loader import vivado_interface_cache_dir

    try:
        if args.busdef_command == "scan-vivado":
            interfaces_dir = Path(args.install_dir) / "data" / "ip" / "interfaces"
            if not interfaces_dir.is_dir():
                err(f"Could not read Vivado interfaces directory at {interfaces_dir}", args)
            files = convert_interfaces([str(interfaces_dir)], "vivado")
            out_dir = Path(args.output) if args.output else Path(vivado_interface_cache_dir(args.version))
            replace = True
        else:
            files = convert_interfaces(args.paths, args.source)
            out_dir = Path(args.output) if args.output else Path(".")
            replace = False
        if replace:
            tmp = out_dir.parent / f".{out_dir.name}.tmp"
            shutil.rmtree(tmp, ignore_errors=True)
            tmp.mkdir(parents=True)
            for name, content in files.items():
                (tmp / name).write_text(content, encoding="utf-8")
            shutil.rmtree(out_dir, ignore_errors=True)
            tmp.rename(out_dir)
        else:
            out_dir.mkdir(parents=True, exist_ok=True)
            for name, content in files.items():
                target = out_dir / name
                if target.exists() and not args.force:
                    err(f"Output file already exists: {target}\n  Use --force / -f to overwrite.", args)
                target.write_text(content, encoding="utf-8")
        if args.json:
            print(json.dumps({"success": True, "count": len(files), "outputDir": str(out_dir), "files": sorted(files)}))
        else:
            print(f"✓ Converted {len(files)} bus definition(s) into {out_dir}")
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        err(f"Bus definition conversion failed: {e}", args, e)


# ---------------------------------------------------------------------------
# Subcommand: parse
# ---------------------------------------------------------------------------

def _parse_dry_run_report(
    ip_out: Path, mm_out: Path, write_mm: bool, ip_core
) -> None:
    """Print a dry-run preview of what would be written."""
    status_ip = "(overwrite)" if ip_out.exists() else "(new)"
    status_mm = "(overwrite)" if mm_out.exists() else "(new)"
    print(f"Would write: {ip_out}  {status_ip}")
    if write_mm:
        print(f"Would write: {mm_out}  {status_mm}")


def _safe_write(path: Path, content: str, force: bool, args) -> None:
    """Write *content* to *path*, respecting --force."""
    if path.exists() and not force:
        err(
            f"Output file already exists: {path}\n"
            "  Use --force / -f to overwrite.",
            args,
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


_HDL_EXTENSIONS = {".vhd", ".vhdl", ".v"}


def cmd_parse(args):
    """Parse an IP description file and generate .ip.yml (and optionally .mm.yml)."""
    from ipcraft.parser.vendor.parse_dispatcher import ParseDispatcher, ParseFormatError
    from ipcraft.generator.yaml.mm_yaml_generator import MmYamlGenerator

    input_path = Path(args.input)

    if not input_path.exists():
        err(f"File not found: {input_path}", args)

    # Legacy VHDL-only path: if --output is a plain .yml file and no new flags
    # are used, fall through to the old single-output behaviour for compatibility.
    output_arg = getattr(args, "output", None)
    write_mm   = getattr(args, "mm", False)
    dry_run    = getattr(args, "dry_run", False)

    # Detect whether we're in legacy mode (output points directly to a .yml file)
    legacy_mode = (
        output_arg
        and not write_mm
        and not dry_run
        and Path(output_arg).suffix.lower() in (".yml", ".yaml")
    )

    if legacy_mode and input_path.suffix.lower() in _HDL_EXTENSIONS:
        _cmd_parse_legacy(args, input_path, output_arg)
        return

    try:
        dispatcher = ParseDispatcher()
        fmt = dispatcher.detect_format(input_path)
        log(f"Detected format: {fmt}", args)

        ip_core = dispatcher.parse(
            input_path,
            detect_bus=not args.no_detect_bus,
        )

        # Apply CLI VLNV overrides
        if any([args.vendor != "user", args.library != "ip", args.version != "1.0"]):
            from ipcraft.model import VLNV
            ip_core = ip_core.model_copy(update={
                "vlnv": VLNV(
                    vendor=args.vendor if args.vendor != "user" else ip_core.vlnv.vendor,
                    library=args.library if args.library != "ip" else ip_core.vlnv.library,
                    name=ip_core.vlnv.name,
                    version=args.version if args.version != "1.0" else ip_core.vlnv.version,
                )
            })

        # Determine output directory
        if output_arg:
            output_dir = Path(output_arg)
            # If caller passed a .yml path directly (shouldn't happen here after
            # legacy check, but guard anyway)
            if output_dir.suffix.lower() in (".yml", ".yaml"):
                output_dir = output_dir.parent
        else:
            output_dir = input_path.parent

        ip_out = output_dir / f"{ip_core.vlnv.name.lower()}.ip.yml"
        mm_out = output_dir / f"{ip_core.vlnv.name.lower()}.mm.yml"

        if dry_run:
            _parse_dry_run_report(ip_out, mm_out, write_mm, ip_core)
            return

        # Write .ip.yml
        ip_yaml = IpYamlGenerator().generate_from_model(ip_core)
        _safe_write(ip_out, ip_yaml, args.force, args)

        # Write .mm.yml if requested
        if write_mm:
            discovered = getattr(ip_core, "_discovered_registers", None)
            mm_yaml = MmYamlGenerator().generate(ip_core, discovered_regs=discovered)
            _safe_write(mm_out, mm_yaml, args.force, args)

        if args.json:
            files = [str(ip_out)] + ([str(mm_out)] if write_mm else [])
            print(json.dumps({"success": True, "format": fmt, "files": files}))
        else:
            print(f"✓ Detected format: {fmt}")
            print(f"✓ Written: {ip_out}")
            if write_mm:
                print(f"✓ Written: {mm_out}")

    except SystemExit:
        raise
    except Exception as e:
        err(f"Parse failed: {e}", args, e)


def _cmd_parse_legacy(args, vhdl_path: Path, output_arg: str) -> None:
    """Original single-file VHDL → .ip.yml behaviour (backward compatible)."""
    try:
        if getattr(args, "verbose", False):
            print(f"Parsing {vhdl_path}...")

        generator = IpYamlGenerator(detect_bus=not args.no_detect_bus)
        yaml_content = generator.generate(
            vhdl_path=vhdl_path,
            vendor=args.vendor,
            library=args.library,
            version=args.version,
            memmap_path=Path(args.memmap) if getattr(args, "memmap", None) else None,
        )

        output_path = Path(output_arg)

        if output_path.exists() and not args.force:
            err(
                f"Output file already exists: {output_path}\n"
                "  Use --force / -f to overwrite.",
                args,
            )

        output_path.write_text(yaml_content)

        if args.json:
            print(json.dumps({"success": True, "output": str(output_path)}))
        else:
            print(f"✓ Generated: {output_path}")

    except SystemExit:
        raise
    except Exception as e:
        err(f"Parse failed: {e}", args, e)


# ---------------------------------------------------------------------------
# Subcommand: list-buses
# ---------------------------------------------------------------------------

def cmd_list_buses(args):
    """List available bus types from the bus library."""
    from ipcraft.model.bus_library import SUGGESTED_PREFIXES

    try:
        library = get_bus_library()
        bus_types = library.list_bus_types()

        if args.json:
            print(json.dumps({
                "success": True,
                "buses": library.get_all_bus_info(include_ports=True),
                "library": library.get_bus_library_dict(),
            }))
        else:
            if args.bus_type:
                defn = library.get_bus_definition(args.bus_type)
                if not defn:
                    err(
                        f"Unknown bus type: '{args.bus_type}'\n"
                        f"  Available: {', '.join(bus_types)}",
                        args,
                    )

                print(f"\n{defn.key} - {defn.bus_type.full_name}")
                print("\nSuggested prefixes:")
                prefixes = SUGGESTED_PREFIXES.get(defn.key, {})
                for mode, prefix in prefixes.items():
                    print(f"  {mode:8} {prefix}")

                if args.ports:
                    print(f"\nRequired ports ({len(defn.required_ports)}):")
                    for port in defn.required_ports:
                        width = f"[{port.width}]" if port.width else ""
                        direction = port.direction or "clk/rst"
                        print(f"  {port.name:20} {direction:6} {width}")

                    if defn.optional_ports:
                        print(f"\nOptional ports ({len(defn.optional_ports)}):")
                        for port in defn.optional_ports:
                            width = f"[{port.width}]" if port.width else ""
                            direction = port.direction or "clk/rst"
                            print(f"  {port.name:20} {direction:6} {width}")
            else:
                print("\nAvailable bus types:")
                for key in bus_types:
                    info = library.get_bus_info(key)
                    print(f"  {key:22} {info['vlnv']}")
                print("\nUse 'list-buses <TYPE>' for details, add --ports for port list")

    except SystemExit:
        raise
    except Exception as e:
        err(f"list-buses failed: {e}", args, e)


# ---------------------------------------------------------------------------
# Subcommand: init  (TUI wizard — implementation in cli_init.py)
# ---------------------------------------------------------------------------

def cmd_init(args):
    from ipcraft.cli_init import run_init_wizard
    run_init_wizard(args)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

_EXAMPLES = """\
Examples:
  ipcraft init                                      interactive wizard — browse examples or start fresh
  ipcraft init basic_peripheral.ip.yml             clone an existing IP core under a new name
  ipcraft new my_core --bus AXI4_LITE -o ./my_core  scaffold from template
  ipcraft generate my_core.ip.yml --output ./build  generate VHDL + vendor files
  ipcraft generate my_core.ip.yml --dry-run         preview changes without writing
  ipcraft generate my_core.ip.yml --watch           re-generate on file change
  ipcraft parse my_core.vhd -o my_core.ip.yml       reverse-engineer VHDL → YAML
  ipcraft validate my_core.ip.yml                   check YAML before generation
  ipcraft list-buses AXI4_LITE --ports              show bus port definitions
"""


def main():
    parser = argparse.ArgumentParser(
        prog="ipcraft",
        description="IP Core scaffolding and generation tool",
        epilog=_EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {_VERSION}"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # ---- init ----
    init_p = subparsers.add_parser(
        "init",
        help="Interactive wizard: scaffold + generate in one command",
        description=(
            "Guided step-by-step wizard that collects project details interactively,\n"
            "then scaffolds the YAML files and runs generation automatically.\n\n"
            "Pass an existing .ip.yml file to clone it under a new name without\n"
            "touching the original (template mode).\n\n"
            "For non-interactive use (scripts, CI) use 'new' + 'generate' instead."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    init_p.add_argument(
        "template",
        nargs="?",
        metavar="TEMPLATE.ip.yml",
        help="Existing .ip.yml to use as a starting point (skips mode selection)",
    )
    _add_common_args(init_p)
    init_p.set_defaults(func=cmd_init)

    # ---- validate ----
    val_p = subparsers.add_parser("validate", help="Validate IP core YAML")
    val_p.add_argument("input", help="IP core YAML file to validate")
    val_p.add_argument("--contracts", action="store_true",
                       help="Validate against the JSON schema and the declarative bus contracts (as the ipcraft-vscode extension does)")
    val_p.add_argument("--bus-library", action="append", metavar="DIR", help="Extra bus-definition directory with --contracts (repeatable)")
    val_p.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    _add_common_args(val_p)
    val_p.set_defaults(func=cmd_validate)

    # ---- new ----
    new_p = subparsers.add_parser(
        "new",
        help="Scaffold a new IP core from template (non-interactive)",
        description=(
            "Creates boilerplate .ip.yml and .mm.yml from the selected template.\n"
            "Use 'ipcraft init' for an interactive guided experience."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    new_p.add_argument("name", help="Name of the IP core (used as filename prefix)")
    new_p.add_argument("--vendor", default="ipcraft", help="VLNV vendor name (default: ipcraft)")
    new_p.add_argument("--library", default="examples", help="VLNV library name (default: examples)")
    new_p.add_argument("--version", default="1.0.0", help="VLNV version (default: 1.0.0)")
    new_p.add_argument(
        "--bus",
        help=(
            "Primary bus interface (e.g. AXI4_LITE, AVALON_MM). "
            "Run 'ipcraft list-buses' for all valid values."
        ),
    )
    new_p.add_argument("--output", "-o", default=".", help="Output directory (default: current directory)")
    new_p.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    _add_common_args(new_p)
    new_p.set_defaults(func=cmd_new)

    # ---- generate ----
    gen_p = subparsers.add_parser(
        "generate",
        help="Generate VHDL, testbench, and vendor files from IP core YAML",
        description=(
            "Files listed in fileSets with managed: false are never overwritten.\n"
            "Use --dry-run to preview which managed files would change.\n"
            "Use --watch to automatically re-generate when source YAML files change."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    gen_p.add_argument("input", help="IP core YAML file (.ip.yml)")
    gen_p.add_argument("--output", "--out", "-o", dest="output",
                       help="Output directory (default: same directory as input)")
    gen_p.add_argument(
        "--vendor",
        default="both",
        choices=["none", "intel", "xilinx", "both"],
        help="Vendor integration files to generate (default: both)",
    )
    gen_p.add_argument(
        "--testbench", action="store_true", default=True,
        help="Generate Cocotb testbench skeleton (default: on)",
    )
    gen_p.add_argument(
        "--no-testbench", dest="testbench", action="store_false",
        help="Skip Cocotb testbench generation",
    )
    gen_p.add_argument(
        "--regs", action="store_true", default=True,
        help="Generate standalone register bank (*_regs.vhd) (default: on)",
    )
    gen_p.add_argument(
        "--no-regs", dest="regs", action="store_false",
        help="Skip standalone register bank generation",
    )
    gen_p.add_argument(
        "--update-yaml", action="store_true", default=True,
        help="Write generated fileSets back into the input YAML (default: on)",
    )
    gen_p.add_argument(
        "--no-update-yaml", dest="update_yaml", action="store_false",
        help="Do not modify the input YAML file",
    )
    gen_p.add_argument(
        "--json", action="store_true",
        help="Machine-readable JSON output; progress events go to stderr as JSON Lines",
    )
    gen_p.add_argument(
        "--progress", action="store_true",
        help="Print a line for every file written (verbose file list)",
    )
    gen_p.add_argument(
        "--dry-run", action="store_true",
        help="Preview which files would be written or skipped without touching the filesystem",
    )
    gen_p.add_argument(
        "--watch", action="store_true",
        help="Watch input YAML files and re-generate automatically on change (Ctrl+C to stop)",
    )
    gen_p.add_argument(
        "--template-dir", "--methodology",
        dest="template_dir",
        action="append",
        help=(
            "Path to a custom Jinja2 template directory (overrides built-in templates). "
            "Can be specified multiple times. "
            "See docs/user-guide/templates.md for the expected directory layout."
        ),
    )
    gen_p.add_argument(
        "--dump-context", action="store_true",
        help=(
            "Write the full Jinja2 template context to template_context.json. "
            "Useful when developing or debugging custom --template-dir templates."
        ),
    )
    _add_indent_args(gen_p)
    _add_scaffold_args(gen_p)
    _add_common_args(gen_p)
    gen_p.set_defaults(func=cmd_generate)

    # ---- verify ----
    ver_p = subparsers.add_parser(
        "verify",
        help="Check a generated directory against a fresh generation (drift check)",
        description=(
            "Regenerates the IP core in memory and diffs it against GENERATED_DIR.\n"
            "Exits 1 if any file is stale, missing, or orphaned. managed: false files are exempt."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ver_p.add_argument("input", help="IP core YAML file (.ip.yml)")
    ver_p.add_argument("generated_dir", metavar="GENERATED_DIR", help="Directory holding generated files")
    ver_p.add_argument("--vendor", default="both", choices=["none", "intel", "xilinx", "both"],
                       help="Vendor integration files to expect (default: both)")
    ver_p.add_argument("--no-testbench", dest="testbench", action="store_false", default=True,
                       help="Do not expect a Cocotb testbench")
    ver_p.add_argument("--no-regs", dest="regs", action="store_false", default=True,
                       help="Do not expect a standalone register bank")
    ver_p.add_argument("--template-dir", "--methodology", dest="template_dir", action="append",
                       help="Custom Jinja2 template directory (repeatable)")
    ver_p.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    _add_indent_args(ver_p)
    _add_scaffold_args(ver_p)
    _add_common_args(ver_p)
    ver_p.set_defaults(func=cmd_verify)

    # ---- migrate ----
    mig_p = subparsers.add_parser(
        "migrate",
        help="Upgrade .ip.yml to the latest format version and convert legacy snake_case keys",
    )
    mig_p.add_argument("paths", nargs="+", metavar="FILE", help=".ip.yml / .mm.yml files to convert")
    mig_p.add_argument("--vendor-targets", action="store_true",
                       help="Also rewrite the legacy 'vendor: altera|xilinx|both' field to 'targets: [...]'")
    mig_p.add_argument("--check", action="store_true",
                       help="Report files needing conversion without writing; exit 1 if any do")
    mig_p.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    _add_common_args(mig_p)
    mig_p.set_defaults(func=cmd_migrate)

    # ---- pack ----
    pack_p = subparsers.add_parser("pack", help="List or export scaffold packs")
    pack_sub = pack_p.add_subparsers(dest="pack_command", required=True)
    pl = pack_sub.add_parser("list", help="List the built-in scaffold packs")
    pl.add_argument("--pack-dir", action="append", metavar="DIR", help="Also list packs found in DIR (repeatable)")
    pl.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    _add_common_args(pl)
    pl.set_defaults(func=cmd_pack)
    pe = pack_sub.add_parser("export", help="Copy a built-in pack (and the templates it uses) to a directory for editing")
    pe.add_argument("name", help="Built-in pack name, e.g. builtin-ipcraft")
    pe.add_argument("dest", help="Destination directory for the exported pack")
    pe.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    _add_common_args(pe)
    pe.set_defaults(func=cmd_pack)

    # ---- preview-template ----
    pv = subparsers.add_parser("preview-template", help="Render a .j2 template against an IP core's template context")
    pv.add_argument("template", help="Template file (.j2)")
    pv.add_argument("input", help="IP core YAML file (.ip.yml)")
    _add_common_args(pv)
    pv.set_defaults(func=cmd_preview_template, json=False)

    # ---- import ----
    imp_p = subparsers.add_parser(
        "import",
        help="Import VHDL / SystemVerilog / Platform Designer _hw.tcl / Vivado component.xml as .ip.yml",
        description=(
            "Pack-engine importer shared with the ipcraft-vscode extension. For a component.xml inside\n"
            "xilinx/ or altera/ the .ip.yml (and .mm.yml) are written one directory up. Existing files\n"
            "are never overwritten without --force."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    imp_p.add_argument("input", help="Source file: .vhd/.vhdl, .v/.sv, *_hw.tcl or component.xml")
    imp_p.add_argument("--output", "--out", "-o", help="Output directory (default: next to the source)")
    imp_p.add_argument("--vendor", help="VLNV vendor (default: user for HDL; git e-mail domain or 'ipcraft' for _hw.tcl)")
    imp_p.add_argument("--library", help="VLNV library (default: ip)")
    imp_p.add_argument("--version", help="VLNV version (default: 1.0.0; HDL sources only)")
    imp_p.add_argument("--no-detect-bus", action="store_true", help="Do not detect bus interfaces from port names (HDL only)")
    imp_p.add_argument("--bus-library", action="append", metavar="DIR", help="Extra bus-definition directory (repeatable)")
    imp_p.add_argument("--dry-run", action="store_true", help="Show what would be written without writing")
    imp_p.add_argument("--force", "-f", action="store_true", help="Overwrite existing output files")
    imp_p.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    _add_common_args(imp_p)
    imp_p.set_defaults(func=cmd_import)

    # ---- instance ----
    inst_p = subparsers.add_parser("instance", help="Print a component-instantiation snippet for a VHDL / SystemVerilog file")
    inst_p.add_argument("input", help="HDL source file (.vhd, .vhdl, .sv, .v)")
    inst_p.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    _add_common_args(inst_p)
    inst_p.set_defaults(func=cmd_instance)

    # ---- busdef ----
    bd_p = subparsers.add_parser("busdef", help="Convert IP-XACT bus definitions (XML) to bus-definition YAML")
    bd_sub = bd_p.add_subparsers(dest="busdef_command", required=True)
    bi = bd_sub.add_parser("import", help="Convert busDefinition/abstractionDefinition XML files or directories")
    bi.add_argument("paths", nargs="+", metavar="PATH", help="XML files or directories to scan")
    bi.add_argument("--output", "--out", "-o", help="Output directory (default: current directory)")
    bi.add_argument("--source", default="workspace", choices=["workspace", "vivado"], help="Provenance recorded in each definition")
    bi.add_argument("--force", "-f", action="store_true", help="Overwrite existing files")
    bi.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    _add_common_args(bi)
    bi.set_defaults(func=cmd_busdef)
    bs = bd_sub.add_parser("scan-vivado", help="Cache the interface definitions of a Vivado installation (used by generate/verify/import)")
    bs.add_argument("install_dir", help="Vivado installation directory (contains data/ip/interfaces)")
    bs.add_argument("--version", help="Cache this scan under a version label (default: the unversioned cache)")
    bs.add_argument("--output", "--out", "-o", help="Write here instead of the shared IPCraft cache directory")
    bs.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    _add_common_args(bs)
    bs.set_defaults(func=cmd_busdef, force=True)

    # ---- parse ----
    parse_p = subparsers.add_parser(
        "parse",
        help="Parse a source file (.vhd, .v, _hw.tcl, component.xml) and generate .ip.yml",
    )
    parse_p.add_argument(
        "input",
        help="Source file to parse (.vhd/.vhdl, .v, _hw.tcl, component.xml)",
    )
    parse_p.add_argument(
        "--output", "-o",
        help=(
            "Output directory (default: same directory as input file). "
            "For VHDL files with a direct .yml path this still works as before."
        ),
    )
    parse_p.add_argument(
        "--mm", action="store_true",
        help="Also generate a .mm.yml register-map skeleton alongside the .ip.yml",
    )
    parse_p.add_argument(
        "--dry-run", action="store_true",
        help="Print which files would be written without writing anything",
    )
    parse_p.add_argument("--vendor", default="user", help="VLNV vendor name (default: user)")
    parse_p.add_argument("--library", default="ip", help="VLNV library name (default: ip)")
    parse_p.add_argument("--version", default="1.0", help="VLNV version (default: 1.0)")
    parse_p.add_argument(
        "--no-detect-bus", action="store_true",
        help="Disable automatic bus interface detection from port name prefixes",
    )
    parse_p.add_argument(
        "--memmap",
        help="Path to an existing memory map file to reference (VHDL legacy mode only)",
    )
    parse_p.add_argument(
        "--force", "-f", action="store_true",
        help="Overwrite existing output files",
    )
    parse_p.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    _add_common_args(parse_p)
    parse_p.set_defaults(func=cmd_parse)

    # ---- list-buses ----
    buses_p = subparsers.add_parser(
        "list-buses",
        help="List available bus types from the built-in library",
    )
    buses_p.add_argument(
        "bus_type", nargs="?",
        help="Bus type key to show details for (e.g. AXI4_LITE)",
    )
    buses_p.add_argument("--ports", action="store_true", help="Show required and optional port lists")
    buses_p.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    _add_common_args(buses_p)
    buses_p.set_defaults(func=cmd_list_buses)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

