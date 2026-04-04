"""
ipcraft init — Interactive TUI wizard for scaffolding a new IP core.

Collects project details in 6 phases, then calls new + generate automatically.
Uses questionary for prompts.
"""

import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

import questionary
from questionary import Choice


# ---------------------------------------------------------------------------
# Bus type display options
# ---------------------------------------------------------------------------

# Sentinel string used in questionary Choice value to mean "no bus".
# We cannot use None as a value because questionary.ask() also returns None
# on Ctrl+C, which would be ambiguous.
_NO_BUS_SENTINEL = "__NONE__"

_BUS_OPTIONS = [
    Choice(
        title="AXI4-Lite   — Control/status register slave  (most common)",
        value="AXI4_LITE",
    ),
    Choice(
        title="AXI4-Full   — High-bandwidth burst slave  (DMA engines)",
        value="AXI4_FULL",
    ),
    Choice(
        title="AXI-Stream  — Streaming data path  (DSP, video pipelines)",
        value="AXI_STREAM",
    ),
    Choice(
        title="Avalon-MM   — Intel/Quartus register slave",
        value="AVALON_MM",
    ),
    Choice(
        title="Avalon-ST   — Intel/Quartus streaming path",
        value="AVALON_ST",
    ),
    Choice(
        title="None        — No bus interface  (standalone / custom)",
        value=_NO_BUS_SENTINEL,
    ),
]

# Default clock / reset names and polarity for each bus type.
_BUS_CLK_DEFAULTS: dict = {
    "AXI4_LITE":  ("s_axi_aclk",   "s_axi_resetn",  "active_low"),
    "AXI4_FULL":  ("s_axi_aclk",   "s_axi_resetn",  "active_low"),
    "AXI_STREAM": ("s_axis_aclk",  "s_axis_resetn", "active_low"),
    "AVALON_MM":  ("clk",          "reset",         "active_high"),
    "AVALON_ST":  ("clk",          "reset",         "active_high"),
}

# Bus key to pass to generate_new_ip (which uses older alias keys).
_BUS_NEW_KEY: dict = {
    "AXI4_LITE":  "AXI4L",
    "AXI4_FULL":  "AXI4",
    "AXI_STREAM": "AXIS",
    "AVALON_MM":  "AVALON_MM",
    "AVALON_ST":  "AVALON_ST",
}

# Smart port suggestions keyed by IP name keywords.
_PORT_SUGGESTIONS: dict = {
    "pwm":   [("o_pwm",  1, "out")],
    "uart":  [("o_tx",   1, "out"), ("i_rx", 1, "in")],
    "spi":   [("o_sclk", 1, "out"), ("o_mosi", 1, "out"),
              ("i_miso", 1, "in"),  ("o_cs_n", 1, "out")],
    "gpio":  [("io_gpio", 8, "inout")],
    "irq":   [("o_irq",  1, "out")],
    "timer": [("o_irq",  1, "out")],
    "dma":   [("o_irq",  1, "out")],
}


# ---------------------------------------------------------------------------
# Input validators
# ---------------------------------------------------------------------------

def _valid_identifier(value: str):
    if re.match(r"^[a-z][a-z0-9_]*$", value.strip()):
        return True
    return "Use lowercase letters, digits, and underscores (must start with a letter)"


def _valid_version(value: str):
    if re.match(r"^\d+\.\d+(\.\d+)?$", value.strip()):
        return True
    return "Use semver format: 1.0.0 or 1.0"


def _valid_width(value: str):
    try:
        if int(value.strip()) >= 1:
            return True
    except ValueError:
        pass
    return "Enter a positive integer"


# ---------------------------------------------------------------------------
# Wizard phases
# ---------------------------------------------------------------------------

def _phase_identity() -> Optional[dict]:
    """Phase 1 — collect core name, vendor, library, version."""
    print()
    questionary.print("Phase 1/6 — IP Core Identity", style="bold")
    questionary.print(
        "  (Press Enter to accept defaults, Ctrl+C to cancel)\n",
        style="fg:ansidarkgray",
    )

    name = questionary.text(
        "Core name:",
        default="my_core",
        validate=_valid_identifier,
        instruction="(lowercase, underscores only)",
    ).ask()
    if name is None:
        return None

    vendor = questionary.text("Vendor:", default="ipcraft").ask()
    if vendor is None:
        return None

    library = questionary.text("Library:", default="ip").ask()
    if library is None:
        return None

    version = questionary.text(
        "Version:", default="1.0.0", validate=_valid_version
    ).ask()
    if version is None:
        return None

    return {
        "name": name.strip(),
        "vendor": vendor.strip(),
        "library": library.strip(),
        "version": version.strip(),
    }


