# Installation

## Requirements

- Python 3.8 or later
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

## Install with uv (recommended)

From the repository root:

```bash
uv sync
```

This installs `ipcraft` and its companion package `ipcraft-spec` (schemas,
templates, bus definitions) in editable mode.

## Install with pip

```bash
pip install -e .
```

## Dependencies

| Package | Purpose |
|---------|---------|
| `pydantic` | Data model validation |
| `jinja2` | HDL template rendering |
| `pyyaml` | YAML parsing and generation |
| `click` | CLI framework |
| `rich` | Terminal formatting |
| `pyparsing` | VHDL grammar parsing |
| `ipcraft-spec` | Schemas, templates, bus definitions |

## Optional Dependencies (Simulation)

For cocotb-based simulation and testbench execution:

```bash
pip install cocotb cocotbext-axi
```

## Development Setup

```bash
# Clone the repository
git clone https://github.com/bleviet/ipcraft.git
cd ipcraft

# Install with dev dependencies
uv sync

# Verify installation
uv run ipcraft --help
```

## Verify Installation

```bash
# Check CLI is accessible
ipcraft --help

# List available bus types
ipcraft list-buses
```
