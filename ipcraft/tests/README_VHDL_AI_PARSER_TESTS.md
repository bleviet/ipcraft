# Test Configuration

This directory contains tests for the VHDL AI Parser.

## Test Categories

### Unit Tests (`test_vhdl_ai_parser.py`)
- **Basic Entity Parsing**: Entity name, description generation
- **Port Parsing**: Direction, width, type extraction
- **Generic Parsing**: Parameter extraction with defaults
- **Complex Expressions**: Arithmetic, division, power-of-2
- **Bus Interface Detection**: AXI, SPI, Wishbone, AXI-Stream
- **Error Handling**: Graceful degradation, strict mode
- **Model Validation**: Pydantic validation, serialization

### Performance Tests
- Marked with `@pytest.mark.slow`
- Benchmark parsing time for simple and complex entities
- Require `pytest-benchmark` plugin

### Integration Tests
- Marked with `@pytest.mark.integration`
- Test with real LLM providers (Ollama, OpenAI, Gemini)
- Require API keys for cloud providers

## Running Tests

### Run All Tests
```bash
cd ipcraft
pytest ipcraft/tests/test_vhdl_ai_parser.py -v
```

### Run Specific Test Class
```bash
# Basic parsing tests only
pytest ipcraft/tests/test_vhdl_ai_parser.py::TestBasicEntityParsing -v

# Bus interface detection tests
pytest ipcraft/tests/test_vhdl_ai_parser.py::TestBusInterfaceDetection -v

# Port parsing tests
pytest ipcraft/tests/test_vhdl_ai_parser.py::TestPortParsing -v
```

### Run Specific Test
```bash
pytest ipcraft/tests/test_vhdl_ai_parser.py::TestBasicEntityParsing::test_simple_counter_parsing -v
```

### Skip Slow Tests
```bash
pytest ipcraft/tests/test_vhdl_ai_parser.py -v -m "not slow"
```

### Skip Integration Tests
```bash
pytest ipcraft/tests/test_vhdl_ai_parser.py -v -m "not integration"
```

### Run Only Integration Tests
```bash
# Requires Ollama running or API keys set
pytest ipcraft/tests/test_vhdl_ai_parser.py -v -m integration
```

### Run with Coverage
```bash
pytest ipcraft/tests/test_vhdl_ai_parser.py --cov=ipcraft.parser.hdl --cov-report=html
```

### Run Performance Benchmarks
```bash
# Requires pytest-benchmark
pip install pytest-benchmark
pytest ipcraft/tests/test_vhdl_ai_parser.py -v -m slow --benchmark-only
```

## Test Requirements

### Basic Tests
- Python 3.11+
- `pytest`
- `ipcraft` package installed
- Ollama running locally (default provider)
- Test VHDL files in `examples/test_vhdl/`

### Performance Tests
- `pytest-benchmark`

### Integration Tests
- **Ollama**: Ollama server running on `localhost:11434`
- **OpenAI**: `OPENAI_API_KEY` environment variable
- **Gemini**: `GEMINI_API_KEY` environment variable

## Test Data

Tests use VHDL files from `examples/test_vhdl/`:
- `simple_counter.vhd` - Basic entity
- `uart_transmitter.vhd` - Multiple generics
- `fifo_buffer.vhd` - Power-of-2 expressions
- `spi_master.vhd` - SPI bus interface
- `axi_stream_filter.vhd` - AXI-Stream interfaces
- `pwm_generator.vhd` - Multi-channel
- `wishbone_slave.vhd` - Wishbone bus
- `axi_example_peripheral.vhd` - AXI4-Lite bus

## Expected Test Results