def _phase_bus() -> Optional[str]:
    """Phase 2 — select primary bus interface.

    Returns a bus key string, _NO_BUS_SENTINEL, or None on Ctrl+C.
    """
    print()
    questionary.print("Phase 2/6 — Primary Bus Interface", style="bold")

    result = questionary.select(
        "Select bus type:",
        choices=_BUS_OPTIONS,
        use_shortcuts=False,
    ).ask()
    return result  # None means Ctrl+C


def _phase_clocks(bus: Optional[str]) -> Optional[dict]:
    """Phase 3 — clock name, reset name, and polarity."""
    print()
    questionary.print("Phase 3/6 — Clocks & Resets", style="bold")

    effective_bus = bus if bus and bus != _NO_BUS_SENTINEL else None
    defaults = _BUS_CLK_DEFAULTS.get(effective_bus, ("clk", "rst_n", "active_low"))
    default_clk, default_rst, default_polarity = defaults

    clk_name = questionary.text("Clock port name:", default=default_clk).ask()
    if clk_name is None:
        return None

    rst_name = questionary.text("Reset port name:", default=default_rst).ask()
    if rst_name is None:
        return None

    polarity = questionary.select(
        "Reset polarity:",
        choices=[
            Choice(
                "Active-low  (typical for AXI — name often ends in _n or _resetn)",
                value="active_low",
            ),
            Choice(
                "Active-high (typical for Avalon)",
                value="active_high",
            ),
        ],
        default="active_low" if default_polarity == "active_low" else "active_high",
    ).ask()
    if polarity is None:
        return None

    return {
        "clk_name": clk_name.strip(),
        "rst_name": rst_name.strip(),
        "polarity": polarity,
    }


def _phase_ports(name: str) -> Optional[List[Tuple[str, int, str]]]:
    """Phase 4 — extra (non-bus) ports."""
    print()
    questionary.print("Phase 4/6 — Extra Ports", style="bold")
    questionary.print(
        "  Add non-bus ports to the top-level entity.\n",
        style="fg:ansidarkgray",
    )

    # Offer smart suggestions based on keywords in the IP name.
    suggestions: List[Tuple[str, int, str]] = []
    for keyword, ports in _PORT_SUGGESTIONS.items():
        if keyword in name.lower():
            suggestions.extend(ports)

    if suggestions:
        suggestion_str = ", ".join(f"{p[0]}[{p[1]}] {p[2]}" for p in suggestions)
        print(f"  Suggestion for '{name}': {suggestion_str}")
        use_suggestions = questionary.confirm(
            "  Accept suggested ports?", default=True
        ).ask()
        if use_suggestions is None:
            return None
        if use_suggestions:
            return suggestions

    ports: List[Tuple[str, int, str]] = []
    print("  Enter ports one at a time. Leave name blank to finish.")
    while True:
        port_name = questionary.text("  Port name (blank to finish):").ask()
        if port_name is None:
            return None
        if not port_name.strip():
            break

        width_str = questionary.text(
            f"  Width of '{port_name}':", default="1", validate=_valid_width
        ).ask()
        if width_str is None:
            return None

        direction = questionary.select(
            f"  Direction of '{port_name}':",
            choices=["in", "out", "inout"],
        ).ask()
        if direction is None:
            return None

        ports.append((port_name.strip(), int(width_str.strip()), direction))

    return ports


