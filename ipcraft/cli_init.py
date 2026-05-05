"""
ipcraft init — Interactive TUI wizard for scaffolding a new IP core.

A questionary + rich wizard that clears and redraws a live panel (config summary
+ ASCII diagram) before every prompt, giving a single-screen form feel with
real-time feedback as values are filled in.
"""

import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

import questionary
from questionary import Choice
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

console = Console()

# ---------------------------------------------------------------------------
# Bus options & lookup tables
# ---------------------------------------------------------------------------

_NO_BUS_SENTINEL = "__NONE__"

_BUS_OPTIONS = [
    Choice("AXI4-Lite   — Control/status register slave  (most common)", value="AXI4_LITE"),
    Choice("AXI4-Full   — High-bandwidth burst slave  (DMA engines)",    value="AXI4_FULL"),
    Choice("AXI-Stream  — Streaming data path  (DSP, video pipelines)",  value="AXI_STREAM"),
    Choice("Avalon-MM   — Intel/Quartus register slave",                  value="AVALON_MM"),
    Choice("Avalon-ST   — Intel/Quartus streaming path",                  value="AVALON_ST"),
    Choice("None        — No bus interface  (standalone / custom)",       value=_NO_BUS_SENTINEL),
]

_BUS_DISPLAY = {
    "AXI4_LITE":  "AXI4-Lite",
    "AXI4_FULL":  "AXI4-Full",
    "AXI_STREAM": "AXI-Stream",
    "AVALON_MM":  "Avalon-MM",
    "AVALON_ST":  "Avalon-ST",
}

_BUS_CLK_DEFAULTS = {
    "AXI4_LITE":  ("s_axi_aclk",  "s_axi_aresetn", "active_low"),
    "AXI4_FULL":  ("s_axi_aclk",  "s_axi_aresetn", "active_low"),
    "AXI_STREAM": ("s_axis_aclk", "s_axis_aresetn","active_low"),
    "AVALON_MM":  ("clk",         "reset",         "active_high"),
    "AVALON_ST":  ("clk",         "reset",         "active_high"),
}

_BUS_NEW_KEY = {
    "AXI4_LITE":  "AXI4L",
    "AXI4_FULL":  "AXI4",
    "AXI_STREAM": "AXIS",
    "AVALON_MM":  "AVALON_MM",
    "AVALON_ST":  "AVALON_ST",
}

# Human-readable interface names used in the diagram preview.
_BUS_IF_PREVIEW_NAME = {
    "AXI4_LITE":  "S_AXI_LITE",
    "AXI4_FULL":  "S_AXI",
    "AXI_STREAM": "S_AXIS",
    "AVALON_MM":  "AVS",
    "AVALON_ST":  "AVS_ST",
}

# Smart port defaults keyed by keywords found in the core name.
_PORT_SUGGESTIONS = {
    "pwm":   "o_pwm:1:out",
    "uart":  "o_tx:1:out, i_rx:1:in",
    "spi":   "o_sclk:1:out, o_mosi:1:out, i_miso:1:in, o_cs_n:1:out",
    "gpio":  "io_gpio:8:inout",
    "irq":   "o_irq:1:out",
    "timer": "o_irq:1:out",
    "dma":   "o_irq:1:out",
}

# Email domains that carry no useful vendor information.
_PUBLIC_DOMAINS = {
    "gmail", "yahoo", "outlook", "hotmail", "icloud",
    "proton", "protonmail", "live", "msn", "me",
}

# ---------------------------------------------------------------------------
# Context inference
# ---------------------------------------------------------------------------

def _infer_defaults() -> dict:
    """Infer good defaults from git config and current working directory."""
    defaults = {"name": "my_core", "vendor": "user", "library": "ip", "version": "1.0.0"}

    # Core name: use the current directory name if it is a valid VHDL identifier.
    cwd = Path(".").resolve().name.lower().replace("-", "_")
    if re.match(r"^[a-z][a-z0-9_]*$", cwd):
        defaults["name"] = cwd

    # Vendor: extract a meaningful organisation from the git user's email domain.
    try:
        email = subprocess.run(
            ["git", "config", "user.email"],
            capture_output=True, text=True, timeout=2,
        ).stdout.strip()
        if "@" in email:
            domain = email.split("@")[-1].split(".")[0].lower()
            if domain not in _PUBLIC_DOMAINS:
                defaults["vendor"] = domain
    except Exception:
        pass

    return defaults

