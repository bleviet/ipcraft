"""
AI-Powered VHDL Parser using LLM and Pydantic models.

This parser uses LLM (Large Language Model) to parse VHDL code directly,
leveraging AI's understanding of code structure, naming conventions, and context.

Architecture:
    LLM Parsing: AI extracts entity, ports, generics, and bus interfaces
    Validation: Pydantic models ensure data correctness

Benefits:
    - Handles complex expressions and edge cases naturally
    - Infers bus interfaces from naming and comments
    - Robust to formatting variations
    - No grammar maintenance needed
"""

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ValidationError

# Import Pydantic models
from ipcraft.model.base import VLNV, Parameter
from ipcraft.model.bus import BusInterface
from ipcraft.model.core import IpCore
from ipcraft.model.port import Port, PortDirection

# Set up logging
logger = logging.getLogger(__name__)


# ============================================================================
# Configuration Models
# ============================================================================


class ParserConfig(BaseModel):
    """Configuration for AI-powered VHDL parser."""

    llm_provider: str = Field(default="ollama", description="LLM provider (ollama, openai, gemini)")
    llm_model: str = Field(default="gemma3:12b", description="LLM model name")

    # Default VLNV components
    default_vendor: str = Field(default="unknown.vendor", description="Default vendor")
    default_library: str = Field(default="work", description="Default library")
    default_version: str = Field(default="1.0.0", description="Default version")
    default_api_version: str = Field(default="fpga-lib/v1.0", description="Schema version")

    # Parser behavior
    strict_mode: bool = Field(
        default=False, description="Fail on parsing errors (vs graceful degradation)"
    )
    max_retries: int = Field(default=2, description="Max retries if LLM response is invalid")

    model_config = {"extra": "forbid"}


# ============================================================================
# LLM-Based VHDL Parser
# ============================================================================


