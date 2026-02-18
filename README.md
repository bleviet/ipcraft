# IPCraft (Python Backend)

Python library and CLI for IP Core specifications (IPCraft).

## Features

- **Hardware Generators**: VHDL/Verilog generation from YAML.
- **Parsers**: VHDL/Verilog parsing to YAML.
- **Bus Library**: Standard bus interface definitions (AXI4-Lite, Avalon-MM).
- **Project Scaffolding**: Create new IP cores from templates.

## Installation

```bash
pip install .
```

## CLI Usage

```bash
# Generate VHDL from IP YAML
ipcraft generate my_core.ip.yml

# Parse VHDL to IP YAML
ipcraft parse rtl/my_entity.vhd

# List available bus definitions
ipcraft list-buses
```

## Development

This project uses `hatch` or `setuptools` build backend.

```bash
# Install in editable mode
pip install -e .

# Run tests
pytest
```