# ---------------------------------------------------------------------------
# Validators & port parsing
# ---------------------------------------------------------------------------

def _valid_identifier(value: str):
    if re.match(r"^[a-z][a-z0-9_]*$", value.strip()):
        return True
    return "Use lowercase letters, digits, and underscores (must start with a letter)"

def _valid_version(value: str):
    if re.match(r"^\d+\.\d+(\.\d+)?$", value.strip()):
        return True
    return "Use semver format: 1.0.0 or 1.0"

def _parse_ports(text: str) -> Tuple[List[Tuple[str, int, str]], Optional[str]]:
    """Parse compact port syntax: 'name:width:direction, ...'.

    Returns (ports, error_message).  error_message is None on success.
    """
    if not text.strip():
        return [], None
    ports = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        pieces = [p.strip() for p in part.split(":")]
        if len(pieces) != 3:
            return [], f"Bad syntax '{part}' — use name:width:direction"
        pname, pwidth_str, pdirection = pieces
        if not re.match(r"^[a-zA-Z][a-zA-Z0-9_]*$", pname):
            return [], f"Invalid port name '{pname}'"
        try:
            pwidth = int(pwidth_str)
            if pwidth < 1:
                raise ValueError
        except ValueError:
            return [], f"Width must be a positive integer, got '{pwidth_str}'"
        if pdirection not in ("in", "out", "inout"):
            return [], f"Direction must be in/out/inout, got '{pdirection}'"
        ports.append((pname, pwidth, pdirection))
    return ports, None

def _valid_ports(value: str):
    _, err = _parse_ports(value)
    return True if err is None else err

def _polarity_from_name(rst_name: str) -> str:
    """Infer reset polarity from port name conventions."""
    lower = rst_name.lower()
    if lower.endswith("_n") or "resetn" in lower or "aresetn" in lower:
        return "active_low"
    return "active_high"

# ---------------------------------------------------------------------------
# Live panel rendering
# ---------------------------------------------------------------------------

def _build_config_panel(state: dict) -> Panel:
    """Render the left configuration summary panel."""
    t = Text()

    def row(label: str, value: str, style: str = "cyan") -> None:
        t.append(f"  {label:<10}", style="dim")
        if value:
            t.append(f"{value}\n", style=style)
        else:
            t.append("—\n", style="dim")

    row("Name",    state.get("name") or "")
    row("Vendor",  state.get("vendor") or "")
    row("Library", state.get("library") or "")
    row("Version", state.get("version") or "")

    bus = state.get("bus")
    if bus and bus != _NO_BUS_SENTINEL:
        row("Bus", _BUS_DISPLAY.get(bus, bus), style="green")
    elif bus == _NO_BUS_SENTINEL:
        row("Bus", "None", style="dim")
    else:
        row("Bus", "")

    row("Clock",   state.get("clk_name") or "", style="yellow")

    rst = state.get("rst_name") or ""
    pol = state.get("polarity") or "active_low"
    pol_str = "↓ active-low" if pol == "active_low" else "↑ active-high"
    row("Reset",   f"{rst}  {pol_str}" if rst else "", style="red")

    ports = state.get("ports") or []
    if ports:
        port_str = ", ".join(f"{p[0]}:{p[1]}:{p[2]}" for p in ports)
        row("Ports", port_str, style="magenta")
    else:
        row("Ports", "")

    row("Output",  state.get("output_dir") or "")

    return Panel(t, title="[bold]Configuration[/bold]", border_style="blue", padding=(0, 1))


def _build_diagram_panel(state: dict) -> Panel:
    """Render the right IP core preview panel."""
    content = _generate_preview(state)
    return Panel(content, title="[bold]IP Core Preview[/bold]", border_style="green", padding=(0, 1))


