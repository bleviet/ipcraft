# VHDL Generator Test Suite

This directory contains comprehensive tests for the `IpCoreProjectGenerator` that ensure it produces correct, syntactically valid VHDL code.

## Test Files

### `test_vhdl_generator.py`
Unit tests for individual generator methods:
- **TestIpCoreProjectGeneratorBasic**: Core functionality tests (15 tests)
  - Initialization, package, top, core, bus wrappers
  - Generation of all files, register file inclusion
- **TestIpCoreProjectGeneratorWithRegisters**: Tests with memory maps and registers
  - Simple register generation
  - User-defined ports
- **TestIpCoreProjectGeneratorVendorFiles**: Vendor integration file tests
  - Intel Platform Designer `_hw.tcl`
  - Xilinx Vivado `component.xml`
- **TestIpCoreProjectGeneratorTestbench**: Testbench generation tests
  - cocotb test file
  - Makefile generation
  - All testbench files

### `test_template_coverage.py`
Template rendering coverage tests:
- **TestTemplateRendering**: Individual template tests (23 tests)
  - Verify all 13 Jinja2 templates render without errors
  - Test templates with various IP core configurations
  - Check for template artifacts (unrendered Jinja2 syntax)
  - Validate VHDL syntax (entity/package presence, proper ending)
- **TestTemplateEdgeCases**: Edge case tests (4 tests)
  - Empty memory maps
  - Single-bit register fields
  - Wide (32-bit) register fields
  - Many ports (20+ ports)

### `test_vhdl_generator_e2e.py`
End-to-end tests using actual example YAML files:
- **TestIpCoreProjectGeneratorE2E**: Full pipeline tests
  - Parse minimal/basic/timer YAML examples
  - Generate complete VHDL outputs
  - Verify testbench and vendor file generation
- **TestIpCoreProjectGeneratorSyntaxValidation**: GHDL syntax checks (marked `@pytest.mark.slow`)
  - Validate generated VHDL with GHDL `--std=08`
  - Requires GHDL installed (skipped if not available)

### `test_vhdl_generator_structured.py`
Structured output tests:
- **TestIpCoreProjectGeneratorStructured**: Tests for structured directory output
  - RTL, testbench, and vendor file organization
  - Forward/backward compatibility

## Running Tests

### Run all generator tests:
```bash
uv run pytest ipcraft/tests/generator/hdl/ -v
```

### Run only unit tests:
```bash
uv run pytest ipcraft/tests/generator/hdl/test_vhdl_generator.py -v
```

### Run only end-to-end tests:
```bash
uv run pytest ipcraft/tests/generator/hdl/test_vhdl_generator_e2e.py -v
```

### Run only template coverage tests:
```bash
uv run pytest ipcraft/tests/generator/hdl/test_template_coverage.py -v
```

### Run syntax validation tests (requires GHDL):
```bash
uv run pytest ipcraft/tests/generator/hdl/test_vhdl_generator_e2e.py::TestIpCoreProjectGeneratorSyntaxValidation -v
```

### Skip slow tests:
```bash
uv run pytest ipcraft/tests/generator/hdl/ -v -m "not slow"
```

## Test Coverage

Current coverage:
- ✅ Template coverage tests passing (test_template_coverage.py)
- ✅ Unit tests passing (test_vhdl_generator.py)
- ✅ E2E tests passing (test_vhdl_generator_e2e.py)
- ✅ Structured output tests passing (test_vhdl_generator_structured.py)

### What's Tested

**Generation Methods:**
- `generate_package()` - VHDL package with register types
- `generate_top()` - Top-level entity with bus interface
- `generate_core()` - Bus-agnostic core logic
- `generate_bus_wrapper()` - AXI-Lite and Avalon-MM wrappers
- `generate_register_file()` - Standalone register file
- `generate_all()` - Complete file set

**Vendor Integration:**
- `generate_intel_hw_tcl()` - Intel Platform Designer TCL
- `generate_xilinx_component_xml()` - Xilinx IP-XACT XML
- `generate_vendor_files()` - Batch vendor file generation

**Testbench:**
- `generate_cocotb_test()` - cocotb Python test
- `generate_cocotb_makefile()` - GHDL Makefile
- `generate_memmap_yaml()` - Driver memory map
- `generate_testbench()` - Complete testbench set

**GHDL Syntax Validation:**
- Generated VHDL compiles with GHDL `--std=08`
- Proper compilation order: package → submodules → top-level

**Template Rendering:**
- All 13 Jinja2 templates render without errors
- Edge cases: empty memory maps, single-bit fields, wide registers, many ports
- No template artifacts in generated code

### What's NOT Tested (Yet)

- ❌ **Functional Verification**: Running generated cocotb tests in simulation
- ❌ **Register Access Correctness**: Verifying register read/write behavior in simulation

## Adding New Tests

### Unit Test Pattern

```python
def test_new_feature(self):
    """Test description."""
    ip_core = IpCore(
        api_version="test/v1.0",
        vlnv=VLNV(vendor="test", library="lib", name="test_ip", version="1.0"),
        # ... add required fields
    )

    generator = IpCoreProjectGenerator()
    result = generator.generate_something(ip_core)

    assert result is not None
    assert "expected content" in result
```

### E2E Test Pattern

```python
def test_new_yaml_example(self, example_dir, parser, generator):
    """Test with new example."""
    yaml_file = example_dir / "path" / "to" / "example.ip.yml"

    if not yaml_file.exists():
        pytest.skip(f"Example file not found: {yaml_file}")

    ip_core = parser.parse_file(str(yaml_file))
    files = generator.generate_all(ip_core, bus_type='axil')

    # Verify expected outputs
    assert len(files) >= 4
    # ... additional assertions
```

## Dependencies

- **pytest**: Test framework
- **pydantic**: Data validation
- **jinja2**: Template engine
- **pyyaml**: YAML parsing
- **GHDL** (optional): For syntax validation tests

## Known Issues

1. **Timer example test**: `my_timer_core.ip.yml` references missing `common/c_api.fileset.yml`
2. **GHDL tests skipped**: Syntax validation requires GHDL installation

## Future Work

1. **Add GHDL CI check**: Run syntax validation in CI if GHDL available
2. **Simulation tests**: Run generated cocotb testbenches with GHDL
3. **Functional tests**: Verify register behavior in simulation
