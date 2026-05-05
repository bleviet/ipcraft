"""
VHDL Parser module using pyparsing to parse VHDL entities and architectures.
"""

import logging
import re
from typing import Any, Dict, List, Optional

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
    nested_expr,
    one_of,
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
        self.comment = Literal("--") + restOfLine
        self.ignored_text = self.comment

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

        self.identifier = Word(alphas + "_", alphanums + "_")
        self.direction = one_of("in out inout buffer linkage", caseless=True)
        self.simple_type_name = Word(alphas + "_", alphanums + "_.")

        # Use nested_expr to correctly handle ranges with parentheses, including nested ones
        self.range_type = Combine(
            self.simple_type_name + original_text_for(nested_expr())
        )
        self.data_type = self.range_type | self.simple_type_name

        # Captures everything after ":=" until semicolon or closing paren
        self.default_value = Suppress(":=") + original_text_for(
            nested_expr() | CharsNotIn(";)")
        )

        self.port_decl = Group(
            self.identifier.set_results_name("port_name")
            + Suppress(":")
            + self.direction.set_results_name("direction")
            + self.data_type.set_results_name("type")
            + Opt(Suppress(";"))
        ).set_results_name("port_decl")

        self.generic_decl = Group(
            self.identifier.set_results_name("generic_name")
            + Suppress(":")
            + self.data_type.set_results_name("type")
            + Opt(self.default_value.set_results_name("default_value"))
            + Opt(Suppress(";"))
        ).set_results_name("generic_decl")

        self.port_list = Group(
            Suppress("(") + ZeroOrMore(self.port_decl) + Suppress(")")
        ).set_results_name("port_list")

        self.generic_list = Group(
            Suppress("(") + ZeroOrMore(self.generic_decl) + Suppress(")")
        ).set_results_name("generic_list")

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
        """Parse a VHDL file and extract entity and architecture information."""
        with open(file_path, "r") as f:
            content = f.read()
        return self.parse_text(content)

    def parse_text(self, vhdl_text: str) -> Dict[str, Any]:
        """
        Parse VHDL text using pyparsing with regex fallback for each section.

        Returns a dict with keys 'entity', 'architecture', 'package'.
        Falls back to full regex parsing when pyparsing fails for the entity.
        """
        vhdl_text_clean = self._remove_comments(vhdl_text)

        entity = self._parse_entity_result(vhdl_text_clean)
        if entity is None:
            return self._parse_with_regex(vhdl_text_clean)

        return {
            "entity": entity,
            "architecture": self._parse_architecture_result(vhdl_text_clean),
            "package": self._parse_package_result(vhdl_text_clean),
        }

    # ---------------------------------------------------------------------------
    # Section parsers (pyparsing with regex fallback)
    # ---------------------------------------------------------------------------

    def _parse_entity_result(self, vhdl_text_clean: str) -> Optional[IpCore]:
        """Try to parse the entity section with pyparsing. Returns None on failure."""
        try:
            entity_match = self.entity_decl.search_string(vhdl_text_clean)
            if not entity_match:
                return None

            entity_data = entity_match[0]
            entity_name = entity_data.get("entity_name")

            ports = [
                p
                for pd in entity_data.get("port_list", [])
                if (p := self._create_port_from_data(pd))
            ]
            parameters = [
                p
                for gd in entity_data.get("generic_list", [])
                if (p := self._create_parameter_from_data(gd))
            ]

            return IpCore(
                vlnv=VLNV(vendor="parsed", library="vhdl", name=entity_name, version="1.0"),
                description=f"Parsed from VHDL entity {entity_name}",
                ports=ports,
                parameters=parameters,
            )
        except ParseBaseException as e:
            logger.exception("PyParsing exception: %s", e)
            return None

    def _parse_architecture_result(
        self, vhdl_text_clean: str
    ) -> Optional[Dict[str, str]]:
        """Parse the architecture section; falls back to regex."""
        try:
            arch_match = self.architecture_decl.search_string(vhdl_text_clean)
            if arch_match:
                arch_data = arch_match[0]
                return {
                    "name": arch_data.get("arch_name"),
                    "entity": arch_data.get("arch_entity"),
                }
        except ParseBaseException:
            pass

        m = re.search(
            r"architecture\s+(\w+)\s+of\s+(\w+)\s+is",
            vhdl_text_clean,
            re.IGNORECASE | re.DOTALL,
        )
        if m:
            return {"name": m.group(1), "entity": m.group(2)}
        return None

    def _parse_package_result(self, vhdl_text_clean: str) -> Optional[Dict[str, str]]:
        """Parse the package section; falls back to regex."""
        try:
            package_match = self.package_decl.search_string(vhdl_text_clean)
            if package_match:
                return {"name": package_match[0].get("package_name")}
        except ParseBaseException:
            pass

        m = re.search(
            r"package\s+(\w+)\s+is", vhdl_text_clean, re.IGNORECASE | re.DOTALL
        )
        if m:
            return {"name": m.group(1).strip()}
        return None

    # ---------------------------------------------------------------------------
    # Model builders
    # ---------------------------------------------------------------------------

    def _create_port_from_data(self, port_data: dict) -> Optional[Port]:
        """Create a Port object from parsed port data."""
        try:
            port_name = port_data.get("port_name")
            direction_str = port_data.get("direction", "in").lower()
            type_str = self._stringify_type_info(port_data.get("type"))
            direction = PortDirection.from_string(direction_str)
            width = self._parse_downto_width(type_str) if "vector" in type_str.lower() else 1
            return Port(name=port_name, direction=direction, width=width, type=type_str, description="")
        except (ValueError, KeyError, AttributeError) as e:
            logger.exception("Error creating port from data: %s", e)
            return None

    def _create_parameter_from_data(self, generic_data: dict) -> Optional[Parameter]:
        """Create a Parameter object from parsed generic data."""
        try:
            generic_name = generic_data.get("generic_name")
            type_str = self._stringify_type_info(generic_data.get("type"))
            default_value = generic_data.get("default_value")

            if default_value is None:
                parameter_value = 0
            elif isinstance(default_value, str):
                parameter_value = default_value.strip()
            elif hasattr(default_value, "__getitem__") and len(default_value) > 0:
                parameter_value = str(default_value[0]).strip()
            else:
                parameter_value = str(default_value).strip()

            return Parameter(
                name=str(generic_name),
                value=parameter_value if parameter_value is not None else 0,
                description=f"VHDL Type: {type_str}",
            )
        except (ValueError, KeyError, AttributeError) as e:
            logger.exception("Error creating parameter from data: %s", e)
            return None

    # ---------------------------------------------------------------------------
    # Shared utilities
    # ---------------------------------------------------------------------------

    def _stringify_type_info(self, type_info) -> str:
        """Convert a pyparsing ParseResults, list, or string to a plain string."""
        if isinstance(type_info, str):
            return type_info
        if hasattr(type_info, "as_list"):
            return " ".join(str(x) for x in type_info.as_list())
        if isinstance(type_info, list):
            return " ".join(str(x) for x in type_info)
        return str(type_info)

    def _parse_downto_width(self, type_str: str) -> int:
        """Extract bit-width from a VHDL vector range (e.g. '(7 downto 0)' → 8). Returns 1 if not found."""
        m = re.search(r"\((\d+)\s+downto\s+(\d+)\)", type_str, re.IGNORECASE)
        if m:
            return abs(int(m.group(1)) - int(m.group(2))) + 1
        return 1

    def _remove_comments(self, text: str) -> str:
        """Remove VHDL line comments (-- ...) from text."""
        return re.sub(r"--.*$", "", text, flags=re.MULTILINE)

    # ---------------------------------------------------------------------------
    # Regex fallback
    # ---------------------------------------------------------------------------

    def _parse_with_regex(self, vhdl_text_clean: str) -> Dict[str, Any]:
        """Fallback regex-based entity parsing for when pyparsing fails."""
        result: Dict[str, Any] = {
            "entity": None,
            "architecture": self._parse_architecture_result(vhdl_text_clean),
            "package": self._parse_package_result(vhdl_text_clean),
        }

        name_match = re.search(
            r"entity\s+(\w+)\s+is", vhdl_text_clean, re.IGNORECASE | re.DOTALL
        )
        if not name_match:
            return result

        entity_name = name_match.group(1).strip()

        try:
            entity_pattern = (
                rf"entity\s+{re.escape(entity_name)}\s+is\s+(.*?)\s*"
                rf"end\s+(?:entity\s+)?{re.escape(entity_name)}?"
            )
            entity_match = re.search(entity_pattern, vhdl_text_clean, re.IGNORECASE | re.DOTALL)
            if entity_match:
                ports = self._extract_ports_from_body(entity_match.group(1))
                result["entity"] = IpCore(
                    vlnv=VLNV(vendor="parsed", library="vhdl", name=entity_name, version="1.0"),
                    description="Parsed from VHDL (regex fallback)",
                    ports=ports,
                )
        except (ValueError, KeyError, AttributeError) as e:
            logger.exception("Error in regex fallback parsing: %s", e)

        return result

    def _extract_ports_from_body(self, entity_body: str) -> List[Port]:
        """Parse port declarations from an entity body string."""
        port_start = entity_body.find("port")
        if port_start == -1:
            return []

        paren_start = entity_body.find("(", port_start)
        if paren_start == -1:
            return []

        paren_end = self._find_matching_paren(entity_body, paren_start)
        if paren_end == -1:
            return []

        ports = []
        ports_text = entity_body[paren_start + 1 : paren_end]
        for port_part in re.split(r"\s*;\s*", ports_text):
            port_part = re.sub(r"--.*$", "", port_part.strip(), flags=re.MULTILINE).strip()
            if not port_part:
                continue

            m = re.match(
                r"(\w+)\s*:\s*(in|out|inout|buffer|linkage)\s+(.+)",
                port_part,
                re.IGNORECASE | re.DOTALL,
            )
            if not m:
                continue

            p_type = m.group(3)
            ports.append(
                Port(
                    name=m.group(1),
                    direction=PortDirection.from_string(m.group(2)),
                    width=self._parse_downto_width(p_type),
                    type=p_type,
                )
            )

        return ports

    def _find_matching_paren(self, text: str, start: int) -> int:
        """Return the index of the closing paren that matches the open paren at start. Returns -1 if not found."""
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
                if depth == 0:
                    return i
        return -1