def _generate_preview(state: dict) -> str:
    """Build an ASCII diagram from the current wizard state using the model layer."""
    name = state.get("name")
    if not name:
        return "\n  [dim](fill in the core name to see a preview)[/dim]\n"

    try:
        from ipcraft.model import IpCore, VLNV, Port, PortDirection
        from ipcraft.model.base import Polarity
        from ipcraft.model.bus import BusInterface, BusInterfaceMode
        from ipcraft.model.clock_reset import Clock, Reset
        from ipcraft.utils.diagram import generate_ascii_diagram

        clocks = []
        if state.get("clk_name"):
            clocks.append(Clock(name=state["clk_name"], description=""))

        resets = []
        if state.get("rst_name"):
            polarity = (
                Polarity.ACTIVE_LOW
                if state.get("polarity") == "active_low"
                else Polarity.ACTIVE_HIGH
            )
            resets.append(Reset(name=state["rst_name"], polarity=polarity, description=""))

        bus_interfaces = []
        bus = state.get("bus")
        if bus and bus != _NO_BUS_SENTINEL:
            bus_interfaces.append(BusInterface(
                name=_BUS_IF_PREVIEW_NAME.get(bus, f"S_{bus}"),
                type=bus,
                mode=BusInterfaceMode.SLAVE,
                physical_prefix="s_axi_",
                description=f"{_BUS_DISPLAY.get(bus, bus)} interface",
            ))

        ports = []
        for pname, pwidth, pdirection in (state.get("ports") or []):
            ports.append(Port(
                name=pname,
                direction=PortDirection.from_string(pdirection),
                width=pwidth,
                type="std_logic" if pwidth == 1 else f"std_logic_vector({pwidth - 1} downto 0)",
                description="",
            ))

        ip = IpCore(
            vlnv=VLNV(vendor="preview", library="ip", name=name, version="1.0.0"),
            clocks=clocks,
            resets=resets,
            bus_interfaces=bus_interfaces,
            ports=ports,
        )
        return generate_ascii_diagram(ip)

    except Exception:
        return "\n  [dim](preview not available)[/dim]\n"


def _refresh(state: dict) -> None:
    """Clear screen and redraw the live header with config + diagram panels."""
    console.clear()
    console.rule("[bold cyan]  ipcraft init  —  IP Core Wizard  [/bold cyan]", style="blue")
    console.print()

    config_panel = _build_config_panel(state)
    diagram_panel = _build_diagram_panel(state)

    if console.width >= 110:
        console.print(Columns([config_panel, diagram_panel], equal=True, expand=True))
    else:
        # Narrow terminal: stack vertically
        console.print(config_panel)
        console.print(diagram_panel)

    console.print()


def _ask(state: dict, prompt_fn) -> Optional[object]:
    """Redraw the live header then run a questionary prompt."""
    _refresh(state)
    return prompt_fn()


def _cancelled() -> None:
    console.print("\n[dim]Cancelled.[/dim]")
    sys.exit(0)


# ---------------------------------------------------------------------------
# Post-processing: patch generated .ip.yml
# ---------------------------------------------------------------------------

def _patch_ip_yaml(
    ip_path: Path,
    clk_name: str,
    rst_name: str,
    polarity: str,
    ports: List[Tuple[str, int, str]],
    template_clk: str,
    template_rst: str,
) -> None:
    """Apply clock/reset renaming, polarity, and extra ports to the generated YAML."""
    import yaml as yaml_lib

    text = ip_path.read_text()
    if clk_name != template_clk:
        text = text.replace(template_clk, clk_name)
    if rst_name != template_rst:
        text = text.replace(template_rst, rst_name)

    polarity_str = "activeLow" if polarity == "active_low" else "activeHigh"
    text = re.sub(r"polarity:\s*\S+", f"polarity: {polarity_str}", text)
    ip_path.write_text(text)

    if ports:
        data = yaml_lib.safe_load(ip_path.read_text())
        existing = data.get("ports") or []
        for pname, pwidth, pdirection in ports:
            existing.append({
                "name": pname,
                "logicalName": re.sub(r"^[io]o?_", "", pname),
                "direction": pdirection,
                "width": pwidth,
                "description": f"{pdirection.title()} port",
            })
        data["ports"] = existing
        ip_path.write_text(yaml_lib.dump(data, default_flow_style=False, sort_keys=False))


# ---------------------------------------------------------------------------
# Wizard entry point
# ---------------------------------------------------------------------------

