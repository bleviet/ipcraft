import shutil
import re
from pathlib import Path
from typing import Optional, Tuple
from ipcraft.utils import BUS_DEFINITIONS_PATH


def generate_new_ip(
    name: str,
    vendor: str = "example.com",
    library: str = "examples",
    version: str = "1.0.0",
    bus_type: Optional[str] = None,
    output_dir: str = ".",
) -> Tuple[Path, Optional[Path]]:
    """
    Generates boilerplate IP and MM YAML files based on templates.
    Returns a tuple of (ip_yaml_path, mm_yaml_path).
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    ip_filename = f"{name}.ip.yml"
    mm_filename = f"{name}.mm.yml"

    ip_out_path = out_dir / ip_filename
    mm_out_path = out_dir / mm_filename

    # Locate templates in ipcraft-spec
    # Based on BUS_DEFINITIONS_PATH which is in common/bus_definitions.yml
    if BUS_DEFINITIONS_PATH is None:
        raise FileNotFoundError("Could not find ipcraft-spec bus_definitions.yml path")

    spec_dir = Path(BUS_DEFINITIONS_PATH).parent.parent
    templates_dir = spec_dir / "templates"

    # Select template based on bus_type
    if bus_type and bus_type.upper() in ["AXI4L", "AXIL", "AXI4-LITE"]:
        ip_template = templates_dir / "axi_slave.ip.yml"
        mm_template = templates_dir / "axi_slave.mm.yml"
    else:
        ip_template = templates_dir / "basic.ip.yml"
        mm_template = templates_dir / "basic.mm.yml"

    if not ip_template.exists():
        raise FileNotFoundError(f"Template not found: {ip_template}")

    # Read templates
    ip_content = ip_template.read_text()

    # Replace VLNV fields in IP YAML, limiting to the first occurrence (which is inside vlnv:)
    ip_content = re.sub(r"vendor:\s*.*", f"vendor: {vendor}", ip_content, count=1)
    ip_content = re.sub(r"library:\s*.*", f"library: {library}", ip_content, count=1)
    ip_content = re.sub(r"name:\s*.*", f"name: {name}", ip_content, count=1)
    ip_content = re.sub(r"version:\s*.*", f"version: {version}", ip_content, count=1)

    # Remove relative useBusLibrary to use the system default
    ip_content = re.sub(r"useBusLibrary:\s*.*\n", "", ip_content)

    # Update memory map import if it exists
    if "import:" in ip_content and ".mm.yml" in ip_content:
        ip_content = re.sub(
            r"import:\s*.*\.mm\.yml", f"import: {mm_filename}", ip_content
        )
    # If no memory map is in the IP template, but we are generating one, add the import
    elif "memoryMaps:" not in ip_content:
        ip_content += f"\nmemoryMaps:\n  import: {mm_filename}\n"

    ip_out_path.write_text(ip_content)

    if mm_template.exists():
        mm_content = mm_template.read_text()
        mm_out_path.write_text(mm_content)
        return ip_out_path, mm_out_path

    return ip_out_path, None
