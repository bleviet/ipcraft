# AI VHDL Parser - Usage Guide

## Quick Start

The VHDL parser uses a **Pure LLM** approach to parse VHDL files, automatically handling complex expressions and detecting bus interfaces.

### Prerequisites

1.  **Install dependencies**:
    ```bash
    uv sync
    ```

2.  **Install Ollama** (Recommended for local privacy):
    ```bash
    curl -fsSL https://ollama.com/install.sh | sh
    ollama serve
    ollama pull llama3.3:latest
    ```

---

## Command Line Usage

Use the demo script to parse VHDL files directly:

```bash
# Parse using default local Ollama model
uv run examples/ai_parser_demo.py examples/test_vhdl/axi_example_peripheral.vhd

# Parse using a specific provider (e.g., openai)
# Requires OPENAI_API_KEY in .env
uv run examples/ai_parser_demo.py myfile.vhd --provider openai

# Parse using a custom model
uv run examples/ai_parser_demo.py myfile.vhd --model gemma:7b
```

**Expected Output:**
The script will output a JSON representation of the IP Core, including:
*   Entity Name & Description
*   Generics (Parameters)
*   Ports (with resolved widths)
*   **Detected Bus Interfaces** (e.g., AXI4L, AXIS)

---

## Python API Usage

### Basic Parsing

```python
from ipcraft.parser.hdl.vhdl_ai_parser import VHDLAiParser, ParserConfig

# 1. Configure the parser
config = ParserConfig(
    llm_provider="ollama",  # "ollama", "openai", "gemini"
    llm_model="llama3.3:latest",
    max_retries=2
)

# 2. Initialize
parser = VHDLAiParser(config=config)

# 3. Parse a file
ip_core = parser.parse_file("design.vhd")

# 4. Access parsed data (Pydantic models)
print(f"Entity: {ip_core.vlnv.name}")

for port in ip_core.ports:
    print(f"  {port.name}: {port.direction} [{port.width}]")

# 5. Access automatically detected bus interfaces
for bus in ip_core.bus_interfaces:
    print(f"  Bus: {bus.name} ({bus.type} {bus.mode})")
```

### JSON Export

The parsed `IpCore` object is a Pydantic model, making export easy:

```python
# Export to JSON string
json_data = ip_core.model_dump_json(indent=2)
print(json_data)

# Export to Python dict
dict_data = ip_core.model_dump()
```

---

## Testing

Run the comprehensive test suite to verify the parser.

### Run All Parsing Tests
```bash
uv run pytest ipcraft/tests/test_vhdl_ai_parser.py -v
```

### Run Specific Categories

```bash
# Complex expressions (e.g., (WIDTH/8)-1)
uv run pytest ipcraft/tests/test_vhdl_ai_parser.py::TestComplexExpressions -v

# Bus Interface Detection
uv run pytest ipcraft/tests/test_vhdl_ai_parser.py::TestBusInterfaceDetection -v
```

### Integration Tests (Live LLM)
Tests marked as `integration` will call the actual LLM provider.
```bash
uv run pytest ipcraft/tests/test_vhdl_ai_parser.py -v -m integration
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `Connection refused` (Ollama) | Ensure `ollama serve` is running in another terminal. |
| `Model not found` | Run `ollama pull <model_name>` to download the model first. |
| `pydantic.ValidationError` | The LLM returned malformed JSON. Try increasing `max_retries` in `ParserConfig`. |
| Import Errors | Ensure you are running with `uv run` to load the virtual environment. |