def _phase_output_options(name: str) -> Optional[dict]:
    """Phase 5 — what to generate and output directory."""
    print()
    questionary.print("Phase 5/6 — Output Options", style="bold")

    vendor_choices = questionary.checkbox(
        "Vendor integration files:",
        choices=[
            Choice("Intel  (Platform Designer .tcl)", value="intel", checked=True),
            Choice("Xilinx (IP-XACT component.xml + Vivado xgui .tcl)", value="xilinx", checked=True),
        ],
    ).ask()
    if vendor_choices is None:
        return None

    if set(vendor_choices) == {"intel", "xilinx"}:
        vendor_flag = "both"
    elif vendor_choices == ["intel"]:
        vendor_flag = "intel"
    elif vendor_choices == ["xilinx"]:
        vendor_flag = "xilinx"
    else:
        vendor_flag = "none"

    gen_choices = questionary.checkbox(
        "Additional outputs:",
        choices=[
            Choice("Cocotb testbench skeleton   (_test.py + Makefile)", value="testbench", checked=True),
            Choice("Standalone register bank    (_regs.vhd)", value="regs", checked=True),
        ],
    ).ask()
    if gen_choices is None:
        return None

    output_dir = questionary.text("Output directory:", default=f"./{name}").ask()
    if output_dir is None:
        return None

    return {
        "vendor_flag": vendor_flag,
        "include_testbench": "testbench" in gen_choices,
        "include_regs": "regs" in gen_choices,
        "output_dir": output_dir.strip(),
    }


def _phase_confirm(
    name: str,
    identity: dict,
    bus: Optional[str],
    clocks: dict,
    ports: List[Tuple[str, int, str]],
    output_opts: dict,
) -> Optional[bool]:
    """Phase 6 — show equivalent CLI command and ask to proceed."""
    print()
    questionary.print("Phase 6/6 — Confirm & Generate", style="bold")

    effective_bus = bus if bus and bus != _NO_BUS_SENTINEL else None
    bus_key_for_new = _BUS_NEW_KEY.get(effective_bus, effective_bus) if effective_bus else None

    cli_new = (
        f"ipcraft new {name}"
        f" --vendor {identity['vendor']}"
        f" --library {identity['library']}"
        f" --version {identity['version']}"
    )
    if bus_key_for_new:
        cli_new += f" --bus {bus_key_for_new}"
    cli_new += f" --output {output_opts['output_dir']}"

    cli_gen = f"ipcraft generate {output_opts['output_dir']}/{name}.ip.yml"
    cli_gen += f" --vendor {output_opts['vendor_flag']}"
    if not output_opts["include_testbench"]:
        cli_gen += " --no-testbench"
    if not output_opts["include_regs"]:
        cli_gen += " --no-regs"

    sep = "─" * 60
    print()
    print(f"  {sep}")
    print("  Equivalent CLI command (copy for scripts / CI):\n")
    print(f"    {cli_new} \\")
    print(f"      && {cli_gen}")
    print(f"  {sep}")
    print()

    return questionary.confirm("Generate now?", default=True).ask()


# ---------------------------------------------------------------------------
# Post-processing: patch generated .ip.yml with wizard choices
# ---------------------------------------------------------------------------

