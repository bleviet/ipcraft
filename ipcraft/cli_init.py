"""
ipcraft init — Interactive TUI wizard for scaffolding a new IP core.

Two startup modes:
  fresh    — answer a short sequence of questions to define a new core
  template — pick an existing .ip.yml, preview it, and clone it under a new name

A rich header panel (config summary + live ASCII diagram) is redrawn before
every prompt.  A step-progress bar shows which phase the user is in and what
comes next so there are no surprises.
"""

import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

import questionary
from questionary import Choice, Separator
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
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

# URI substrings (from ipcraft-spec) → internal bus key.
_BUS_URI_MAP = [
    ("axi4_lite", "AXI4_LITE"),
    ("axi4-lite", "AXI4_LITE"),
    ("axi_stream","AXI_STREAM"),
    ("axi-stream","AXI_STREAM"),
    ("axis",      "AXI_STREAM"),
    ("axi4",      "AXI4_FULL"),
    ("avalon_st", "AVALON_ST"),
    ("avalon-st", "AVALON_ST"),
    ("avalon",    "AVALON_MM"),
]

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

# Step-progress phases for each mode.
_FRESH_PHASES    = ["Identity", "Interface", "Ports", "Output", "Confirm"]
_TEMPLATE_PHASES = ["Template", "Rename", "Output", "Confirm"]

# ---------------------------------------------------------------------------
# Context inference
# ---------------------------------------------------------------------------

def _infer_defaults() -> dict:
    """Infer good defaults from git config and current working directory."""
    defaults = {"name": "my_core", "vendor": "user", "library": "ip", "version": "1.0.0"}

    cwd = Path(".").resolve().name.lower().replace("-", "_")
    if re.match(r"^[a-z][a-z0-9_]*$", cwd):
        defaults["name"] = cwd

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
    """Parse compact port syntax: 'name:width:direction, ...'."""
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
    lower = rst_name.lower()
    if lower.endswith("_n") or "resetn" in lower or "aresetn" in lower:
        return "active_low"
    return "active_high"

def _bus_key_from_uri(uri: str) -> Optional[str]:
    """Map an ipcraft-spec bus type URI to an internal bus key."""
    lower = uri.lower()
    for fragment, key in _BUS_URI_MAP:
        if fragment in lower:
            return key
    return None

# ---------------------------------------------------------------------------
# Template discovery & loading
# ---------------------------------------------------------------------------

def _spec_root() -> Optional[Path]:
    """Return the ipcraft-spec root directory via the installed package path."""
    try:
        from ipcraft.utils import BUS_DEFINITIONS_PATH
        if BUS_DEFINITIONS_PATH:
            return Path(BUS_DEFINITIONS_PATH).parent
    except Exception:
        pass
    return None

def _discover_templates() -> List[Tuple[str, Path]]:
    """Discover .ip.yml files from built-in examples and the current project tree.

    Returns a list of (display_label, path) pairs ordered built-ins first.
    """
    templates: List[Tuple[str, Path]] = []

    # Built-in examples (ipcraft-spec/examples/)
    spec = _spec_root()
    if spec:
        examples_dir = spec / "examples"
        for yml in sorted(examples_dir.rglob("*.ip.yml")):
            label = f"[example]  {yml.parent.name} / {yml.stem}"
            templates.append((label, yml))

    # Local .ip.yml files in the current directory tree (up to 3 levels deep).
    cwd = Path(".").resolve()
    for yml in sorted(cwd.rglob("*.ip.yml")):
        if spec and spec in yml.parents:
            continue  # skip files already listed above
        try:
            rel = yml.relative_to(cwd)
        except ValueError:
            rel = yml
        label = f"[local]    {rel}"
        templates.append((label, yml))

    return templates