All tests should pass with Ollama as the default provider:
```
========================== test session starts ==========================
collected 30 items

test_vhdl_ai_parser.py::TestBasicEntityParsing::test_simple_counter_parsing PASSED
test_vhdl_ai_parser.py::TestBasicEntityParsing::test_entity_name_extraction PASSED
test_vhdl_ai_parser.py::TestBasicEntityParsing::test_description_generation PASSED
test_vhdl_ai_parser.py::TestPortParsing::test_simple_counter_ports PASSED
test_vhdl_ai_parser.py::TestPortParsing::test_port_directions PASSED
test_vhdl_ai_parser.py::TestPortParsing::test_port_widths PASSED
test_vhdl_ai_parser.py::TestPortParsing::test_uart_transmitter_ports PASSED
test_vhdl_ai_parser.py::TestGenericParsing::test_simple_counter_generic PASSED
test_vhdl_ai_parser.py::TestGenericParsing::test_uart_transmitter_generics PASSED
test_vhdl_ai_parser.py::TestGenericParsing::test_fifo_buffer_generics PASSED
test_vhdl_ai_parser.py::TestComplexExpressions::test_simple_subtraction PASSED
test_vhdl_ai_parser.py::TestComplexExpressions::test_power_of_two PASSED
test_vhdl_ai_parser.py::TestComplexExpressions::test_division_expression PASSED
test_vhdl_ai_parser.py::TestComplexExpressions::test_axi_division_expression PASSED
test_vhdl_ai_parser.py::TestBusInterfaceDetection::test_axi4_lite_detection PASSED
test_vhdl_ai_parser.py::TestBusInterfaceDetection::test_axi_stream_detection PASSED
test_vhdl_ai_parser.py::TestBusInterfaceDetection::test_spi_detection PASSED
test_vhdl_ai_parser.py::TestBusInterfaceDetection::test_wishbone_detection PASSED
test_vhdl_ai_parser.py::TestBusInterfaceDetection::test_no_bus_interface PASSED
test_vhdl_ai_parser.py::TestErrorHandling::test_nonexistent_file PASSED
test_vhdl_ai_parser.py::TestErrorHandling::test_strict_mode_on_failure PASSED
test_vhdl_ai_parser.py::TestErrorHandling::test_graceful_degradation_on_failure PASSED
test_vhdl_ai_parser.py::TestModelValidation::test_valid_ip_core_model PASSED
test_vhdl_ai_parser.py::TestModelValidation::test_vlnv_structure PASSED
test_vhdl_ai_parser.py::TestModelValidation::test_port_model_validation PASSED

========================== 25 passed in 45.23s ==========================
```

## Troubleshooting

### "Ollama not available"
- Start Ollama: `ollama serve`
- Pull model: `ollama pull gemma3:12b`
- Check server: `curl http://localhost:11434/api/tags`

### "API key not configured"
- Set environment variable:
  ```bash
  export OPENAI_API_KEY=your-key-here
  export GEMINI_API_KEY=your-key-here
  ```
- Or create `.env` file in project root

### "Test VHDL files not found"
- Ensure test files exist in `examples/test_vhdl/`
- Run from project root directory

### Slow test execution
- LLM calls take 20-40 seconds each
- Run with `-m "not slow"` to skip performance tests
- Use faster model: `llama3.2:latest` instead of `gemma3:12b`

## Adding New Tests

### Test Template
```python
def test_new_feature(self, parser, test_vhdl_dir):
    """Test description."""
    ip_core = parser.parse_file(test_vhdl_dir / "your_file.vhd")
    
    # Assertions
    assert ip_core.vlnv.name == "expected_name"
    assert len(ip_core.ports) == expected_count
```

### Test Markers
```python
@pytest.mark.slow          # Performance tests
@pytest.mark.integration   # Integration with real APIs
@pytest.mark.skipif(...)   # Conditional skip
```

## CI/CD Integration

### GitHub Actions Example
```yaml
- name: Run VHDL Parser Tests
  run: |
    pytest ipcraft/tests/test_vhdl_ai_parser.py -v -m "not integration"
```

### Skip Integration Tests in CI
```yaml
- name: Run Tests (Skip Integration)
  run: |
    pytest ipcraft/tests/test_vhdl_ai_parser.py -v \
      -m "not integration and not slow"
```
