#!/usr/bin/env python3
"""
ipcraft - IP Core scaffolding and generation tool.

Usage:
    python scripts/ipcraft.py generate my_core.ip.yml --output ./generated
    python scripts/ipcraft.py generate my_core.ip.yml --json --progress  # VS Code mode
    python scripts/ipcraft.py parse my_core.vhd --output my_core.ip.yml

Subcommands:
    generate    Generate VHDL/testbench from IP core YAML
    parse       Parse VHDL file and generate IP core YAML
    list-buses  List available bus types from library
    validate    Validate IP core YAML (future)
    new         Create new IP core from template (future)
"""
import argparse
import json
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from ipcraft.generator.hdl.ipcore_project_generator import IpCoreProjectGenerator
from ipcraft.generator.yaml.ip_yaml_generator import IpYamlGenerator
from ipcraft.model.bus_library import BusLibrary, get_bus_library
from ipcraft.parser.yaml.ip_yaml_parser import YamlIpCoreParser

# Map YAML bus types to generator templates
BUS_TYPE_MAP = {
    "AXI4L": "axil",
    "AXI4LITE": "axil",
    "AXILITE": "axil",
    "AVALONMM": "avmm",
    "AVMM": "avmm",
    "AVALON_MM": "avmm",
    "AVALON-MM": "avmm",
}


def get_bus_type(ip_core) -> str:
    """Extract bus type from IP core's bus interfaces."""
    for bus in ip_core.bus_interfaces:
        if bus.mode == "slave" and bus.memory_map_ref:
            bus_type = bus.type.value if hasattr(bus.type, "value") else str(bus.type)
            return BUS_TYPE_MAP.get(bus_type.upper(), "axil")
    return "axil"


def log(msg: str, use_progress: bool, use_json: bool):
    """Output progress message if enabled."""
    if use_progress and use_json:
        print(f"PROGRESS: {msg}", flush=True)
    elif use_progress:
        print(msg)


def cmd_generate(args):
    """Generate VHDL files from IP core YAML."""
    output_base = args.output or os.path.dirname(args.input)

    try:
        log("Parsing IP core YAML...", args.progress, args.json)
        ip_core = YamlIpCoreParser().parse_file(args.input)

        bus_type = get_bus_type(ip_core)
        log(f"Detected bus type: {bus_type}", args.progress, args.json)

        log("Generating VHDL files...", args.progress, args.json)
        gen = IpCoreProjectGenerator()
        all_files = gen.generate_all(
            ip_core,
            bus_type=bus_type,
            structured=True,
            vendor=args.vendor,
            include_testbench=args.testbench,
            include_regs=args.regs,
        )

        log(f"Writing {len(all_files)} files...", args.progress, args.json)
        written = {}
        for filepath, content in all_files.items():
            full_path = os.path.join(output_base, filepath)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            Path(full_path).write_text(content)
            written[filepath] = full_path
            log(f"  Written: {filepath}", args.progress, args.json)

        # Update IP core YAML with fileSets
        if args.update_yaml:
            gen.update_ipcore_filesets(
                os.path.abspath(args.input),
                all_files,
                include_regs=args.regs,
                vendor=args.vendor,
                include_testbench=args.testbench,
            )

        log("Generation complete!", args.progress, args.json)

        if args.json:
            # JSON output for VS Code integration
            print(
                json.dumps(
                    {"success": True, "files": written, "count": len(written), "busType": bus_type}
                )
            )
        else:
            # Human-readable output
            name = ip_core.vlnv.name if ip_core.vlnv else "ipcore"
            print(f"\n✓ Generated {len(all_files)} files to: {output_base}")
            print(f"\nDirectory structure for '{name}':")
            print(f"  rtl/")
            print(f"    {name}_pkg.vhd      - Package (types, records)")
            print(f"    {name}.vhd          - Top-level entity")
            print(f"    {name}_core.vhd     - Core logic")
            print(f"    {name}_axil.vhd     - AXI-Lite bus wrapper")
            print(f"    {name}_regs.vhd     - Register bank")
            print(f"  tb/")
            print(f"    {name}_test.py      - Cocotb testbench")
            print(f"    Makefile            - Simulation makefile")
            print(f"  intel/")
            print(f"    {name}_hw.tcl       - Platform Designer")
            print(f"  xilinx/")
            print(f"    component.xml       - IP-XACT")
            print(f"    xgui/{name}_v*.tcl  - Vivado GUI")

    except Exception as e:
        if args.json:
            print(json.dumps({"success": False, "error": str(e)}))
        else:
            print(f"Error: {e}")
            import traceback

            traceback.print_exc()
        sys.exit(1)