def _load_template_state(template_path: Path) -> dict:
    """Parse a .ip.yml file and extract wizard state fields from it."""
    import yaml as yaml_lib

    data = yaml_lib.safe_load(template_path.read_text())
    vlnv = data.get("vlnv", {})

    state: dict = {
        "name":    vlnv.get("name",    "my_core"),
        "vendor":  vlnv.get("vendor",  "ipcraft"),
        "library": vlnv.get("library", "examples"),
        "version": vlnv.get("version", "1.0.0"),
        "bus":     None,
        "clk_name": None,
        "rst_name": None,
        "polarity": "active_low",
        "ports":   [],
        "output_dir": None,
        "_template_path": template_path,
        "_template_data": data,
    }

    clocks = data.get("clocks", [])
    if clocks:
        state["clk_name"] = clocks[0].get("name")

    resets = data.get("resets", [])
    if resets:
        state["rst_name"] = resets[0].get("name")
        pol_raw = resets[0].get("polarity", "activeLow")
        state["polarity"] = "active_low" if "Low" in pol_raw or "low" in pol_raw else "active_high"

    bus_interfaces = data.get("busInterfaces", [])
    if bus_interfaces:
        uri = bus_interfaces[0].get("type", "")
        state["bus"] = _bus_key_from_uri(uri) or _NO_BUS_SENTINEL

    for p in data.get("ports", []):
        pname = p.get("name", "")
        pdirection = p.get("direction", "out")
        pwidth = p.get("width", 1)
        # Width may be a parameter reference string — fall back to 1.
        try:
            pwidth = int(pwidth)
        except (TypeError, ValueError):
            pwidth = 1
        state["ports"].append((pname, pwidth, pdirection))

    return state

