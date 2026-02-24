# Contributing

Guide for contributors to the IPCraft project.

## Development Setup

```bash
git clone https://github.com/bleviet/ipcraft.git
cd ipcraft
uv sync
```

This installs the package in editable mode with all development dependencies.

## Project Structure

```
ipcraft/
  model/         Data models (Pydantic v2)
  parser/
    yaml/        IP YAML parser
    hdl/         VHDL parser, bus detector
  generator/
    hdl/         VHDL/vendor/testbench generators
    yaml/        VHDL-to-YAML generator
  runtime/       Register/BitField runtime classes
  driver/        Cocotb bus integration, driver loader
  utils/         Shared utilities
  cli.py         CLI entry point
  tests/         Test suite
ipcraft-spec/    Specification package (schemas, templates, bus definitions)
scripts/         Build/generation scripts
docs/            Documentation (MkDocs)
```

## Running Tests

```bash
# All tests
make test

# Verbose output
make test-verbose

# With coverage report
make test-coverage

# Multi-version testing
make tox
```

Tests are in `ipcraft/tests/` and organized by module:

| Directory | Scope |
|-----------|-------|
| `tests/core/` | Integration tests (RW1C, bus I/O) |
| `tests/model/` | Pydantic model tests |
| `tests/parser/` | YAML and VHDL parser tests |
| `tests/generator/hdl/` | VHDL generation and template tests |

## Code Quality

```bash
# Run all checks
make quality

# Individual checks
make lint          # flake8
make format        # black (auto-format)
make format-check  # black (check only, via tox)
make type-check    # mypy
```

## Coding Standards

1. Use idiomatic Python with latest library versions.
2. Keep it simple. No over-engineering, no unnecessary defensive programming.
3. When fixing issues, identify the root cause before applying a fix.
4. Ensure `make quality` passes before committing.

## Architecture Conventions

### Model Layer

- **`StrictModel`** for top-level schema objects (unknown fields are errors)
- **`FlexibleModel`** for memory map objects (supports vendor extensions)
- Field names use `snake_case` in Python, serialized as `camelCase` in YAML

### Parser Layer

- Use mixin classes for separable parsing concerns
- `ParseError` with file path and line context for user-friendly errors
- Support `{import: file}` for external file references

### Generator Layer

- Jinja2 templates in `generator/hdl/templates/`
- Build context dictionaries from the `IpCore` model
- Mixin composition: vendor, testbench, fileset management

### Runtime Layer

- `Register` (sync) and `AsyncRegister` (async) share `_RegisterBase`
- `AbstractBusInterface` (sync) and `AsyncBusInterface` (async) for bus backends
- Read-modify-write with W1C field protection

## Adding a New Bus Type

1. Add the definition to `ipcraft-spec/common/bus_definitions.yml`
2. Add port-level definitions with required/optional status
3. Add prefix suggestions to `SUGGESTED_PREFIXES` in `bus_library.py`
4. Add aliases to `_BUS_TYPE_ALIASES` in `utils/__init__.py`
5. Test bus detection with a sample VHDL entity

## Adding a New Generator Target

1. Create a Jinja2 template in `generator/hdl/templates/`
2. Add a generation method in the appropriate mixin or generator class
3. Wire it into `generate_all()` with appropriate flags
4. Add tests in `tests/generator/hdl/`

## Documentation

Documentation uses MkDocs with Material theme. Source files are in `docs/`.

```bash
# Install MkDocs dependencies
pip install mkdocs mkdocs-material pymdown-extensions

# Serve locally
mkdocs serve

# Build static site
mkdocs build
```

## Version Control

- Do not commit generated/temporary files used for debugging.
- Do not push changes automatically -- verify locally first.