def cmd_parse(args):
    """Parse VHDL file and generate IP core YAML."""
    vhdl_path = Path(args.input)

    if not vhdl_path.exists():
        print(f"Error: VHDL file not found: {vhdl_path}")
        sys.exit(1)

    try:
        generator = IpYamlGenerator(detect_bus=not args.no_detect_bus)

        yaml_content = generator.generate(
            vhdl_path=vhdl_path,
            vendor=args.vendor,
            library=args.library,
            version=args.version,
            memmap_path=Path(args.memmap) if args.memmap else None,
        )

        # Determine output path
        if args.output:
            output_path = Path(args.output)
        else:
            # Extract entity name from YAML content
            import yaml as yaml_lib

            data = yaml_lib.safe_load(yaml_content)
            entity_name = data.get("vlnv", {}).get("name", "output")
            output_path = vhdl_path.parent / f"{entity_name}.ip.yml"

        # Check if output exists
        if output_path.exists() and not args.force:
            print(f"Error: Output file exists: {output_path}")
            print("Use --force to overwrite")
            sys.exit(1)

        # Write output
        output_path.write_text(yaml_content)

        if args.json:
            print(
                json.dumps(
                    {
                        "success": True,
                        "output": str(output_path),
                    }
                )
            )
        else:
            print(f"✓ Generated: {output_path}")

    except Exception as e:
        if args.json:
            print(json.dumps({"success": False, "error": str(e)}))
        else:
            print(f"Error: {e}")
            import traceback

            traceback.print_exc()
        sys.exit(1)


def cmd_list_buses(args):
    """List available bus types from the bus library."""
    from ipcraft.model.bus_library import SUGGESTED_PREFIXES

    try:
        library = get_bus_library()
        bus_types = library.list_bus_types()

        if args.json:
            # JSON output for VS Code integration - include full library format
            print(
                json.dumps(
                    {
                        "success": True,
                        "buses": library.get_all_bus_info(include_ports=True),
                        "library": library.get_bus_library_dict(),
                    }
                )
            )
        else:
            if args.bus_type:
                # Show details for specific bus type
                defn = library.get_bus_definition(args.bus_type)
                if not defn:
                    print(f"Error: Unknown bus type: {args.bus_type}")
                    print(f"Available: {', '.join(bus_types)}")
                    sys.exit(1)

                print(f"\n{defn.key} - {defn.bus_type.full_name}")
                print(f"\nSuggested prefixes:")
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
                # List all bus types
                print("\nAvailable bus types:")
                for key in bus_types:
                    info = library.get_bus_info(key)
                    print(f"  {key:12} - {info['vlnv']}")
                print("\nUse 'list-buses <TYPE>' for details, add --ports for port list")

    except Exception as e:
        if args.json:
            print(json.dumps({"success": False, "error": str(e)}))
        else:
            print(f"Error: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        prog="ipcraft", description="IP Core scaffolding and generation tool"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # generate subcommand
    gen_parser = subparsers.add_parser("generate", help="Generate VHDL from IP core YAML")
    gen_parser.add_argument("input", help="IP core YAML file")
    gen_parser.add_argument("--output", "-o", help="Output directory (default: same as input)")
    gen_parser.add_argument(
        "--vendor",
        default="both",
        choices=["none", "intel", "xilinx", "both"],
        help="Vendor integration files to generate",
    )
    gen_parser.add_argument(
        "--testbench",
        action="store_true",
        default=True,
        help="Generate cocotb testbench (default: True)",
    )
    gen_parser.add_argument("--no-testbench", dest="testbench", action="store_false")
    gen_parser.add_argument(
        "--regs", action="store_true", default=True, help="Include standalone register bank"
    )
    gen_parser.add_argument("--no-regs", dest="regs", action="store_false")
    gen_parser.add_argument(
        "--update-yaml", action="store_true", default=True, help="Update IP core YAML with fileSets"
    )
    gen_parser.add_argument("--no-update-yaml", dest="update_yaml", action="store_false")
    gen_parser.add_argument(
        "--json", action="store_true", help="JSON output (for VS Code integration)"
    )
    gen_parser.add_argument("--progress", action="store_true", help="Enable progress output")
    gen_parser.set_defaults(func=cmd_generate)

    # parse subcommand
    parse_parser = subparsers.add_parser("parse", help="Parse VHDL file and generate IP core YAML")
    parse_parser.add_argument("input", help="VHDL source file")
    parse_parser.add_argument(
        "--output", "-o", help="Output .ip.yml path (default: {entity}.ip.yml)"
    )
    parse_parser.add_argument("--vendor", default="user", help="VLNV vendor name (default: user)")
    parse_parser.add_argument("--library", default="ip", help="VLNV library name (default: ip)")
    parse_parser.add_argument("--version", default="1.0", help="VLNV version (default: 1.0)")
    parse_parser.add_argument(
        "--no-detect-bus", action="store_true", help="Disable automatic bus interface detection"
    )
    parse_parser.add_argument("--memmap", help="Path to memory map file to reference")
    parse_parser.add_argument(
        "--force", "-f", action="store_true", help="Overwrite existing output file"
    )
    parse_parser.add_argument(
        "--json", action="store_true", help="JSON output (for VS Code integration)"
    )
    parse_parser.set_defaults(func=cmd_parse)

    # list-buses subcommand
    buses_parser = subparsers.add_parser("list-buses", help="List available bus types")
    buses_parser.add_argument("bus_type", nargs="?", help="Bus type to show details for")
    buses_parser.add_argument("--ports", action="store_true", help="Show port details")
    buses_parser.add_argument("--json", action="store_true", help="JSON output")
    buses_parser.set_defaults(func=cmd_list_buses)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
