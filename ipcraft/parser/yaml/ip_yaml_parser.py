"""
YAML Parser for IP Core definitions.

Loads YAML files and converts them to canonical Pydantic models.
Supports imports, bus library loading, and memory map references.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Union

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
    def _filter_none(data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Remove keys with None values from dictionary.

        This is required for Pydantic v2 compatibility. When a model field has
        a default value or default_factory, passing None explicitly causes
        validation errors. By filtering None values, we let Pydantic use its
        own defaults instead.

        Args:
            data: Dictionary that may contain None values

        Returns:
            Dictionary with all None-valued keys removed

        Example:
            >>> # Without filtering - FAILS if description has default value:
            >>> Clock(name="CLK", description=None)
            ValidationError: description field expects string, got None

            >>> # With filtering - WORKS:
            >>> Clock(**_filter_none({"name": "CLK", "description": None}))
            Clock(name="CLK", description="")  # Uses default value
        """
        return {k: v for k, v in data.items() if v is not None}

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
        clocks = []
        for idx, clock_data in enumerate(data):
            try:
                clocks.append(
                    Clock(
                        **self._filter_none(
                            {
                                "name": clock_data.get("name"),
                                "logical_name": clock_data.get("logicalName", "CLK"),
                                "direction": clock_data.get("direction", "in"),
                                "frequency": clock_data.get("frequency"),
                                "description": clock_data.get("description"),
                            }
                        )
                    )
                )
            except (KeyError, TypeError, ValueError, ValidationError) as e:
                raise ParseError(f"Error parsing clock[{idx}]: {e}", file_path)
        return clocks

    def _parse_resets(self, data: List[Dict[str, Any]], file_path: Path) -> List[Reset]:
        """Parse reset definitions."""
        resets = []
        for idx, reset_data in enumerate(data):
            try:
                polarity_str = reset_data.get("polarity", "activeLow")
                polarity = (
                    Polarity.ACTIVE_LOW if polarity_str == "activeLow" else Polarity.ACTIVE_HIGH
                )
                # Default logical name based on polarity
                default_logical = (
                    "RESET_N"
                    if polarity_str == "activeLow" or polarity_str == "active_low"
                    else "RESET"
                )

                resets.append(
                    Reset(
                        **self._filter_none(
                            {
                                "name": reset_data.get("name"),
                                "logical_name": reset_data.get("logicalName", default_logical),
                                "direction": reset_data.get("direction", "in"),
                                "polarity": polarity,
                                "description": reset_data.get("description"),
                            }
                        )
                    )
                )
            except (KeyError, TypeError, ValueError, ValidationError) as e:
                raise ParseError(f"Error parsing reset[{idx}]: {e}", file_path)
        return resets

    def _parse_ports(self, data: List[Dict[str, Any]], file_path: Path) -> List[Port]:
        """Parse port definitions."""
        ports = []
        for idx, port_data in enumerate(data):
            try:
                ports.append(
                    Port(
                        **self._filter_none(
                            {
                                "name": port_data.get("name"),
                                "logical_name": port_data.get("logicalName", ""),
                                "direction": port_data.get("direction"),
                                "width": port_data.get("width", 1),
                                "description": port_data.get("description"),
                            }
                        )
                    )
                )
            except (KeyError, TypeError, ValueError, ValidationError) as e:
                raise ParseError(f"Error parsing port[{idx}]: {e}", file_path)
        return ports

    def _parse_bus_interfaces(
        self, data: List[Dict[str, Any]], file_path: Path
    ) -> List[BusInterface]:
        """Parse bus interface definitions."""
        interfaces = []
        for idx, bus_data in enumerate(data):
            try:
                # Parse array configuration if present
                array_config = None
                if "array" in bus_data:
                    array_data = bus_data["array"]
                    array_config = ArrayConfig(
                        count=array_data.get("count"),
                        index_start=array_data.get("indexStart", 0),
                        naming_pattern=array_data.get("namingPattern"),
                        physical_prefix_pattern=array_data.get("physicalPrefixPattern"),
                    )

                interfaces.append(
                    BusInterface(
                        **self._filter_none(
                            {
                                "name": bus_data.get("name"),
                                "type": bus_data.get("type"),
                                "mode": bus_data.get("mode"),
                                "physical_prefix": bus_data.get("physicalPrefix"),
                                "associated_clock": bus_data.get("associatedClock"),
                                "associated_reset": bus_data.get("associatedReset"),
                                "memory_map_ref": bus_data.get("memoryMapRef"),
                                "use_optional_ports": bus_data.get("useOptionalPorts"),
                                "port_width_overrides": bus_data.get("portWidthOverrides"),
                                "array": array_config,
                            }
                        )
                    )
                )
            except (KeyError, TypeError, ValueError, ValidationError) as e:
                raise ParseError(f"Error parsing busInterface[{idx}]: {e}", file_path)
        return interfaces

    def _parse_parameters(self, data: List[Dict[str, Any]], file_path: Path) -> List[Parameter]:
        """Parse parameter definitions."""
        parameters = []
        for idx, param_data in enumerate(data):
            try:
                parameters.append(
                    Parameter(
                        **self._filter_none(
                            {
                                "name": param_data.get("name"),
                                "value": param_data.get("value"),
                                "data_type": param_data.get("dataType", "integer"),
                                "description": param_data.get("description"),
                            }
                        )
                    )
                )
            except (KeyError, TypeError, ValueError, ValidationError) as e:
                raise ParseError(f"Error parsing parameter[{idx}]: {e}", file_path)
        return parameters

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