class VhdlLlmParser:
    """
    LLM-based VHDL parser using AI to understand code structure.

    This replaces pyparsing with LLM intelligence for more robust parsing.
    """

    def __init__(self, provider_name: str = "ollama", model_name: str = "gemma3:12b"):
        """
        Initialize LLM parser.

        Args:
            provider_name: Provider type (ollama, openai, gemini)
            model_name: Model identifier
        """
        self.provider = None
        self.provider_name = provider_name
        self.model_name = model_name

        # Lazy loading: only import and initialize if needed
        self._initialize_provider()

    def _initialize_provider(self):
        """Initialize LLM provider (lazy loading)."""
        try:
            # Try to import llm_core providers
            import sys

            llm_core_path = Path(__file__).parents[4] / "llm-playground" / "llm_core"

            if llm_core_path.exists():
                sys.path.insert(0, str(llm_core_path))

            # Import directly from module files
            from llm_core.providers.gemini import GeminiProvider
            from llm_core.providers.ollama import OllamaProvider
            from llm_core.providers.openai import OpenAIProvider
            from llm_core.providers.strategies.openai_api_strategy import OpenAIAPIStrategy

            # Initialize provider based on config
            if self.provider_name.lower() == "ollama":
                self.provider = OllamaProvider(model_name=self.model_name)
            elif self.provider_name.lower() == "openai":
                self.provider = OpenAIProvider(model_name=self.model_name)
            elif self.provider_name.lower() == "gemini":
                self.provider = GeminiProvider(
                    strategy=OpenAIAPIStrategy(), model_name=self.model_name
                )
            else:
                logger.warning(f"Unknown provider: {self.provider_name}, LLM disabled")

        except ImportError as e:
            logger.warning(f"Could not import llm_core: {e}. LLM features disabled.")
            logger.info("To enable LLM: ensure llm_core is in PYTHONPATH or installed")
            self.provider = None

    def is_available(self) -> bool:
        """Check if LLM provider is available."""
        if self.provider is None:
            return False

        # Check if Ollama (local) or has API key
        if self.provider_name.lower() == "ollama":
            return True

        return self.provider.api_key is not None

    def parse_vhdl_entity(self, vhdl_text: str) -> Dict[str, Any]:
        """
        Parse VHDL entity using LLM to extract all information.

        Args:
            vhdl_text: VHDL source code

        Returns:
            Dict with entity structure including ports, generics, bus interfaces, description
        """
        if not self.is_available():
            raise RuntimeError("LLM provider not available. Cannot parse VHDL without LLM.")

        system_prompt = """You are an expert VHDL parser. Parse the provided VHDL code and extract structured information.

Return ONLY valid JSON (no markdown, no explanation) with this structure:
{
    "entity_name": "string",
    "description": "brief 1-2 sentence description",
    "generics": [
    {
            "name": "string",
            "type": "string (e.g., integer, std_logic_vector)",
            "default": "string or null"
    }
    ],
    "ports": [
    {
            "name": "string",
            "direction": "in|out|inout",
            "type": "string (e.g., std_logic, std_logic_vector)",
            "width": number (1 for std_logic, N for vectors),
            "range": "string (e.g., '7 downto 0') or null"
    }
    ],
    "bus_interfaces": [
    {
            "name": "string (e.g., s_axi)",
            "type": "string (e.g., AXI4_LITE, AXI_STREAM, AVALON_MM)",
            "mode": "master|slave|source|sink",
            "physical_prefix": "string (e.g., s_axi_)",
            "signals": ["list of signal names in this interface"]
    }
    ]
}

Common bus interface types and their signals:
- AXI4_LITE: awaddr, awvalid, awready, wdata, wstrb, wvalid, wready, bresp, bvalid, bready, araddr, arvalid, arready, rdata, rresp, rvalid, rready
- AXI4_FULL: Same as AXI4_LITE plus awid, awlen, awsize, awburst, awlock, awcache, awprot, awqos, bid, arid, arlen, arsize, arburst, arlock, arcache, arprot, arqos, rid, rlast
- AXI_STREAM: tdata, tvalid, tready, tlast, tkeep, tstrb, tuser, tid, tdest
- AVALON_MM: address, writedata, readdata, write, read, waitrequest, byteenable, readdatavalid
- WISHBONE: adr, dat_i, dat_o, we, cyc, stb, ack, err, rty, sel
- SPI: sclk/sck/clk, mosi/sdo/dout, miso/sdi/din, cs/cs_n/ss/ss_n (chip select can be active high or low)
- I2C: scl/sclk (clock), sda (data), may have separate sda_i/sda_o/sda_t (tristate control)
- UART: tx/txd/uart_tx (transmit), rx/rxd/uart_rx (receive), may have rts/cts (flow control)
- JTAG: tck (clock), tms (mode select), tdi (data in), tdo (data out), trst_n (reset, optional)
- APB: paddr, psel, penable, pwrite, pwdata, prdata, pready, pslverr

For width calculation:
- std_logic = 1
- std_logic_vector(7 downto 0) = 8
- std_logic_vector(N-1 downto 0) = N
- Handle arithmetic expressions like (C_WIDTH-1 downto 0), (C_WIDTH/8)-1 downto 0)

Identify bus interfaces by:
1. Signal naming prefixes (s_axi_, m_axis_, avmm_, wb_, apb_)
2. Comments mentioning bus types (AXI, SPI, I2C, UART, Wishbone, Avalon)
3. Standard signal patterns matching common interfaces
4. Naming conventions (spi_sclk, i2c_scl, uart_tx indicate specific bus types)

Bus interface naming guidelines:
- Group related signals with common prefixes or suffixes
- SPI: Look for sclk/sck + mosi/miso + cs combinations
- I2C: Look for scl + sda pairs (may be bidirectional with _i/_o/_t suffixes)
- UART: Look for tx/rx pairs (may include rts/cts for flow control)
- Master vs Slave: Masters typically drive clock/control, slaves respond
- Direction: Master initiates transfers, slave responds"""

        user_prompt = f"""Parse this VHDL entity and return structured JSON:

```vhdl
{vhdl_text}
```

Return complete JSON with all fields filled:"""

        try:
            client = self.provider.get_client()
            response = self.provider.summarize(client, user_prompt, system_prompt, "")

            # Clean response
            response_clean = response.strip()

            # Extract JSON from markdown code blocks if present
            if "```" in response_clean:
                json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response_clean, re.DOTALL)
                if json_match:
                    response_clean = json_match.group(1)
                else:
                    # Try to find JSON object directly
                    json_match = re.search(r"(\{.*\})", response_clean, re.DOTALL)
                    if json_match:
                        response_clean = json_match.group(1)

            # Parse JSON
            parsed_data = json.loads(response_clean)

            logger.info(
                f"LLM successfully parsed entity: {parsed_data.get('entity_name', 'unknown')}"
            )
            logger.info(
                f"  Ports: {len(parsed_data.get('ports', []))}, "
                f"Generics: {len(parsed_data.get('generics', []))}, "
                f"Bus Interfaces: {len(parsed_data.get('bus_interfaces', []))}"
            )

            return parsed_data

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM JSON response: {e}")
            logger.debug(f"Response was: {response[:500]}")
            raise ValueError(f"LLM returned invalid JSON: {e}")
        except Exception as e:
            logger.error(f"VHDL parsing failed: {e}")
            raise


