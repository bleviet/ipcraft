# IP Core Library Tests

This directory contains the test suite for the ipcraft components.

## Test Structure

```
ipcraft/tests/
├── core/
│   └── test_register_rw1c.py      # RW1C access type tests
├── model/
│   └── test_pydantic_models.py    # Pydantic model validation
├── generator/
│   └── hdl/
│       ├── test_vhdl_generator.py          # Unit tests
│       ├── test_vhdl_generator_e2e.py      # End-to-end tests
│       ├── test_vhdl_generator_structured.py # Structured output tests
│       └── test_template_coverage.py       # Template rendering tests
├── parser/
│   ├── test_yaml_parser.py        # YAML IP core parser tests
│   └── hdl/
│       ├── test_vhdl_parser.py              # VHDL parser tests
│       ├── test_vhdl_parser_comprehensive.py # Comprehensive parser tests
│       └── test_hdl_roundtrip.py            # Parse-generate roundtrip
└── test_vhdl_ai_parser.py         # AI-powered VHDL parser tests
```

## Running Tests

### All Tests

```bash
uv run pytest ipcraft/tests/ -v
```

### By Component

```bash
# Core register tests
uv run pytest ipcraft/tests/core/ -v

# Model validation tests
uv run pytest ipcraft/tests/model/ -v

# Generator tests
uv run pytest ipcraft/tests/generator/hdl/ -v

# Parser tests
uv run pytest ipcraft/tests/parser/ -v
```

## Test Coverage

The tests cover:

1. **RW1C Access Type**:
   - Single bit clearing
   - Multi-bit field partial clearing
   - Write-0-no-effect behavior
   - Mixed access types in same register

2. **Pydantic Models**:
   - Model construction and validation
   - Computed properties
   - Serialization/deserialization

3. **VHDL Generation**:
   - Template rendering for all 13 Jinja2 templates
   - End-to-end generation from YAML examples
   - Vendor integration files (Intel, Xilinx)
   - Testbench generation (cocotb, Makefile)
   - GHDL syntax validation (when available)

4. **YAML Parsing**:
   - IP core YAML parsing
   - Memory map inline and imported definitions
   - Auto-offset and auto-bit-offset calculation

5. **VHDL Parsing**:
   - Entity extraction
   - Port and generic parsing
   - Parse-generate roundtrip

## Adding New Tests

When adding new test files:

1. Place tests in the subdirectory matching the source structure
2. Use descriptive test names following the pattern `test_{component}_{feature}.py`
3. Use `uv run pytest` to execute tests
