"""
YAML Parser for IP Core definitions.

Loads YAML files and converts them to canonical Pydantic models.
Supports imports, bus library loading, and memory map references.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Union, Callable, TypeVar

T = TypeVar("T")

import yaml
from pydantic import ValidationError

from ipcraft.model import (
    VLNV,
    AccessType,
    ArrayConfig,
    BusInterface,
    Clock,
    IpCore,
    Parameter,
    Polarity,
    Port,
    Reset,
)

from .errors import ParseError
from .fileset_parser import FileSetParserMixin
from .memory_map_parser import MemoryMapParserMixin
from ipcraft.utils import filter_none


class YamlIpCoreParser(MemoryMapParserMixin, FileSetParserMixin):
    """
    Parser for IP core YAML definitions.

    Handles:
    - Main IP core file parsing
    - Bus library loading and caching
    - Memory map imports (separate files)
    - FileSet imports
    - Validation and error reporting with line numbers
    """

    def __init__(self):
        self._bus_library_cache: Dict[Path, Dict[str, Any]] = {}
        self._register_templates: Dict[str, List[Dict[str, Any]]] = {}
        self._current_file: Optional[Path] = None

    @staticmethod
    def _parse_access(access: Any) -> AccessType:
        """Normalize access values into ``AccessType`` consistently."""
        if isinstance(access, AccessType):
            return access
        if isinstance(access, str):
            return AccessType.from_string(access)
        return AccessType.READ_WRITE

    def parse_file(self, file_path: Union[str, Path]) -> IpCore:
        """
        Parse an IP core YAML file.

        Args:
            file_path: Path to the IP core YAML file

        Returns:
            IpCore: Validated IP core model

        Raises:
            ParseError: If parsing or validation fails
        """
        file_path = Path(file_path).resolve()
        self._current_file = file_path

        if not file_path.exists():
            raise ParseError(f"File not found: {file_path}")

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            line = getattr(e, "problem_mark", None)
            line_num = line.line + 1 if line else None
            raise ParseError(f"YAML syntax error: {e}", file_path, line_num)

        if not isinstance(data, dict):
            raise ParseError("Root element must be a YAML object/dictionary", file_path)

        try:
            return self._parse_ip_core(data, file_path)
        except ValidationError as e:
            # Convert Pydantic validation errors to ParseError
            errors = []
            for error in e.errors():
                loc = " -> ".join(str(x) for x in error["loc"])
                errors.append(f"{loc}: {error['msg']}")
            raise ParseError(f"Validation failed:\n  " + "\n  ".join(errors), file_path)

    def _parse_ip_core(self, data: Dict[str, Any], file_path: Path) -> IpCore:
        """Parse the main IP core structure."""
        # Required fields
        api_version = data.get("apiVersion")
        if not api_version:
            raise ParseError("Missing required field: apiVersion", file_path)

        # Convert numeric apiVersion to string if needed
        api_version = str(api_version)

        vlnv_data = data.get("vlnv")
        if not vlnv_data:
            raise ParseError("Missing required field: vlnv", file_path)

        # Parse VLNV
        vlnv = self._parse_vlnv(vlnv_data, file_path)

        # Parse optional sections
        description = data.get("description")
        clocks = self._parse_clocks(data.get("clocks", []), file_path)
        resets = self._parse_resets(data.get("resets", []), file_path)
        ports = self._parse_ports(data.get("ports", []), file_path)

        # Load bus library if specified
        bus_library = data.get("useBusLibrary")
        if bus_library:
            # Resolve relative to the current file
            bus_lib_path = (file_path.parent / bus_library).resolve()
            self._load_bus_library(bus_lib_path)

        bus_interfaces = self._parse_bus_interfaces(data.get("busInterfaces", []), file_path)
        parameters = self._parse_parameters(data.get("parameters", []), file_path)

        # Parse memory maps (may include imports)
        memory_maps = self._parse_memory_maps(data.get("memoryMaps", {}), file_path)

        # Parse file sets (may include imports)
        file_sets = self._parse_file_sets(data.get("fileSets", []), file_path)

        # Create IpCore model - only pass non-empty values to use Pydantic defaults
        kwargs = {
            "api_version": api_version,
            "vlnv": vlnv,
        }
        if description:
            kwargs["description"] = description
        if clocks:
            kwargs["clocks"] = clocks
        if resets:
            kwargs["resets"] = resets
        if ports:
            kwargs["ports"] = ports
        if bus_interfaces:
            kwargs["bus_interfaces"] = bus_interfaces
        if memory_maps:
            kwargs["memory_maps"] = memory_maps
        if parameters:
            kwargs["parameters"] = parameters
        if file_sets:
            kwargs["file_sets"] = file_sets
        if bus_library:
            kwargs["use_bus_library"] = bus_library

        return IpCore(**kwargs)

    def _parse_list(
        self,
        data: List[Dict[str, Any]],
        kind: str,
        builder: Callable[[Dict[str, Any]], T],
        file_path: Path,
    ) -> List[T]:
        """Generic list parser with consistent error handling.

        Args:
            data: List of raw dicts from YAML.
            kind: Human-readable item kind for error messages (e.g. 'clock', 'port').
            builder: Callable that converts one raw dict into a model instance.
            file_path: Source file path for error context.

        Returns:
            List of parsed model instances.
        """
        results = []
        for idx, item_data in enumerate(data):
            try:
                results.append(builder(item_data))
            except (KeyError, TypeError, ValueError, ValidationError) as e:
                raise ParseError(f"Error parsing {kind}[{idx}]: {e}", file_path)
        return results

    def _parse_vlnv(self, data: Dict[str, Any], file_path: Path) -> VLNV:
        """Parse VLNV structure."""
        required = ["vendor", "library", "name", "version"]
        for field in required:
            if field not in data:
                raise ParseError(f"VLNV missing required field: {field}", file_path)

        return VLNV(
            vendor=data["vendor"],
            library=data["library"],
            name=data["name"],
            version=data["version"],
        )

    def _parse_clocks(self, data: List[Dict[str, Any]], file_path: Path) -> List[Clock]:
        """Parse clock definitions."""
        def build_clock(d):
            return Clock(**filter_none({
                "name": d.get("name"),
                "logical_name": d.get("logicalName", "CLK"),
                "direction": d.get("direction", "in"),
                "frequency": d.get("frequency"),
                "description": d.get("description"),
            }))
        return self._parse_list(data, "clock", build_clock, file_path)

    def _parse_resets(self, data: List[Dict[str, Any]], file_path: Path) -> List[Reset]:
        """Parse reset definitions."""
        def build_reset(d):
            polarity_str = d.get("polarity", "activeLow")
            polarity = Polarity.ACTIVE_LOW if polarity_str == "activeLow" else Polarity.ACTIVE_HIGH
            default_logical = "RESET_N" if polarity_str in ["activeLow", "active_low"] else "RESET"
            return Reset(**filter_none({
                "name": d.get("name"),
                "logical_name": d.get("logicalName", default_logical),
                "direction": d.get("direction", "in"),
                "polarity": polarity,
                "description": d.get("description"),
            }))
        return self._parse_list(data, "reset", build_reset, file_path)

    def _parse_ports(self, data: List[Dict[str, Any]], file_path: Path) -> List[Port]:
        """Parse port definitions."""
        def build_port(d):
            return Port(**filter_none({
                "name": d.get("name"),
                "logical_name": d.get("logicalName", ""),
                "direction": d.get("direction"),
                "width": d.get("width", 1),
                "description": d.get("description"),
            }))
        return self._parse_list(data, "port", build_port, file_path)

    def _parse_bus_interfaces(
        self, data: List[Dict[str, Any]], file_path: Path
    ) -> List[BusInterface]:
        """Parse bus interface definitions."""
        def build_bus(d):
            array_config = None
            if "array" in d:
                array_data = d["array"]
                array_config = ArrayConfig(
                    count=array_data.get("count"),
                    index_start=array_data.get("indexStart", 0),
                    naming_pattern=array_data.get("namingPattern"),
                    physical_prefix_pattern=array_data.get("physicalPrefixPattern"),
                )
            return BusInterface(**filter_none({
                "name": d.get("name"),
                "type": d.get("type"),
                "mode": d.get("mode"),
                "physical_prefix": d.get("physicalPrefix"),
                "associated_clock": d.get("associatedClock"),
                "associated_reset": d.get("associatedReset"),
                "memory_map_ref": d.get("memoryMapRef"),
                "use_optional_ports": d.get("useOptionalPorts"),
                "port_width_overrides": d.get("portWidthOverrides"),
                "array": array_config,
            }))
        return self._parse_list(data, "busInterface", build_bus, file_path)

    def _parse_parameters(self, data: List[Dict[str, Any]], file_path: Path) -> List[Parameter]:
        """Parse parameter definitions."""
        def build_param(d):
            return Parameter(**filter_none({
                "name": d.get("name"),
                "value": d.get("value"),
                "data_type": d.get("dataType", "integer"),
                "description": d.get("description"),
            }))
        return self._parse_list(data, "parameter", build_param, file_path)

    def _load_bus_library(self, file_path: Path) -> Dict[str, Any]:
        """Load and cache bus library definitions."""
        if file_path in self._bus_library_cache:
            return self._bus_library_cache[file_path]

        if not file_path.exists():
            raise ParseError(f"Bus library file not found: {file_path}")

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                bus_lib = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ParseError(f"YAML syntax error in bus library: {e}", file_path)

        self._bus_library_cache[file_path] = bus_lib
        return bus_lib
