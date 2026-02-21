"""Memory map parsing mixin for ``YamlIpCoreParser``."""

from pathlib import Path
from typing import Any, Dict, List, Union

import yaml
from pydantic import ValidationError

from ipcraft.model import AddressBlock, MemoryMap
from ipcraft.model.memory_map import BitFieldDef, RegisterDef
from ipcraft.utils import parse_bit_range, filter_none

from .errors import ParseError
from .protocols import ParserHostContext


class MemoryMapParserMixin(ParserHostContext):
    """Mixin implementing memory map parsing and expansion logic."""

    def _build_register_def(
        self,
        *,
        name: str,
        address_offset: int,
        size: int = 32,
        access: str = "read-write",
        description: str = None,
        reset_value: int = None,
        fields: list = None,
    ) -> RegisterDef:
        """Build a RegisterDef from parsed data with consistent field mapping.

        Centralizes the RegisterDef construction pattern to avoid duplication
        across _parse_registers, _expand_nested_register_array, and
        _expand_register_array.

        Args:
            name: Register name.
            address_offset: Byte offset within the address block.
            size: Register width in bits (default 32).
            access: Access type string (default "read-write").
            description: Optional register description.
            reset_value: Optional reset/default value.
            fields: Optional list of parsed BitFieldDef objects.

        Returns:
            Validated RegisterDef instance.
        """
        return RegisterDef(
            **filter_none(
                {
                    "name": name,
                    "address_offset": address_offset,
                    "size": size,
                    "access": self._parse_access(access),
                    "description": description,
                    "reset_value": reset_value,
                    "fields": fields if fields else None,
                }
            )
        )

    def _parse_memory_maps(
        self, data: Union[Dict[str, Any], List[Dict[str, Any]]], file_path: Path
    ) -> List[MemoryMap]:
        """Parse memory maps, including import forms and inline list forms."""
        if not data:
            return []

        if isinstance(data, dict) and "import" in data:
            import_path = (file_path.parent / data["import"]).resolve()
            return self._load_memory_maps_from_file(import_path)

        if isinstance(data, list):
            return self._parse_memory_map_list(data, file_path)

        raise ParseError("memoryMaps must be either {import: ...} or a list", file_path)

    def _load_memory_maps_from_file(self, file_path: Path) -> List[MemoryMap]:
        """Load memory maps from an external YAML file."""
        if not file_path.exists():
            raise ParseError(f"Memory map file not found: {file_path}")

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            docs = list(yaml.safe_load_all(content))
        except yaml.YAMLError as e:
            raise ParseError(f"YAML syntax error in memory map file: {e}", file_path)

        if (
            len(docs) > 1
            and isinstance(docs[0], dict)
            and "registerTemplates" in docs[0]
        ):
            self._register_templates = docs[0]["registerTemplates"]
            map_data = docs[1]
        else:
            map_data = docs[-1] if docs else []

        if isinstance(map_data, list):
            return self._parse_memory_map_list(map_data, file_path)
        if isinstance(map_data, dict):
            return self._parse_memory_map_list([map_data], file_path)
        raise ParseError(f"Invalid memory map structure in {file_path}", file_path)

    def _parse_memory_map_list(
        self, data: List[Dict[str, Any]], file_path: Path
    ) -> List[MemoryMap]:
        """Parse list-form memory map definitions."""
        memory_maps = []
        for idx, map_data in enumerate(data):
            try:
                address_blocks = self._parse_address_blocks(
                    map_data.get("addressBlocks", []), file_path
                )
                memory_maps.append(
                    MemoryMap(
                        **filter_none(
                            {
                                "name": map_data.get("name"),
                                "description": map_data.get("description"),
                                "address_blocks": (
                                    address_blocks if address_blocks else None
                                ),
                            }
                        )
                    )
                )
            except (KeyError, TypeError, ValueError, ValidationError) as e:
                raise ParseError(f"Error parsing memoryMap[{idx}]: {e}", file_path)
        return memory_maps

    def _parse_address_blocks(
        self, data: List[Dict[str, Any]], file_path: Path
    ) -> List[AddressBlock]:
        """Parse address blocks and nested register definitions."""
        blocks = []
        for idx, block_data in enumerate(data):
            try:
                base_address = block_data.get("baseAddress", 0)
                registers = self._parse_registers(
                    block_data.get("registers", []), file_path
                )

                range_value = block_data.get("range")
                if range_value is None and registers:
                    max_offset = max(
                        reg.address_offset + (reg.size // 8) for reg in registers
                    )
                    range_value = max(max_offset, 64)
                elif range_value is None:
                    range_value = 4096

                blocks.append(
                    AddressBlock(
                        **filter_none(
                            {
                                "name": block_data.get("name"),
                                "base_address": base_address,
                                "range": range_value,
                                "description": block_data.get("description"),
                                "usage": block_data.get("usage", "register"),
                                "default_reg_width": block_data.get("defaultRegWidth"),
                                "registers": registers if registers else None,
                            }
                        )
                    )
                )
            except (KeyError, TypeError, ValueError, ValidationError) as e:
                raise ParseError(f"Error parsing addressBlock[{idx}]: {e}", file_path)
        return blocks

    def _parse_registers(
        self, data: List[Dict[str, Any]], file_path: Path
    ) -> List[RegisterDef]:
        """Parse register definitions and expand array/template constructs."""
        registers = []
        current_offset = 0

        for idx, reg_data in enumerate(data):
            try:
                if "reserved" in reg_data:
                    current_offset += reg_data["reserved"]
                    continue

                if "registers" in reg_data and "count" in reg_data:
                    expanded_regs = self._expand_nested_register_array(
                        reg_data, current_offset, file_path
                    )
                    registers.extend(expanded_regs)
                    if expanded_regs:
                        last_reg = expanded_regs[-1]
                        current_offset = last_reg.address_offset + (last_reg.size // 8)
                    continue

                if "generateArray" in reg_data:
                    expanded_regs = self._expand_register_array(
                        reg_data["generateArray"], current_offset, file_path
                    )
                    registers.extend(expanded_regs)
                    if expanded_regs:
                        last_reg = expanded_regs[-1]
                        current_offset = last_reg.address_offset + (last_reg.size // 8)
                    continue

                address_offset = reg_data.get("addressOffset") or reg_data.get("offset")
                if address_offset is None:
                    address_offset = current_offset

                size = reg_data.get("size", 32)
                fields = self._parse_bit_fields(reg_data.get("fields", []), file_path)

                registers.append(
                    self._build_register_def(
                        name=reg_data.get("name"),
                        address_offset=address_offset,
                        size=size,
                        access=reg_data.get("access", "read-write"),
                        description=reg_data.get("description"),
                        reset_value=reg_data.get("resetValue"),
                        fields=fields,
                    )
                )
                current_offset = address_offset + (size // 8)
            except (KeyError, TypeError, ValueError, ValidationError) as e:
                raise ParseError(f"Error parsing register[{idx}]: {e}", file_path)

        return registers

    def _expand_nested_register_array(
        self, array_spec: Dict[str, Any], base_offset: int, file_path: Path
    ) -> List[RegisterDef]:
        """Expand nested register arrays used in .mm.yml format."""
        base_name = array_spec.get("name", "REG")
        count = array_spec.get("count", 1)
        stride = array_spec.get("stride", 4)
        sub_registers = array_spec.get("registers", [])

        if not sub_registers:
            raise ParseError(
                f"Nested register array '{base_name}' has no sub-registers", file_path
            )

        registers = []
        for instance_idx in range(count):
            instance_offset = base_offset + (instance_idx * stride)
            for sub_reg in sub_registers:
                reg_name = f"{base_name}_{instance_idx}_{sub_reg['name']}"
                final_offset = instance_offset + sub_reg.get("offset", 0)
                size = sub_reg.get("size", 32)
                fields = self._parse_bit_fields(sub_reg.get("fields", []), file_path)

                registers.append(
                    self._build_register_def(
                        name=reg_name,
                        address_offset=final_offset,
                        size=size,
                        access=sub_reg.get("access", "read-write"),
                        description=sub_reg.get("description"),
                        reset_value=sub_reg.get("resetValue"),
                        fields=fields,
                    )
                )

        return registers

    def _expand_register_array(
        self, array_spec: Dict[str, Any], start_offset: int, file_path: Path
    ) -> List[RegisterDef]:
        """Expand legacy ``generateArray`` register templates."""
        base_name = array_spec.get("name", "REG")
        count = array_spec.get("count", 1)
        template_name = array_spec.get("template")

        if not template_name:
            raise ParseError("generateArray requires 'template' field", file_path)
        if template_name not in self._register_templates:
            raise ParseError(
                f"Register template '{template_name}' not found. Available: {list(self._register_templates.keys())}",
                file_path,
            )

        template = self._register_templates[template_name]
        registers = []
        current_offset = start_offset

        for instance_idx in range(count):
            instance_num = instance_idx + 1
            for template_reg in template:
                reg_name = template_reg.get("name", "")
                reg_name = (
                    f"{base_name}{instance_num}{reg_name}"
                    if reg_name.startswith("_")
                    else f"{base_name}{instance_num}_{reg_name}"
                )

                size = template_reg.get("size", 32)
                fields = self._parse_bit_fields(
                    template_reg.get("fields", []), file_path
                )

                registers.append(
                    self._build_register_def(
                        name=reg_name,
                        address_offset=current_offset,
                        size=size,
                        access=template_reg.get("access", "read-write"),
                        description=template_reg.get("description"),
                        reset_value=template_reg.get("resetValue"),
                        fields=fields,
                    )
                )
                current_offset += size // 8

        return registers

    def _parse_bit_fields(
        self, data: List[Dict[str, Any]], file_path: Path
    ) -> List[BitFieldDef]:
        """Parse bit-field definitions from register entries."""
        fields = []
        current_bit = 0

        for idx, field_data in enumerate(data):
            try:
                if "bits" in field_data:
                    bit_offset, bit_width = self._parse_bits_notation(
                        field_data["bits"]
                    )
                else:
                    bit_offset = field_data.get("bitOffset")
                    bit_width = field_data.get("bitWidth", 1)

                if bit_offset is None:
                    bit_offset = current_bit
                if bit_width is None:
                    bit_width = 1

                access_type = self._parse_access(field_data.get("access", "read-write"))

                fields.append(
                    BitFieldDef(
                        **filter_none(
                            {
                                "name": field_data.get("name"),
                                "bit_offset": bit_offset,
                                "bit_width": bit_width,
                                "access": access_type,
                                "description": field_data.get("description"),
                                "reset_value": field_data.get("resetValue")
                                or field_data.get("reset"),
                            }
                        )
                    )
                )
                current_bit = bit_offset + bit_width
            except (KeyError, TypeError, ValueError, ValidationError) as e:
                raise ParseError(f"Error parsing bitField[{idx}]: {e}", file_path)

        return fields

    def _parse_bits_notation(self, bits_str: str) -> tuple[int, int]:
        """Parse ``[msb:lsb]`` bits notation into ``(offset, width)``."""
        try:
            return parse_bit_range(bits_str)
        except ValueError as e:
            raise ValueError(f"Failed to parse bits notation '{bits_str}': {e}")
