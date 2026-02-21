"""
VHDL Parser module using pyparsing to parse VHDL entities and architectures.
"""

import logging
import re
from typing import Any, Dict

from pyparsing import (
    CaselessKeyword,
    CharsNotIn,
    Combine,
    Group,
    Literal,
    ParseBaseException,
)
from pyparsing import Optional as Opt
from pyparsing import (
    ParserElement,
    SkipTo,
    Suppress,
    Word,
    ZeroOrMore,
    alphanums,
    alphas,
    nestedExpr,
    oneOf,
    original_text_for,
    restOfLine,
)

from ipcraft.model import VLNV, IpCore, Parameter, Port, PortDirection

logger = logging.getLogger(__name__)

# Enable packrat parsing for better performance
ParserElement.set_default_whitespace_chars(" \t\n\r")
ParserElement.enable_packrat()


class VHDLParser:
    """Parser for VHDL files to extract entity and architecture information."""

    def __init__(self):
        """Initialize the VHDL parser with grammar definitions."""
        # Set up comment handling - VHDL comments start with '--' and continue to end of line
        self.comment = Literal("--") + restOfLine
        self.ignored_text = self.comment

        # VHDL keywords (case insensitive)
        self.keywords = {
            "entity": CaselessKeyword("entity"),
            "is": CaselessKeyword("is"),
            "port": CaselessKeyword("port"),
            "generic": CaselessKeyword("generic"),
            "end": CaselessKeyword("end"),
            "architecture": CaselessKeyword("architecture"),
            "of": CaselessKeyword("of"),
            "begin": CaselessKeyword("begin"),
            "in": CaselessKeyword("in"),
            "out": CaselessKeyword("out"),
            "inout": CaselessKeyword("inout"),
            "buffer": CaselessKeyword("buffer"),
            "linkage": CaselessKeyword("linkage"),
            "package": CaselessKeyword("package"),
            "downto": CaselessKeyword("downto"),
            "to": CaselessKeyword("to"),
        }

        # Basic building blocks
        self.identifier = Word(alphas + "_", alphanums + "_")
        self.direction = oneOf("in out inout buffer linkage", caseless=True)

        # Enhanced type handling
        self.simple_type_name = Word(alphas + "_", alphanums + "_.")

        # Use nestedExpr to correctly handle ranges with parentheses, including nested ones
        self.range_type = Combine(self.simple_type_name + original_text_for(nestedExpr()))
        self.data_type = self.range_type | self.simple_type_name

        # Default value for generics - captures everything after ":=" until semicolon or closing paren
        # Enhanced to handle nested expressions like (others => '0')
        self.default_value = Suppress(":=") + original_text_for(nestedExpr() | CharsNotIn(";)"))

        # Enhanced port declaration parser
        self.port_decl = Group(
            self.identifier.set_results_name("port_name")
            + Suppress(":")
            + self.direction.set_results_name("direction")
            + self.data_type.set_results_name("type")
            + Opt(Suppress(";"))  # Semicolon is optional to handle the last port
        ).set_results_name("port_decl")

        # Generic declaration parser
        self.generic_decl = Group(
            self.identifier.set_results_name("generic_name")
            + Suppress(":")
            + self.data_type.set_results_name("type")
            + Opt(self.default_value.set_results_name("default_value"))
            + Opt(Suppress(";"))  # Semicolon is optional to handle the last generic
        ).set_results_name("generic_decl")

        # Port list that captures all ports, including the last one
        self.port_list = Group(
            Suppress("(") + ZeroOrMore(self.port_decl) + Suppress(")")
        ).set_results_name("port_list")

        # Generic list that captures all generics
        self.generic_list = Group(
            Suppress("(") + ZeroOrMore(self.generic_decl) + Suppress(")")
        ).set_results_name("generic_list")

        # Entity declaration parser with optional generics
        self.entity_decl = (
            self.keywords["entity"]
            + self.identifier.set_results_name("entity_name")
            + self.keywords["is"]
            + Opt(self.keywords["generic"] + self.generic_list + Suppress(";"))
            + self.keywords["port"]
            + self.port_list
            + Suppress(";")
            + self.keywords["end"]
            + Opt(self.keywords["entity"])
            + Opt(self.identifier)
            + Suppress(";")
        ).set_results_name("entity_decl")

        # Architecture declaration parser
        self.architecture_decl = (
            self.keywords["architecture"]
            + self.identifier.set_results_name("arch_name")
            + self.keywords["of"]
            + self.identifier.set_results_name("arch_entity")
            + self.keywords["is"]
            + SkipTo(self.keywords["begin"])
            + self.keywords["begin"]
            + SkipTo(self.keywords["end"])
            + self.keywords["end"]
            + Opt(self.keywords["architecture"])
            + Opt(self.identifier)
            + Suppress(";")
        ).set_results_name("architecture_decl")

        # Package declaration parser
        self.package_decl = (
            self.keywords["package"]
            + self.identifier.set_results_name("package_name")
            + self.keywords["is"]
            + SkipTo(self.keywords["end"])
            + self.keywords["end"]
            + Opt(self.keywords["package"])
            + Opt(self.identifier)
            + Suppress(";")
        ).set_results_name("package_decl")

    def parse_file(self, file_path: str) -> Dict[str, Any]:
        """
        Parse a VHDL file and extract entity and architecture information.

        Args:
            file_path: Path to the VHDL file

        Returns:
            Dictionary containing parsed entity and architecture information
        """
        with open(file_path, "r") as f:
            content = f.read()
        return self.parse_text(content)

    def parse_text(self, vhdl_text: str) -> Dict[str, Any]:
        """
        Parse VHDL text and extract entity and architecture information using pyparsing.

        Args:
            vhdl_text: VHDL code to parse

        Returns:
            Dictionary containing parsed entity and architecture information
        """
        result = {"entity": None, "architecture": None, "package": None}

        # Remove comments to simplify parsing
        vhdl_text_clean = self._remove_comments(vhdl_text)

        # Try to parse the entity using pyparsing
        try:
            entity_match = self.entity_decl.search_string(vhdl_text_clean)
            if entity_match and len(entity_match) > 0:
                entity_data = entity_match[0]
                entity_name = entity_data.get("entity_name")
                port_list = entity_data.get("port_list", [])
                generic_list = entity_data.get("generic_list", [])

                # Create ports from port_list
                ports = []
                for port_data in port_list:
                    port = self._create_port_from_data(port_data)
                    if port:
                        ports.append(port)

                # Create basic VLNV for parsed core
                vlnv = VLNV(vendor="parsed", library="vhdl", name=entity_name, version="1.0")

                # Create IPCore directly
                ip_core = IpCore(
                    api_version="1.0",
                    vlnv=vlnv,
                    description=f"Parsed from VHDL entity {entity_name}",
                    ports=ports,
                )

                # Add generics as parameters to the IPCore
                parameters = []
                for generic_data in generic_list:
                    parameter = self._create_parameter_from_data(generic_data)
                    if parameter:
                        parameters.append(parameter)

                # Update parameters field (it's a list)
                if parameters:
                    ip_core.parameters = parameters

                result["entity"] = ip_core
        except ParseBaseException as e:
            logger.exception("PyParsing exception: %s", e)
            # No return here, let it fall through to regex check if entity is still None

        # If pyparsing didn't find an entity, try regex-based parsing as fallback
        if result["entity"] is None:
            return self._parse_with_regex(vhdl_text_clean)

        # Parse architecture using pyparsing
        try:
            arch_match = self.architecture_decl.search_string(vhdl_text_clean)
            if arch_match and len(arch_match) > 0:
                arch_data = arch_match[0]
                result["architecture"] = {
                    "name": arch_data.get("arch_name"),
                    "entity": arch_data.get("arch_entity"),
                }
        except ParseBaseException as e:
            # Fall back to regex for architecture
            arch_match = re.search(
                r"architecture\s+(\w+)\s+of\s+(\w+)\s+is",
                vhdl_text_clean,
                re.IGNORECASE | re.DOTALL,
            )
            if arch_match:
                result["architecture"] = {
                    "name": arch_match.group(1),
                    "entity": arch_match.group(2),
                }

        # Parse package using pyparsing
        try:
            package_match = self.package_decl.search_string(vhdl_text_clean)
            if package_match and len(package_match) > 0:
                package_data = package_match[0]
                result["package"] = {"name": package_data.get("package_name")}
        except ParseBaseException as e:
            # Fall back to regex for package
            package_match = re.search(
                r"package\s+(\w+)\s+is", vhdl_text_clean, re.IGNORECASE | re.DOTALL
            )
            if package_match:
                result["package"] = {"name": package_match.group(1).strip()}

        return result

    def _create_port_from_data(self, port_data: dict) -> Port:
        """
        Create a Port object from parsed port data.

        Args:
            port_data: Dictionary containing port data

        Returns:
            Port object
        """
        try:
            port_name = port_data.get("port_name")
            direction_str = port_data.get("direction", "in").lower()
            type_info = port_data.get("type")

            # Handle type info which might be ParseResults or list or string
            original_type_str = ""
            if isinstance(type_info, str):
                original_type_str = type_info
            elif hasattr(type_info, "as_list"):
                original_type_str = " ".join([str(x) for x in type_info.as_list()])
            elif isinstance(type_info, list):
                original_type_str = " ".join([str(x) for x in type_info])
            else:
                original_type_str = str(type_info)

            # Map direction string to PortDirection enum
            direction = PortDirection.from_string(direction_str)

            # Extract width from type definition if possible
            width = 1
            if "vector" in original_type_str.lower():
                # Check for (N downto M)
                # Regex must handle potential spaces if Combine preserved them or if original had them
                range_match = re.search(
                    r"\((\d+)\s+downto\s+(\d+)\)", original_type_str, re.IGNORECASE
                )
                if range_match:
                    high = int(range_match.group(1))
                    low = int(range_match.group(2))
                    width = abs(high - low) + 1
                else:
                    # Could be parameterized width
                    pass

            port = Port(
                name=port_name,
                direction=direction,
                width=width,
                type=original_type_str,
                description="",
            )

            return port
        except (ValueError, KeyError, AttributeError) as e:
            logger.exception("Error creating port from data: %s", e)
            return None

    def _create_parameter_from_data(self, generic_data: dict):
        """
        Create a Parameter object from parsed generic data.

        Args:
            generic_data: Dictionary containing generic data

        Returns:
            Parameter object
        """
        try:
            generic_name = generic_data.get("generic_name")
            type_info = generic_data.get("type")
            default_value = generic_data.get("default_value")

            original_type_str = ""
            if isinstance(type_info, str):
                original_type_str = type_info
            elif hasattr(type_info, "as_list"):
                original_type_str = " ".join([str(x) for x in type_info.as_list()])
            elif isinstance(type_info, list):
                original_type_str = " ".join([str(x) for x in type_info])
            else:
                original_type_str = str(type_info)

            # Create parameter value
            parameter_value = None
            if default_value is not None:
                if isinstance(default_value, str):
                    parameter_value = default_value.strip()
                elif hasattr(default_value, "__getitem__") and len(default_value) > 0:
                    # Handle ParseResults/list by taking first element which is the captured string
                    parameter_value = str(default_value[0]).strip()
                else:
                    parameter_value = str(default_value).strip()

            parameter = Parameter(
                name=str(generic_name),  # Explicit cast
                value=(
                    parameter_value if parameter_value is not None else 0
                ),  # Default to 0/empty if None
                description=f"VHDL Type: {original_type_str}",
            )

            return parameter
        except (ValueError, KeyError, AttributeError) as e:
            logger.exception("Error creating parameter from data: %s", e)
            return None

    def _remove_comments(self, text):
        """Remove comments from VHDL text."""
        result = re.sub(r"--.*$", "", text, flags=re.MULTILINE)
        return result

    def _parse_with_regex(self, vhdl_text_clean):
        """Fallback regex-based parsing for when pyparsing fails."""
        result = {"entity": None, "architecture": None, "package": None}

        # Get entity name
        entity_name_match = re.search(
            r"entity\s+(\w+)\s+is", vhdl_text_clean, re.IGNORECASE | re.DOTALL
        )
        expected_entity_name = None
        if entity_name_match:
            expected_entity_name = entity_name_match.group(1).strip()

        # Extract ports from entity
        if expected_entity_name:
            try:
                # Find the complete entity definition including generics and ports
                entity_pattern = rf"entity\s+{re.escape(expected_entity_name)}\s+is\s+(.*?)\s*end\s+(?:entity\s+)?{re.escape(expected_entity_name)}?"
                entity_match = re.search(entity_pattern, vhdl_text_clean, re.IGNORECASE | re.DOTALL)

                if entity_match:
                    entity_body = entity_match.group(1)

                    # Extract port section - look for port ( ... );
                    ports = []
                    port_start = entity_body.find("port")
                    if port_start != -1:
                        paren_start = entity_body.find("(", port_start)
                        if paren_start != -1:
                            # Simple paren counting (same as strict parser logic)
                            paren_count = 0
                            paren_end = -1
                            for i in range(paren_start, len(entity_body)):
                                if entity_body[i] == "(":
                                    paren_count += 1
                                elif entity_body[i] == ")":
                                    paren_count -= 1
                                    if paren_count == 0:
                                        paren_end = i
                                        break

                            if paren_end != -1:
                                ports_text = entity_body[paren_start + 1 : paren_end]
                                port_parts = re.split(r"\s*;\s*", ports_text)

                                for port_part in port_parts:
                                    port_part = port_part.strip()
                                    if not port_part:
                                        continue
                                    port_part = re.sub(
                                        r"--.*$", "", port_part, flags=re.MULTILINE
                                    ).strip()

                                    # Regex match port
                                    port_match = re.match(
                                        r"(\w+)\s*:\s*(in|out|inout|buffer|linkage)\s+(.+)",
                                        port_part,
                                        re.IGNORECASE | re.DOTALL,
                                    )
                                    if port_match:
                                        p_name = port_match.group(1)
                                        p_dir_str = port_match.group(2).lower()
                                        p_type = port_match.group(3)

                                        p_dir = {
                                            "in": PortDirection.IN,
                                            "out": PortDirection.OUT,
                                            "inout": PortDirection.INOUT,
                                            "buffer": PortDirection.OUT,
                                            "linkage": PortDirection.IN,
                                        }.get(p_dir_str, PortDirection.IN)

                                        # Width calc
                                        width = 1
                                        range_match = re.search(r"\((.*?)\)", p_type)
                                        if range_match:
                                            r_str = range_match.group(1)
                                            downto = re.search(r"(\d+)\s+downto\s+(\d+)", r_str)
                                            if downto:
                                                width = (
                                                    int(downto.group(1)) - int(downto.group(2)) + 1
                                                )

                                        ports.append(
                                            Port(
                                                name=p_name,
                                                direction=p_dir,
                                                width=width,
                                                type=p_type,
                                            )
                                        )

                    # Create VLNV
                    vlnv = VLNV(
                        vendor="parsed", library="vhdl", name=expected_entity_name, version="1.0"
                    )
                    ip_core = IpCore(
                        api_version="1.0",
                        vlnv=vlnv,
                        description=f"Parsed from VHDL (regex fallback)",
                        ports=ports,
                    )

                    result["entity"] = ip_core
            except (ValueError, KeyError, AttributeError) as e:
                logger.exception("Error in regex fallback parsing: %s", e)

        # Parse architecture (regex)
        try:
            arch_match = re.search(
                r"architecture\s+(\w+)\s+of\s+(\w+)\s+is",
                vhdl_text_clean,
                re.IGNORECASE | re.DOTALL,
            )
            if arch_match:
                result["architecture"] = {
                    "name": arch_match.group(1),
                    "entity": arch_match.group(2),
                }
        except (re.error, AttributeError):
            pass

        try:
            package_match = re.search(
                r"package\s+(\w+)\s+is", vhdl_text_clean, re.IGNORECASE | re.DOTALL
            )
            if package_match:
                result["package"] = {"name": package_match.group(1).strip()}
        except (re.error, AttributeError):
            pass

        return result
