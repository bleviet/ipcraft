"""
Verilog Parser module using pyparsing to parse Verilog module declarations.
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from pyparsing import (
    CaselessKeyword,
    CaselessLiteral,
    CharsNotIn,
    Forward,
    Group,
    Keyword,
    LineEnd,
    Literal,
    ParseBaseException,
)
from pyparsing import Optional as Opt
from pyparsing import (
    ParserElement,
    QuotedString,
    SkipTo,
    StringEnd,
    Suppress,
    White,
    Word,
    ZeroOrMore,
    alphanums,
    alphas,
    cppStyleComment,
    delimitedList,
    nums,
    oneOf,
    pythonStyleComment,
)

from ipcraft.model import VLNV, IpCore, Port, PortDirection

logger = logging.getLogger(__name__)

# Enable packrat parsing for better performance
ParserElement.set_default_whitespace_chars(" \t\n\r")
ParserElement.enable_packrat()


class VerilogParser:
    """Parser for Verilog files to extract module declarations."""

    def __init__(self):
        """Initialize the Verilog parser with grammar definitions."""
        # Verilog keywords
        self.keywords = {
            "module": CaselessKeyword("module"),
            "endmodule": CaselessKeyword("endmodule"),
            "input": CaselessKeyword("input"),
            "output": CaselessKeyword("output"),
            "inout": CaselessKeyword("inout"),
            "wire": CaselessKeyword("wire"),
            "reg": CaselessKeyword("reg"),
        }

        # Basic building blocks
        self.identifier = Word(alphas + "_", alphanums + "_$")

        # Comments
        self.line_comment = "//" + SkipTo(LineEnd())
        self.block_comment = "/*" + SkipTo("*/") + "*/"

        # Number definitions for vector ranges
        self.number = Word(nums)
        self.vector_range = (
            Suppress("[") + self.number + Suppress(":") + self.number + Suppress("]")
        )

        # Port types and directions
        self.direction = oneOf("input output inout", caseless=True)
        self.data_type = Opt(oneOf("wire reg logic", caseless=True))

        # Verilog port declaration with range
        self.port_decl_with_range = Group(
            self.direction
            + Opt(self.vector_range).set_results_name("range")
            + self.data_type
            + self.identifier.set_results_name("name")
            + Opt(Suppress(CaselessLiteral(",")) | Suppress(CaselessLiteral(";")))
        ).set_results_name("port_decl")

        # Verilog port declaration without range
        self.port_decl_no_range = Group(
            self.direction
            + self.data_type
            + self.identifier.set_results_name("name")
            + Opt(Suppress(CaselessLiteral(",")) | Suppress(CaselessLiteral(";")))
        ).set_results_name("port_decl")

        self.port_decl = self.port_decl_with_range | self.port_decl_no_range

        # Port list - just names for the module declaration
        self.port_list_simple = Group(
            Suppress("(") + delimitedList(self.identifier) + Suppress(")")
        ).set_results_name("port_list")

        # Full port definitions
        self.full_port_list = Group(
            Suppress("(") + ZeroOrMore(self.port_decl) + Suppress(")")
        ).set_results_name("full_port_list")

        # Module declaration (ansi-style with inline port declarations)
        self.module_ansi_decl = (
            self.keywords["module"]
            + self.identifier.set_results_name("module_name")
            + self.full_port_list
            + Suppress(";")
            + SkipTo(self.keywords["endmodule"])
            + self.keywords["endmodule"]
        ).set_results_name("module_ansi_decl")

        # Module declaration (older non-ansi style with port list followed by port definitions)
        self.module_non_ansi_decl = (
            self.keywords["module"]
            + self.identifier.set_results_name("module_name")
            + self.port_list_simple
            + Suppress(";")
            + ZeroOrMore(self.port_decl)
            + SkipTo(self.keywords["endmodule"])
            + self.keywords["endmodule"]
        ).set_results_name("module_non_ansi_decl")

        # Combined module declaration (try ansi-style first, then non-ansi)
        self.module_decl = self.module_ansi_decl | self.module_non_ansi_decl

    def parse_file(self, file_path: str) -> Dict[str, Any]:
        """
        Parse a Verilog file and extract module information.

        Args:
            file_path: Path to the Verilog file

        Returns:
            Dictionary containing parsed module information
        """
        with open(file_path, "r") as f:
            content = f.read()
        return self.parse_text(content)

    def parse_text(self, verilog_text: str) -> Dict[str, Any]:
        """
        Parse Verilog text and extract module information.

        Args:
            verilog_text: Verilog code to parse

        Returns:
            Dictionary containing parsed module information
        """
        result = {"module": None}

        # Check if "module" keyword exists in text
        if "module" not in verilog_text.lower():
            logger.warning("No 'module' keyword found in Verilog text")
            return result

        # Try regex approach first (more flexible with different formatting)
        try:
            # Extract module name - handle modules with special /* AUTOARG */ comment
            # This pattern is more robust for modules with special comments
            module_pattern = r"module\s+(\w+)\s*\((.*?)\);"
            module_match = re.search(module_pattern, verilog_text, re.IGNORECASE | re.DOTALL)

            if module_match:
                module_name = module_match.group(1)
                ports_text = module_match.group(2)

                logger.debug("Regex found module: %s", module_name)
                logger.debug("Ports text: %s", ports_text)

                ports = []

                # Parse ANSI-style port declarations with a more flexible regex pattern
                # This handles: input/output/inout, with optional reg/wire/logic, optional bit range, and name
                ansi_port_pattern = (
                    r"(input|output|inout)\s+(reg|wire|logic)?\s*(?:\[(\d+)\s*:\s*(\d+)\])?\s*(\w+)"
                )
                ansi_ports = re.findall(ansi_port_pattern, ports_text, re.IGNORECASE)

                if ansi_ports:
                    logger.debug("Found %d ANSI-style ports", len(ansi_ports))
                    # Process ANSI-style ports
                    for port_match in ansi_ports:
                        direction_str = port_match[0].lower()
                        port_type = port_match[1].lower() if port_match[1] else None
                        msb_str = port_match[2]
                        lsb_str = port_match[3]
                        port_name = port_match[4]

                        # Parse MSB and LSB if present
                        msb = int(msb_str) if msb_str else None
                        lsb = int(lsb_str) if lsb_str else None

                        logger.debug(
                            "Found port: %s, direction: %s, type: %s, range: %s:%s",
                            port_name,
                            direction_str,
                            port_type,
                            msb,
                            lsb,
                        )

                        # Create port
                        port = self._create_port(port_name, direction_str, msb, lsb)
                        ports.append(port)
                else:
                    # Non-ANSI style parsing logic here...
                    # Simplified regex based port finding for non-ANSI
                    port_names = [p.strip() for p in re.split(r",\s*", ports_text) if p.strip()]

                    # Look for port declarations in module body
                    decl_pattern = r"(input|output|inout)(?:\s+(?:reg|wire|logic))?(?:\s*\[(\d+)\s*:\s*(\d+)\])?(?:\s+(\w+))"
                    port_decls = re.findall(decl_pattern, verilog_text, re.IGNORECASE)

                    port_dict = {}
                    for decl in port_decls:
                        d_str = decl[0].lower()
                        msb = int(decl[1]) if decl[1] else None
                        lsb = int(decl[2]) if decl[2] else None
                        p_name = decl[3]
                        port_dict[p_name] = (d_str, msb, lsb)

                    for p_name in port_names:
                        if p_name in port_dict:
                            d_str, msb, lsb = port_dict[p_name]
                            ports.append(self._create_port(p_name, d_str, msb, lsb))
                        else:
                            # Default to input/std_logic if unknown
                            ports.append(self._create_port(p_name, "input", None, None))

                # Create VLNV and IpCore
                vlnv = VLNV(vendor="parsed", library="verilog", name=module_name, version="1.0")
                result["module"] = IpCore(
                    api_version="1.0",
                    vlnv=vlnv,
                    description=f"Parsed from Verilog module {module_name}",
                    ports=ports,
                )
                return result

        except (re.error, ValueError, KeyError, AttributeError) as e:
            logger.exception("Error in regex parsing: %s", e)

        # If regex approach didn't work, try the pyparsing approach
        if result["module"] is None:
            try:
                logger.debug("Trying pyparsing approach for module")
                module_match = self.module_decl.search_string(verilog_text)
                if module_match and len(module_match) > 0:
                    module_data = module_match[0]
                    result["module"] = self._create_ip_core(module_data)
            except ParseBaseException as e:
                logger.exception("Error parsing module with pyparsing: %s", e)

        return result

    def _create_port(
        self, name: str, direction_str: str, msb: Optional[int], lsb: Optional[int]
    ) -> Port:
        """
        Create a port from extracted values.

        Args:
            name: Port name
            direction_str: Direction string ('input', 'output', 'inout')
            msb: Most significant bit (if vector)
            lsb: Least significant bit (if vector)

        Returns:
            Port object
        """
        # Map direction string to PortDirection enum
        direction = PortDirection.from_string(direction_str)

        # Create type string and calculate width
        width = 1
        type_str = "std_logic"  # Default assumption matching basic wire/reg

        if msb is not None and lsb is not None:
            width = abs(msb - lsb) + 1
            type_str = f"std_logic_vector({msb} downto {lsb})"
            # Note: Verilog wire/reg [msb:lsb] maps conceptually to std_logic_vector
            # We could use "wire [msb:lsb]" string if preferred, but usually we map to abstract types
            # Let's use Verilog syntax for type info to be accurate
            type_str = f"[{msb}:{lsb}]"

        return Port(name=name, direction=direction, width=width, type=type_str)

    def _create_ip_core(self, module_data) -> IpCore:
        """
        Create an IPCore object from parsed module data.

        Args:
            module_data: Parsed module data from pyparsing

        Returns:
            IPCore object representing the parsed module
        """
        module_name = module_data.get("module_name", "")
        ports = []

        # Handle ANSI style module
        if "full_port_list" in module_data:
            for port_decl in module_data["full_port_list"]:
                ports.append(self._create_port_from_decl(port_decl))
        # Handle non-ANSI style module
        elif "port_list" in module_data:
            port_names = module_data["port_list"]
            # Find port declarations in the rest of the module body
            # This logic is simplified; robustness requires regex fallback usually
            # But let's assume packrat parser worked if we are here
            # Actually pyparsing results for ZeroOrMore(self.port_decl) should be adjacent?
            # self.module_non_ansi_decl includes ZeroOrMore(self.port_decl)

            # Extract port definitions from the broader results if possible
            # But module_data might not structurally holding them nicely if they are top level items
            # in module_non_ansi_decl structure.
            # Pyparsing 'results name' behavior can be tricky.
            pass

        vlnv = VLNV(vendor="parsed", library="verilog", name=module_name, version="1.0")
        ip_core = IpCore(
            api_version="1.0",
            vlnv=vlnv,
            description=f"Parsed from Verilog module {module_name}",
            ports=ports,
        )
        return ip_core

    def _create_port_from_decl(self, port_decl) -> Port:
        """
        Create a Port object from parsed port declaration.

        Args:
            port_decl: Parsed port declaration from pyparsing

        Returns:
            Port object representing the port
        """
        name = port_decl["name"]
        direction_str = port_decl[0].lower()

        direction = PortDirection.from_string(direction_str)

        msb = None
        lsb = None
        if "range" in port_decl and port_decl["range"]:
            msb = int(port_decl["range"][0])
            lsb = int(port_decl["range"][1])

        return self._create_port(name, direction_str, msb, lsb)