def run_init_wizard(args) -> None:
    """Run the interactive IP core wizard (called from cli.py cmd_init)."""
    state: dict = _infer_defaults()
    state.update({
        "bus": None,
        "clk_name": None,
        "rst_name": None,
        "polarity": "active_low",
        "ports": [],
        "output_dir": None,
    })

    try:
        # ── Core name ────────────────────────────────────────────────────
        val = _ask(state, lambda: questionary.text(
            "Core name:",
            default=state["name"],
            validate=_valid_identifier,
            instruction="(lowercase, underscores only)",
        ).ask())
        if val is None:
            _cancelled()
        state["name"] = val.strip()
        state["output_dir"] = f"./{state['name']}"

        # ── Vendor ───────────────────────────────────────────────────────
        val = _ask(state, lambda: questionary.text(
            "Vendor:", default=state["vendor"],
        ).ask())
        if val is None:
            _cancelled()
        state["vendor"] = val.strip()

        # ── Library ──────────────────────────────────────────────────────
        val = _ask(state, lambda: questionary.text(
            "Library:", default=state["library"],
        ).ask())
        if val is None:
            _cancelled()
        state["library"] = val.strip()

        # ── Version ──────────────────────────────────────────────────────
        val = _ask(state, lambda: questionary.text(
            "Version:", default=state["version"], validate=_valid_version,
        ).ask())
        if val is None:
            _cancelled()
        state["version"] = val.strip()

        # ── Bus type ─────────────────────────────────────────────────────
        val = _ask(state, lambda: questionary.select(
            "Primary bus interface:", choices=_BUS_OPTIONS,
        ).ask())
        if val is None:
            _cancelled()
        state["bus"] = val

        # Pre-fill clock/reset defaults from the selected bus type.
        effective_bus = val if val != _NO_BUS_SENTINEL else None
        default_clk, default_rst, default_pol = (
            _BUS_CLK_DEFAULTS.get(effective_bus, ("clk", "rst_n", "active_low"))
            if effective_bus else ("clk", "rst_n", "active_low")
        )
        state["clk_name"] = default_clk
        state["rst_name"] = default_rst
        state["polarity"] = default_pol

        # ── Clock port ───────────────────────────────────────────────────
        val = _ask(state, lambda: questionary.text(
            "Clock port name:", default=state["clk_name"],
        ).ask())
        if val is None:
            _cancelled()
        state["clk_name"] = val.strip()

        # ── Reset port ───────────────────────────────────────────────────
        val = _ask(state, lambda: questionary.text(
            "Reset port name:", default=state["rst_name"],
        ).ask())
        if val is None:
            _cancelled()
        state["rst_name"] = val.strip()
        # Infer polarity from the port name suffix rather than asking the user.
        state["polarity"] = _polarity_from_name(state["rst_name"])

        # ── Extra ports ──────────────────────────────────────────────────
        suggestion = next(
            (s for kw, s in _PORT_SUGGESTIONS.items() if kw in state["name"].lower()),
            "",
        )
        val = _ask(state, lambda: questionary.text(
            "Extra ports:",
            default=suggestion,
            validate=_valid_ports,
            instruction="name:width:dir, ...  e.g. o_pwm:1:out, i_data:8:in  (blank = none)",
        ).ask())
        if val is None:
            _cancelled()
        state["ports"], _ = _parse_ports(val)

        # ── Vendor integration targets ───────────────────────────────────
        vendor_choices = _ask(state, lambda: questionary.checkbox(
            "Vendor integration targets:",
            choices=[
                Choice("Intel  — Platform Designer _hw.tcl",                  value="intel",  checked=True),
                Choice("Xilinx — IP-XACT component.xml + Vivado xgui .tcl",   value="xilinx", checked=True),
            ],
        ).ask())
        if vendor_choices is None:
            _cancelled()
        if {"intel", "xilinx"} <= set(vendor_choices):
            vendor_flag = "both"
        elif "intel" in vendor_choices:
            vendor_flag = "intel"
        elif "xilinx" in vendor_choices:
            vendor_flag = "xilinx"
        else:
            vendor_flag = "none"

        # ── Additional code generation ───────────────────────────────────
        gen_choices = _ask(state, lambda: questionary.checkbox(
            "Additional outputs:",
            choices=[
                Choice("Cocotb testbench skeleton  (_test.py + Makefile)", value="testbench", checked=True),
                Choice("Standalone register bank   (_regs.vhd)",           value="regs",      checked=True),
            ],
        ).ask())
        if gen_choices is None:
            _cancelled()
        include_testbench = "testbench" in gen_choices
        include_regs      = "regs"      in gen_choices

        # ── Output directory ─────────────────────────────────────────────
        val = _ask(state, lambda: questionary.text(
            "Output directory:", default=state["output_dir"],
        ).ask())
        if val is None:
            _cancelled()
        state["output_dir"] = val.strip()

        # ── Confirm ──────────────────────────────────────────────────────
        effective_bus    = state["bus"] if state["bus"] != _NO_BUS_SENTINEL else None
        bus_key_for_new  = _BUS_NEW_KEY.get(effective_bus, effective_bus) if effective_bus else None

        cli_new = (
            f"ipcraft new {state['name']}"
            f" --vendor {state['vendor']}"
            f" --library {state['library']}"
            f" --version {state['version']}"
        )
        if bus_key_for_new:
            cli_new += f" --bus {bus_key_for_new}"
        cli_new += f" --output {state['output_dir']}"

        cli_gen = f"ipcraft generate {state['output_dir']}/{state['name']}.ip.yml"
        cli_gen += f" --vendor {vendor_flag}"
        if not include_testbench:
            cli_gen += " --no-testbench"
        if not include_regs:
            cli_gen += " --no-regs"

        _refresh(state)
        console.print(Panel(
            f"[dim]Equivalent CLI command (copy for CI / scripts):[/dim]\n\n"
            f"  [bold]{cli_new}[/bold] \\\n"
            f"    [bold]&& {cli_gen}[/bold]",
            title="[bold yellow]Ready to Generate[/bold yellow]",
            border_style="yellow",
            padding=(1, 2),
        ))
        console.print()

        confirmed = questionary.confirm("Generate now?", default=True).ask()
        if not confirmed:
            _cancelled()

        # ── Execute: scaffold → patch → generate ─────────────────────────
        console.print()
        from ipcraft.generator.yaml.boilerplate import generate_new_ip

        ip_path, mm_path = generate_new_ip(
            name=state["name"],
            vendor=state["vendor"],
            library=state["library"],
            version=state["version"],
            bus_type=bus_key_for_new,
            output_dir=state["output_dir"],
        )
        console.print(f"[green]✓[/green] Generated {ip_path}")
        if mm_path:
            console.print(f"[green]✓[/green] Generated {mm_path}")

        # Determine template defaults for substitution.
        template_clk, template_rst, _ = (
            _BUS_CLK_DEFAULTS.get(effective_bus, ("clk", "rst_n", "active_low"))
            if effective_bus else ("clk", "rst_n", "active_low")
        )
        _patch_ip_yaml(
            ip_path,
            clk_name=state["clk_name"],
            rst_name=state["rst_name"],
            polarity=state["polarity"],
            ports=state["ports"],
            template_clk=template_clk,
            template_rst=template_rst,
        )

        import types
        from ipcraft.cli import _run_generate_core, _print_file_tree

        gen_args = types.SimpleNamespace(
            input=str(ip_path.resolve()),
            vendor=vendor_flag,
            testbench=include_testbench,
            regs=include_regs,
            dump_context=False,
            update_yaml=True,
            dry_run=False,
            json=False,
            verbose=False,
            progress=False,
            template_dir=None,
        )
        output_base = Path(state["output_dir"]).resolve()

        console.print()
        written = _run_generate_core(gen_args, output_base)
        console.print(f"[green]✓[/green] {len(written)} files written to: {state['output_dir']}")
        console.print()

        # Final diagram from the fully-patched YAML.
        try:
            from ipcraft.parser.yaml.ip_yaml_parser import YamlIpCoreParser as _YP
            from ipcraft.utils.diagram import generate_ascii_diagram
            ip_diag = _YP().parse_file(str(ip_path.resolve()))
            console.print(Panel(
                generate_ascii_diagram(ip_diag),
                title="[bold green]Generated IP Core[/bold green]",
                border_style="green",
            ))
        except Exception:
            pass

        _print_file_tree(written, output_base)

        console.print()
        console.rule("[bold green]  Next Steps  [/bold green]", style="green")
        out = state["output_dir"]
        name = state["name"]
        console.print(f"  1. Edit [cyan]{out}/{name}.mm.yml[/cyan]")
        console.print(f"       Add registers, then regenerate.")
        console.print(f"  2. [bold]ipcraft generate {out}/{name}.ip.yml[/bold]")
        console.print(f"       Re-run after every register map change.")
        console.print(f"  3. [bold]cd {out}/tb && make SIM=ghdl[/bold]")
        console.print(f"       Run the generated Cocotb simulation.")
        console.print()

    except KeyboardInterrupt:
        console.print("\n\n[dim]Cancelled.[/dim]")
        sys.exit(0)