# ============================================================================
# Main AI-Enhanced Parser
# ============================================================================


class VHDLAiParser:
    """
    AI-Powered VHDL Parser using LLM and Pydantic models.

    Uses LLM to parse VHDL code directly, providing robust handling of
    complex expressions, edge cases, and automatic bus interface detection.
    """

    def __init__(self, config: Optional[ParserConfig] = None):
        """
        Initialize parser with configuration.

        Args:
            config: Parser configuration (uses defaults if None)
        """
        self.config = config or ParserConfig()

        # Initialize LLM parser
        self.llm_parser = VhdlLlmParser(
            provider_name=self.config.llm_provider, model_name=self.config.llm_model
        )

        if self.llm_parser.is_available():
            logger.info(
                f"LLM parser initialized: {self.config.llm_provider}/{self.config.llm_model}"
            )
        else:
            error_msg = "LLM provider not available. This parser requires an LLM to function."
            if self.config.strict_mode:
                raise RuntimeError(error_msg)
            logger.error(error_msg)

    def parse_file(self, file_path: Path) -> IpCore:
        """
        Parse VHDL file and return IpCore model.

        Args:
            file_path: Path to VHDL file

        Returns:
            Validated IpCore model
        """
        vhdl_text = file_path.read_text()
        return self.parse_text(vhdl_text, source_name=file_path.name)

    def parse_text(self, vhdl_text: str, source_name: str = "unknown") -> IpCore:
        """
        Parse VHDL text and return IpCore model using LLM.

        Args:
            vhdl_text: VHDL source code
            source_name: Source identifier (filename)

        Returns:
            Validated IpCore model
        """
        if not self.llm_parser.is_available():
            if self.config.strict_mode:
                raise RuntimeError("LLM not available, cannot parse VHDL")
            # Return minimal entity
            return self._create_minimal_ipcore(source_name)

        # Parse with LLM (with retries)
        parsed_data = None
        last_error = None

        for attempt in range(self.config.max_retries + 1):
            try:
                logger.info(
                    f"Parsing VHDL with LLM (attempt {attempt + 1}/{self.config.max_retries + 1})..."
                )
                parsed_data = self.llm_parser.parse_vhdl_entity(vhdl_text)
                break  # Success!
            except Exception as e:
                last_error = e
                logger.warning(f"Parse attempt {attempt + 1} failed: {e}")
                if attempt < self.config.max_retries:
                    logger.info("Retrying...")

        if parsed_data is None:
            if self.config.strict_mode:
                raise ValueError(f"Failed to parse entity from {source_name}: {last_error}")
            logger.error(f"All parse attempts failed: {last_error}")
            return self._create_minimal_ipcore(source_name)

        # Build canonical IpCore model from LLM response
        return self._build_ip_core_from_llm(parsed_data, source_name)

    def _create_minimal_ipcore(self, source_name: str) -> IpCore:
        """Create minimal valid IpCore when parsing fails."""
        vlnv = VLNV(
            vendor=self.config.default_vendor,
            library=self.config.default_library,
            name=source_name.replace(".vhd", "").replace(".vhdl", ""),
            version=self.config.default_version,
        )
        return IpCore(
            api_version=self.config.default_api_version,
            vlnv=vlnv,
            description=f"Failed to parse: {source_name}",
        )

    def _build_ip_core_from_llm(self, parsed_data: Dict[str, Any], source_name: str) -> IpCore:
        """
        Build validated IpCore model from LLM-parsed data.

        Args:
            parsed_data: Dict from LLM with entity structure
            source_name: Source file name

        Returns:
            Validated IpCore model
        """
        # Create VLNV
        entity_name = parsed_data.get("entity_name", source_name.replace(".vhd", ""))
        vlnv = VLNV(
            vendor=self.config.default_vendor,
            library=self.config.default_library,
            name=entity_name,
            version=self.config.default_version,
        )

        description = parsed_data.get("description", entity_name)

        # Convert ports to Port models
        ports = []
        for port_data in parsed_data.get("ports", []):
            try:
                # Map direction
                direction_str = port_data.get("direction", "in").lower()
                direction = PortDirection.from_string(direction_str)

                # Get width
                width = port_data.get("width", 1)
                if isinstance(width, str):
                    # Try to parse width string
                    try:
                        width = int(width)
                    except ValueError:
                        width = 1

                # Create Port model
                port = Port(
                    name=port_data["name"],
                    direction=direction,
                    width=width,
                    description="",
                )
                ports.append(port)
            except (KeyError, ValidationError) as e:
                logger.warning(f"Skipping invalid port {port_data.get('name')}: {e}")

        # Convert generics to Parameters
        parameters = []
        for generic_data in parsed_data.get("generics", []):
            try:
                param = Parameter(
                    name=generic_data["name"],
                    value=generic_data.get("default", "") or "",
                    data_type=generic_data.get("type", "integer"),
                    description="",
                )
                parameters.append(param)
            except (KeyError, ValidationError) as e:
                logger.warning(f"Skipping invalid generic {generic_data.get('name')}: {e}")

        # Convert bus interfaces to BusInterface models
        bus_interface_models = []
        for bus_data in parsed_data.get("bus_interfaces", []):
            try:
                bus_if = BusInterface(
                    name=bus_data.get("name", "unknown"),
                    type=bus_data.get("type", "UNKNOWN"),
                    mode=bus_data.get("mode", "slave"),
                    physical_prefix=bus_data.get("physical_prefix", ""),
                    description="",
                )
                bus_interface_models.append(bus_if)
            except (KeyError, ValidationError) as e:
                logger.warning(f"Skipping invalid bus interface: {e}")

        # Build IpCore
        try:
            ip_core = IpCore(
                api_version=self.config.default_api_version,
                vlnv=vlnv,
                description=description,
                ports=ports,
                parameters=parameters,
                bus_interfaces=bus_interface_models,
            )

            logger.info(f"Successfully built IP core: {vlnv.full_name}")
            logger.info(
                f"  Ports: {len(ports)}, Generics: {len(parameters)}, Bus Interfaces: {len(bus_interface_models)}"
            )

            return ip_core

        except ValidationError as e:
            logger.error(f"IpCore validation failed: {e}")
            if self.config.strict_mode:
                raise

            # Return minimal valid core
            return IpCore(
                api_version=self.config.default_api_version, vlnv=vlnv, description=description
            )
