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
from ipcraft.generator.yaml.ip_yaml_generator import IpYamlGenerator
from ipcraft.model.bus_library import get_bus_library
from ipcraft.parser.yaml.ip_yaml_parser import YamlIpCoreParser
from ipcraft.generator.yaml.boilerplate import generate_new_ip
from ipcraft.utils.diagram import generate_ascii_diagram


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

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

def cmd_validate(args):
    """Validate IP core YAML."""
    from ipcraft.model.validators import IpCoreValidator

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
    import os

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
        original_cwd = os.getcwd()
        diagram = None
        try:
            if args.output and args.output != ".":
                os.chdir(args.output)
            filename = ip_path.name if args.output and args.output != "." else str(ip_path)
            ip_core = YamlIpCoreParser().parse_file(filename)
            diagram = generate_ascii_diagram(ip_core)
        finally:
            os.chdir(original_cwd)

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


# ---------------------------------------------------------------------------
# Subcommand: generate  (core logic extracted for reuse by --watch and init)
# ---------------------------------------------------------------------------

def _run_generate_core(args, output_base: Path) -> dict:
    """Run generation and return the written-files dict.

    Raises on error; does not call sys.exit directly.
    Returns an empty dict on --dry-run (nothing written).
    """
    t_start = time.monotonic()

    if not getattr(args, "json", False):
        print(f"Generating from {args.input}...", end=" ", flush=True)

    log("Parsing IP core YAML...", args)
    ip_core = YamlIpCoreParser().parse_file(args.input)

    bus_type = get_bus_type(ip_core)
    log(f"Detected bus type: {bus_type}", args)

    log("Generating files...", args)
    gen = IpCoreProjectGenerator(template_dir=args.template_dir)

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
        dump_context=args.dump_context,
    )

    # ---- Dry-run: report and return without writing ----
    if getattr(args, "dry_run", False):
        print()
        _dry_run_report(all_files, output_base, ip_core)
        return {}

    log(f"Writing {len(all_files)} files...", args)

    # Collect files the user has marked as unmanaged (should not be overwritten).
    unmanaged_files = set()
    if ip_core.file_sets:
        for fileset in ip_core.file_sets:
            for f in fileset.files:
                if not getattr(f, "managed", True):
                    unmanaged_files.add(Path(f.path).name)

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
    unmanaged_files = set()
    if ip_core.file_sets:
        for fileset in ip_core.file_sets:
            for f in fileset.files:
                if not getattr(f, "managed", True):
                    unmanaged_files.add(Path(f.path).name)

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
# Subcommand: parse
# ---------------------------------------------------------------------------

def cmd_parse(args):
    """Parse VHDL file and generate IP core YAML."""
    vhdl_path = Path(args.input)

    if not vhdl_path.exists():
        err(f"VHDL file not found: {vhdl_path}", args)

    try:
        if getattr(args, "verbose", False):
            print(f"Parsing {vhdl_path}...")

        generator = IpYamlGenerator(detect_bus=not args.no_detect_bus)
        yaml_content = generator.generate(
            vhdl_path=vhdl_path,
            vendor=args.vendor,
            library=args.library,
            version=args.version,
            memmap_path=Path(args.memmap) if args.memmap else None,
        )

        if args.output:
            output_path = Path(args.output)
        else:
            import yaml as yaml_lib
            data = yaml_lib.safe_load(yaml_content)
            entity_name = data.get("vlnv", {}).get("name", "output")
            output_path = vhdl_path.parent / f"{entity_name}.ip.yml"

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
  ipcraft init                                      interactive wizard for new users
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
            "For non-interactive use (scripts, CI) use 'new' + 'generate' instead."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_common_args(init_p)
    init_p.set_defaults(func=cmd_init)

    # ---- validate ----
    val_p = subparsers.add_parser("validate", help="Validate IP core YAML")
    val_p.add_argument("input", help="IP core YAML file to validate")
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
    gen_p.add_argument("--output", "-o", help="Output directory (default: same directory as input)")
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
    _add_common_args(gen_p)
    gen_p.set_defaults(func=cmd_generate)

    # ---- parse ----
    parse_p = subparsers.add_parser(
        "parse",
        help="Parse a VHDL file and generate an IP core YAML",
    )
    parse_p.add_argument("input", help="VHDL source file to parse")
    parse_p.add_argument(
        "--output", "-o",
        help="Output .ip.yml path (default: {entity_name}.ip.yml beside the input)",
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
        help="Path to an existing memory map file to reference in the output YAML",
    )
    parse_p.add_argument(
        "--force", "-f", action="store_true",
        help="Overwrite the output file if it already exists",
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