def _copy_template_files(state: dict) -> Tuple[Path, Optional[Path]]:
    """Write a VLNV-patched copy of the template and its memory map to output_dir."""
    import yaml as yaml_lib

    template_path: Path = state["_template_path"]
    out_dir = Path(state["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    new_name = state["name"]
    ip_out = out_dir / f"{new_name}.ip.yml"

    data = yaml_lib.safe_load(template_path.read_text())
    data["vlnv"] = {
        "vendor":  state["vendor"],
        "library": state["library"],
        "name":    new_name,
        "version": state["version"],
    }

    mm_out: Optional[Path] = None
    mm_data = data.get("memoryMaps")
    if isinstance(mm_data, dict) and "import" in mm_data:
        mm_src = template_path.parent / mm_data["import"]
        if mm_src.exists():
            mm_out = out_dir / f"{new_name}.mm.yml"
            mm_out.write_text(mm_src.read_text())
            data["memoryMaps"] = {"import": f"{new_name}.mm.yml"}

    ip_out.write_text(yaml_lib.dump(data, default_flow_style=False, sort_keys=False))
    return ip_out, mm_out

# ---------------------------------------------------------------------------
# Live panel rendering
# ---------------------------------------------------------------------------

def _build_config_panel(state: dict) -> Panel:
    t = Text()

    def row(label: str, value: str, style: str = "cyan") -> None:
        t.append(f"  {label:<10}", style="dim")
        t.append(f"{value}\n", style=style if value else "dim")
        if not value:
            t.seek(len(t) - 1)  # move back before \n to replace last char
            # simpler: just write "—"
        # rebuild cleanly
    t = Text()

    def row(label: str, value: str, style: str = "cyan") -> None:  # noqa: F811
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

    row("Clock",  state.get("clk_name") or "", style="yellow")

    rst = state.get("rst_name") or ""
    pol = state.get("polarity") or "active_low"
    pol_str = "↓ active-low" if pol == "active_low" else "↑ active-high"
    row("Reset",  f"{rst}  {pol_str}" if rst else "", style="red")

    ports = state.get("ports") or []
    if ports:
        row("Ports", ", ".join(f"{p[0]}:{p[1]}:{p[2]}" for p in ports), style="magenta")
    else:
        row("Ports", "")

    row("Output", state.get("output_dir") or "")

    return Panel(t, title="[bold]Configuration[/bold]", border_style="blue", padding=(0, 1))


def _build_diagram_panel(state: dict) -> Panel:
    return Panel(
        _generate_preview(state),
        title="[bold]IP Core Preview[/bold]",
        border_style="green",
        padding=(0, 1),
    )


def _generate_preview(state: dict) -> str:
    name = state.get("name")
    if not name:
        return "\n  [dim](fill in the core name to see a preview)[/dim]\n"
    try:
        from ipcraft.model import IpCore, VLNV, Port, PortDirection
        from ipcraft.model.base import Polarity
        from ipcraft.model.bus import BusInterface, BusInterfaceMode
        from ipcraft.model.clock_reset import Clock, Reset
        from ipcraft.utils.diagram import generate_ascii_diagram

        clocks, resets, bus_ifaces, ports = [], [], [], []

        if state.get("clk_name"):
            clocks.append(Clock(name=state["clk_name"], description=""))

        if state.get("rst_name"):
            polarity = Polarity.ACTIVE_LOW if state.get("polarity") == "active_low" else Polarity.ACTIVE_HIGH
            resets.append(Reset(name=state["rst_name"], polarity=polarity, description=""))

        bus = state.get("bus")
        if bus and bus != _NO_BUS_SENTINEL:
            bus_ifaces.append(BusInterface(
                name=_BUS_IF_PREVIEW_NAME.get(bus, f"S_{bus}"),
                type=bus, mode=BusInterfaceMode.SLAVE,
                physical_prefix="s_axi_",
                description=f"{_BUS_DISPLAY.get(bus, bus)} interface",
            ))

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
            clocks=clocks, resets=resets, bus_interfaces=bus_ifaces, ports=ports,
        )
        return generate_ascii_diagram(ip)
    except Exception:
        return "\n  [dim](preview not available)[/dim]\n"


def _render_step_bar(state: dict) -> None:
    """Print a visual progress bar showing the current wizard phase."""
    phases = _TEMPLATE_PHASES if state.get("_from_template") else _FRESH_PHASES
    current = state.get("_phase_idx", 0)

    parts = []
    for i, phase in enumerate(phases):
        if i < current:
            parts.append(f"[green]✓ {phase}[/green]")
        elif i == current:
            parts.append(f"[bold cyan underline]● {phase}[/bold cyan underline]")
        else:
            parts.append(f"[dim]○ {phase}[/dim]")

    console.print("  " + "  →  ".join(parts))
    console.print()


def _refresh(state: dict) -> None:
    """Clear screen and redraw the live header (step bar + config + diagram)."""
    console.clear()
    console.rule("[bold cyan]  ipcraft init  —  IP Core Wizard  [/bold cyan]", style="blue")
    console.print()
    _render_step_bar(state)

    if console.width >= 110:
        console.print(Columns(
            [_build_config_panel(state), _build_diagram_panel(state)],
            equal=True, expand=True,
        ))
    else:
        console.print(_build_config_panel(state))
        console.print(_build_diagram_panel(state))

    console.print()


def _ask(state: dict, prompt_fn) -> Optional[object]:
    """Redraw the live header, then run a questionary prompt."""
    _refresh(state)
    return prompt_fn()


def _cancelled() -> None:
    console.print("\n[dim]Cancelled.[/dim]")
    sys.exit(0)

# ---------------------------------------------------------------------------
# Shared post-processing
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
    """Apply clock/reset renaming, polarity fix, and extra ports to a generated YAML."""
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


def _run_generator(ip_path: Path, output_dir: str, vendor_flag: str,
                   include_testbench: bool, include_regs: bool) -> None:
    """Run the ipcraft generator and print the file tree + next steps."""
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
    output_base = Path(output_dir).resolve()

    console.print()
    written = _run_generate_core(gen_args, output_base)
    console.print(f"[green]✓[/green] {len(written)} files written to: {output_dir}")
    console.print()

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


def _print_next_steps(state: dict) -> None:
    out, name = state["output_dir"], state["name"]
    console.print()
    console.rule("[bold green]  Next Steps  [/bold green]", style="green")
    console.print(f"  1. Edit [cyan]{out}/{name}.mm.yml[/cyan]")
    console.print(f"       Add registers, then regenerate.")
    console.print(f"  2. [bold]ipcraft generate {out}/{name}.ip.yml[/bold]")
    console.print(f"       Re-run after every register map change.")
    console.print(f"  3. [bold]cd {out}/tb && make SIM=ghdl[/bold]")
    console.print(f"       Run the generated Cocotb simulation.")
    console.print()


def _ask_output_options(state: dict) -> Tuple[str, bool, bool]:
    """Ask vendor targets and additional outputs. Returns (vendor_flag, testbench, regs)."""
    vendor_choices = _ask(state, lambda: questionary.checkbox(
        "Vendor integration targets:",
        choices=[
            Choice("Intel  — Platform Designer _hw.tcl",                value="intel",  checked=True),
            Choice("Xilinx — IP-XACT component.xml + Vivado xgui .tcl", value="xilinx", checked=True),
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

    gen_choices = _ask(state, lambda: questionary.checkbox(
        "Additional outputs:",
        choices=[
            Choice("Cocotb testbench skeleton  (_test.py + Makefile)", value="testbench", checked=True),
            Choice("Standalone register bank   (_regs.vhd)",           value="regs",      checked=True),
        ],
    ).ask())
    if gen_choices is None:
        _cancelled()

    return vendor_flag, "testbench" in gen_choices, "regs" in gen_choices

# ---------------------------------------------------------------------------
# Template preview
# ---------------------------------------------------------------------------

def _show_template_preview(state: dict, template_path: Path) -> None:
    """Render a syntax-highlighted YAML preview with an 'original preserved' banner."""
    _refresh(state)
    yaml_text = template_path.read_text()
    max_lines = min(console.height - 12, 60) if console.height else 50
    lines = yaml_text.splitlines()
    truncated = len(lines) > max_lines
    preview_text = "\n".join(lines[:max_lines])
    if truncated:
        preview_text += (
            f"\n[dim]  … ({len(lines) - max_lines} more lines"
            " — open the file to see the rest)[/dim]"
        )

    console.print(Panel(
        Syntax(preview_text, "yaml", theme="monokai", line_numbers=True),
        title=f"[bold blue]Template: {template_path.name}[/bold blue]",
        border_style="blue",
        padding=(0, 1),
    ))
    console.print(Panel(
        f"[dim]Source:[/dim]  [cyan]{template_path.resolve()}[/cyan]\n"
        f"[green]✓[/green]  The original file will [bold]not[/bold] be modified"
        " — you are creating a fresh copy.",
        border_style="green",
        padding=(0, 1),
    ))
    console.print()


# ---------------------------------------------------------------------------
# Template flow
# ---------------------------------------------------------------------------

def _run_template_flow(state: dict, pre_selected_path: Optional[Path] = None) -> None:
    """Wizard path: clone and rename an existing .ip.yml.

    If *pre_selected_path* is given the template picker and confirmation prompt
    are skipped — the user has already expressed intent by passing the path.
    """
    state["_from_template"] = True
    state["_phase_idx"] = 0

    if pre_selected_path is not None:
        # ── Template already chosen (CLI arg or welcome-screen direct pick) ──
        template_path = pre_selected_path
        loaded = _load_template_state(template_path)
        state.update(loaded)
        state["_from_template"] = True
        _show_template_preview(state, template_path)
        # No "Use this template?" confirm — intent is already clear.
    else:
        # ── Phase 0: Template selection (full browser) ────────────────────
        templates = _discover_templates()

        template_choices = [Choice(label, value=str(path)) for label, path in templates]
        template_choices.append(Choice("[custom path]  Enter a file path…", value="__custom__"))

        template_val = _ask(state, lambda: questionary.select(
            "Select a template:",
            choices=template_choices,
        ).ask())
        if template_val is None:
            _cancelled()

        if template_val == "__custom__":
            template_val = _ask(state, lambda: questionary.path(
                "Template path (.ip.yml):",
            ).ask())
            if template_val is None:
                _cancelled()

        template_path = Path(template_val)
        if not template_path.exists():
            console.print(f"[red]File not found:[/red] {template_path}")
            _cancelled()

        loaded = _load_template_state(template_path)
        state.update(loaded)
        state["_from_template"] = True
        state["_phase_idx"] = 0

        _show_template_preview(state, template_path)

        ok = questionary.confirm("Use this template as a starting point?", default=True).ask()
        if not ok:
            _cancelled()

    # ── Phase 1: Rename (new name + VLNV) ────────────────────────────────
    state["_phase_idx"] = 1
    ctx_defaults = _infer_defaults()
    # Suggest a name different from the template's own name.
    suggested = (
        ctx_defaults["name"]
        if ctx_defaults["name"] != state["name"]
        else state["name"] + "_copy"
    )

    val = _ask(state, lambda: questionary.text(
        "New core name:",
        default=suggested,
        validate=_valid_identifier,
        instruction="(this will be the name of the cloned IP — the original is unchanged)",
    ).ask())
    if val is None:
        _cancelled()
    state["name"] = val.strip()
    state["output_dir"] = f"./{state['name']}"

    val = _ask(state, lambda: questionary.text(
        "Vendor:", default=state["vendor"],
    ).ask())
    if val is None:
        _cancelled()
    state["vendor"] = val.strip()

    val = _ask(state, lambda: questionary.text(
        "Version:", default=state["version"], validate=_valid_version,
    ).ask())
    if val is None:
        _cancelled()
    state["version"] = val.strip()

    val = _ask(state, lambda: questionary.text(
        "Output directory:", default=state["output_dir"],
    ).ask())
    if val is None:
        _cancelled()
    state["output_dir"] = val.strip()

    # ── Phase 2: Output options ───────────────────────────────────────────
    state["_phase_idx"] = 2
    vendor_flag, include_testbench, include_regs = _ask_output_options(state)

    # ── Phase 3: Confirm ──────────────────────────────────────────────────
    state["_phase_idx"] = 3
    template_display = state["_template_path"]
    new_ip_path = f"{state['output_dir']}/{state['name']}.ip.yml"

    _refresh(state)
    console.print(Panel(
        f"[dim]Template (unchanged):[/dim]  [cyan]{template_display}[/cyan]\n"
        f"[dim]Your copy:[/dim]             [bold]{new_ip_path}[/bold]\n"
        f"[dim]New VLNV:[/dim]              "
        f"[bold]{state['vendor']}/{state['library']}/{state['name']} {state['version']}[/bold]",
        title="[bold yellow]Ready to Generate[/bold yellow]",
        border_style="yellow",
        padding=(1, 2),
    ))
    console.print()

    if not questionary.confirm("Create now?", default=True).ask():
        _cancelled()

    console.print()
    ip_path, mm_path = _copy_template_files(state)
    console.print(f"[green]✓[/green] Created {ip_path}")
    if mm_path:
        console.print(f"[green]✓[/green] Copied  {mm_path}")

    _run_generator(ip_path, state["output_dir"], vendor_flag, include_testbench, include_regs)
    _print_next_steps(state)

# ---------------------------------------------------------------------------
# Fresh flow
# ---------------------------------------------------------------------------

def _run_fresh_flow(state: dict) -> None:
    """Wizard path: define a new IP core from scratch."""
    state["_from_template"] = False

    # ── Phase 0: Identity ────────────────────────────────────────────────
    state["_phase_idx"] = 0

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

    val = _ask(state, lambda: questionary.text(
        "Vendor:", default=state["vendor"],
    ).ask())
    if val is None:
        _cancelled()
    state["vendor"] = val.strip()

    val = _ask(state, lambda: questionary.text(
        "Library:", default=state["library"],
    ).ask())
    if val is None:
        _cancelled()
    state["library"] = val.strip()

    val = _ask(state, lambda: questionary.text(
        "Version:", default=state["version"], validate=_valid_version,
    ).ask())
    if val is None:
        _cancelled()
    state["version"] = val.strip()

    # ── Phase 1: Interface ───────────────────────────────────────────────
    state["_phase_idx"] = 1

    val = _ask(state, lambda: questionary.select(
        "Primary bus interface:", choices=_BUS_OPTIONS,
    ).ask())
    if val is None:
        _cancelled()
    state["bus"] = val

    effective_bus = val if val != _NO_BUS_SENTINEL else None
    default_clk, default_rst, default_pol = (
        _BUS_CLK_DEFAULTS.get(effective_bus, ("clk", "rst_n", "active_low"))
        if effective_bus else ("clk", "rst_n", "active_low")
    )
    state["clk_name"] = default_clk
    state["rst_name"] = default_rst
    state["polarity"] = default_pol

    val = _ask(state, lambda: questionary.text(
        "Clock port name:", default=state["clk_name"],
    ).ask())
    if val is None:
        _cancelled()
    state["clk_name"] = val.strip()

    val = _ask(state, lambda: questionary.text(
        "Reset port name:", default=state["rst_name"],
    ).ask())
    if val is None:
        _cancelled()
    state["rst_name"] = val.strip()
    state["polarity"] = _polarity_from_name(state["rst_name"])

    # ── Phase 2: Ports ───────────────────────────────────────────────────
    state["_phase_idx"] = 2

    suggestion = next(
        (s for kw, s in _PORT_SUGGESTIONS.items() if kw in state["name"].lower()), "",
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

    # ── Phase 3: Output ──────────────────────────────────────────────────
    state["_phase_idx"] = 3
    vendor_flag, include_testbench, include_regs = _ask_output_options(state)

    val = _ask(state, lambda: questionary.text(
        "Output directory:", default=state["output_dir"],
    ).ask())
    if val is None:
        _cancelled()
    state["output_dir"] = val.strip()

    # ── Phase 4: Confirm ─────────────────────────────────────────────────
    state["_phase_idx"] = 4
    effective_bus = state["bus"] if state["bus"] != _NO_BUS_SENTINEL else None
    bus_key_for_new = _BUS_NEW_KEY.get(effective_bus, effective_bus) if effective_bus else None

    cli_new = (
        f"ipcraft new {state['name']}"
        f" --vendor {state['vendor']}"
        f" --library {state['library']}"
        f" --version {state['version']}"
    )
    if bus_key_for_new:
        cli_new += f" --bus {bus_key_for_new}"
    cli_new += f" --output {state['output_dir']}"

    cli_gen = f"ipcraft generate {state['output_dir']}/{state['name']}.ip.yml --vendor {vendor_flag}"
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

    if not questionary.confirm("Generate now?", default=True).ask():
        _cancelled()

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

    _run_generator(ip_path, state["output_dir"], vendor_flag, include_testbench, include_regs)
    _print_next_steps(state)

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_init_wizard(args) -> None:
    """Run the interactive IP core wizard (called from cli.py cmd_init)."""
    state: dict = _infer_defaults()
    state.update({
        "bus": None, "clk_name": None, "rst_name": None,
        "polarity": "active_low", "ports": [], "output_dir": None,
        "_phase_idx": 0, "_from_template": False,
    })

    try:
        console.clear()
        console.rule("[bold cyan]  ipcraft init  —  IP Core Wizard  [/bold cyan]", style="blue")
        console.print()

        # ── Direct template from CLI argument (ipcraft init my_core.ip.yml) ──
        template_arg = getattr(args, "template", None)
        if template_arg:
            template_path = Path(template_arg)
            if not template_path.exists():
                console.print(f"[red]File not found:[/red] {template_path}")
                console.print(
                    "[dim]Tip: run [bold]ipcraft init[/bold] without arguments"
                    " to browse available templates.[/dim]"
                )
                sys.exit(1)
            state["_from_template"] = True
            _run_template_flow(state, pre_selected_path=template_path)
            return

        # ── Auto-discover templates to surface on the welcome screen ──────
        discovered = _discover_templates()

        console.print(
            "  Start from scratch or clone an existing .ip.yml template.\n",
            style="dim",
        )

        if discovered:
            # List templates directly so the user picks in one step.
            choices: list = [
                Choice(
                    "Fresh start  — answer questions to define a brand-new core",
                    value="fresh",
                ),
                Separator("── Clone a template ─────────────────────────────────"),
            ]
            for label, path in discovered[:8]:
                choices.append(Choice(label, value=str(path)))
            if len(discovered) > 8:
                choices.append(Choice(
                    f"[{len(discovered) - 8} more…]  Browse all templates",
                    value="__browse__",
                ))
        else:
            choices = [
                Choice(
                    "Fresh start  — answer questions to define a brand-new core",
                    value="fresh",
                ),
                Choice(
                    "From template — pick an existing .ip.yml, preview it, and clone it",
                    value="__browse__",
                ),
            ]

        selection = questionary.select(
            "How would you like to start?",
            choices=choices,
        ).ask()
        if selection is None:
            _cancelled()

        if selection == "fresh":
            _run_fresh_flow(state)
        elif selection == "__browse__":
            state["_from_template"] = True
            _run_template_flow(state)
        else:
            # User picked a specific template directly from the welcome screen.
            state["_from_template"] = True
            _run_template_flow(state, pre_selected_path=Path(selection))

    except KeyboardInterrupt:
        console.print("\n\n[dim]Cancelled.[/dim]")
        sys.exit(0)