def _patch_ip_yaml(
    ip_path: Path,
    clocks: dict,
    ports: List[Tuple[str, int, str]],
    template_clk: str,
    template_rst: str,
) -> None:
    """Apply clock/reset renaming, polarity, and extra ports to the generated YAML."""
    import yaml as yaml_lib

    text = ip_path.read_text()

    # Rename clock and reset signals everywhere in the file (port names, refs).
    if clocks["clk_name"] != template_clk:
        text = text.replace(template_clk, clocks["clk_name"])
    if clocks["rst_name"] != template_rst:
        text = text.replace(template_rst, clocks["rst_name"])

    # Patch reset polarity.
    polarity_str = "activeLow" if clocks["polarity"] == "active_low" else "activeHigh"
    text = re.sub(r"polarity:\s*\S+", f"polarity: {polarity_str}", text)

    ip_path.write_text(text)

    # Append extra ports via YAML round-trip (preserves existing structure).
    if ports:
        data = yaml_lib.safe_load(ip_path.read_text())
        existing_ports = data.get("ports") or []
        for pname, pwidth, pdirection in ports:
            existing_ports.append({
                "name": pname,
                "logicalName": pname.lstrip("io_"),
                "direction": pdirection,
                "width": pwidth,
                "description": f"{pdirection.title()} port",
            })
        data["ports"] = existing_ports
        ip_path.write_text(
            yaml_lib.dump(data, default_flow_style=False, sort_keys=False)
        )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_init_wizard(args) -> None:
    """Run the interactive IP core wizard (called from cli.py cmd_init)."""
    print()
    print("  ipcraft init — IP Core Wizard")
    print("  Press Ctrl+C at any time to cancel.")

    try:
        # Phase 1
        identity = _phase_identity()
        if identity is None:
            print("\nCancelled.")
            sys.exit(0)

        # Phase 2
        bus_raw = _phase_bus()
        if bus_raw is None:
            print("\nCancelled.")
            sys.exit(0)
        # Resolve sentinel → None (no bus)
        effective_bus = bus_raw if bus_raw != _NO_BUS_SENTINEL else None

        # Phase 3
        clocks = _phase_clocks(bus_raw)
        if clocks is None:
            print("\nCancelled.")
            sys.exit(0)

        # Phase 4
        ports = _phase_ports(identity["name"])
        if ports is None:
            print("\nCancelled.")
            sys.exit(0)

        # Phase 5
        output_opts = _phase_output_options(identity["name"])
        if output_opts is None:
            print("\nCancelled.")
            sys.exit(0)

        # Phase 6
        confirmed = _phase_confirm(
            identity["name"], identity, bus_raw, clocks, ports, output_opts
        )
        if not confirmed:
            print("\nCancelled.")
            sys.exit(0)

        # ----------------------------------------------------------------
        # Execute: scaffold then generate
        # ----------------------------------------------------------------
        print()
        bus_key_for_new = (
            _BUS_NEW_KEY.get(effective_bus, effective_bus) if effective_bus else None
        )

        from ipcraft.generator.yaml.boilerplate import generate_new_ip

        ip_path, mm_path = generate_new_ip(
            name=identity["name"],
            vendor=identity["vendor"],
            library=identity["library"],
            version=identity["version"],
            bus_type=bus_key_for_new,
            output_dir=output_opts["output_dir"],
        )
        print(f"✓ Generated {ip_path}")
        if mm_path:
            print(f"✓ Generated {mm_path}")

        # Patch clock/reset names, polarity, and extra ports.
        effective_defaults = _BUS_CLK_DEFAULTS.get(
            effective_bus, ("clk", "rst_n", "active_low")
        ) if effective_bus else ("clk", "rst_n", "active_low")
        template_clk, template_rst, _ = effective_defaults
        _patch_ip_yaml(ip_path, clocks, ports, template_clk, template_rst)

        # Run the generator by re-using cli._run_generate_core.
        # Build a minimal args namespace that satisfies its interface.
        import types
        from ipcraft.cli import _run_generate_core, _print_file_tree

        gen_args = types.SimpleNamespace(
            input=str(ip_path.resolve()),
            vendor=output_opts["vendor_flag"],
            testbench=output_opts["include_testbench"],
            regs=output_opts["include_regs"],
            dump_context=False,
            update_yaml=True,
            dry_run=False,
            json=False,
            verbose=False,
            progress=False,
            template_dir=None,
        )
        output_base = Path(output_opts["output_dir"]).resolve()

        print()
        written = _run_generate_core(gen_args, output_base)
        print(f"✓ {len(written)} files written to: {output_opts['output_dir']}")
        print()

        # Print ASCII diagram.
        try:
            from ipcraft.parser.yaml.ip_yaml_parser import YamlIpCoreParser as _YP
            from ipcraft.utils.diagram import generate_ascii_diagram
            ip_diag = _YP().parse_file(str(ip_path.resolve()))
            print("IP Core Symbol:")
            print(generate_ascii_diagram(ip_diag))
            print()
        except Exception:
            pass

        # Print generated file tree.
        _print_file_tree(written, output_base)

        print()
        questionary.print("Next steps:", style="bold")
        print(f"  1. Edit {output_opts['output_dir']}/{identity['name']}.mm.yml")
        print(f"       Add your registers, then regenerate.")
        print(f"  2. ipcraft generate {output_opts['output_dir']}/{identity['name']}.ip.yml")
        print(f"       Re-run after every register map change.")
        print(f"  3. cd {output_opts['output_dir']}/tb && make SIM=ghdl")
        print(f"       Run the generated Cocotb simulation.")
        print()

    except KeyboardInterrupt:
        print("\n\nCancelled.")
        sys.exit(0)
