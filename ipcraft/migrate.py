"""Legacy-key migration for ``.ip.yml`` / ``.mm.yml`` files.

Mirrors ``ipcraft migrate`` of the ipcraft-vscode CLI: legacy snake_case keys are
renamed to their canonical camelCase spelling on known node shapes only. Edits are
applied at the exact source positions of the key nodes, so comments, key order and
number spellings survive. A legacy key is dropped when its canonical key already
exists on the same mapping.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import yaml

FIELD_KEYS = {
    "bit_offset": "offset",
    "bit_width": "width",
    "bit_range": "bitRange",
    "reset_value": "resetValue",
    "enumerated_values": "enumeratedValues",
    "monitor_change_of": "monitorChangeOf",
}
REGISTER_KEYS = {"address_offset": "offset", "reset_value": "resetValue"}
BLOCK_KEYS = {"base_address": "baseAddress", "default_reg_width": "defaultRegWidth"}
MEMORY_MAP_KEYS = {"address_blocks": "addressBlocks"}
IP_CORE_KEYS = {"memory_maps": "memoryMaps", "file_sets": "fileSets"}
BUS_KEYS = {
    "use_optional_ports": "useOptionalPorts",
    "port_width_overrides": "portWidthOverrides",
    "port_name_overrides": "portNameOverrides",
    "absent_ports": "absentPorts",
    "conduit_ports": "conduitPorts",
    "physical_prefix": "physicalPrefix",
    "associated_clock": "associatedClock",
    "associated_reset": "associatedReset",
}
BUS_ARRAY_KEYS = {
    "index_start": "indexStart",
    "naming_pattern": "namingPattern",
    "physical_prefix_pattern": "physicalPrefixPattern",
}
CLOCK_KEYS = {"associated_reset": "associatedReset"}
RESET_KEYS = {"associated_clock": "associatedClock"}

# (start offset, end offset, replacement) edits; replacement "" drops the pair.
_Edit = Tuple[int, int, Optional[str]]


@dataclass
class MigrationResult:
    text: str
    changed: bool
    mutation_count: int


def _key(pair: Tuple[yaml.Node, yaml.Node]) -> Optional[str]:
    k = pair[0]
    return k.value if isinstance(k, yaml.ScalarNode) else None


def _get(node: yaml.MappingNode, name: str) -> Optional[yaml.Node]:
    for pair in node.value:
        if _key(pair) == name:
            return pair[1]
    return None


def _maps(node: Optional[yaml.Node]):
    if isinstance(node, yaml.SequenceNode):
        for item in node.value:
            if isinstance(item, yaml.MappingNode):
                yield item


class _Renamer:
    def __init__(self, text: str) -> None:
        self.text = text
        self.edits: List[Tuple[yaml.Node, bool]] = []  # (key node, drop?)
        self.pair_drops: List[Tuple[yaml.Node, yaml.Node]] = []
        self.renames: List[yaml.Node] = []  # key nodes to rename
        self.rename_to: Dict[int, str] = {}

    def in_map(self, node: yaml.MappingNode, table: Dict[str, str]) -> int:
        count = 0
        names = {_key(p) for p in node.value}
        for pair in node.value:
            name = _key(pair)
            canonical = table.get(name) if name else None
            if canonical is None:
                continue
            count += 1
            if canonical in names:
                self.pair_drops.append(pair)
            else:
                self.renames.append(pair[0])
                self.rename_to[id(pair[0])] = canonical
        return count

    def register(self, reg: yaml.MappingNode) -> int:
        n = self.in_map(reg, REGISTER_KEYS)
        for f in _maps(_get(reg, "fields")):
            n += self.in_map(f, FIELD_KEYS)
        for r in _maps(_get(reg, "registers")):
            n += self.register(r)
        return n

    def block(self, blk: yaml.MappingNode) -> int:
        n = self.in_map(blk, BLOCK_KEYS)
        for r in _maps(_get(blk, "registers")):
            n += self.register(r)
        return n

    def memory_map(self, mm: yaml.MappingNode) -> int:
        n = self.in_map(mm, MEMORY_MAP_KEYS)
        for b in _maps(_get(mm, "addressBlocks") or _get(mm, "address_blocks")):
            n += self.block(b)
        return n

    def mm_root(self, root: Optional[yaml.Node]) -> int:
        if isinstance(root, yaml.SequenceNode):
            return sum(self.memory_map(m) for m in _maps(root))
        if not isinstance(root, yaml.MappingNode):
            return 0
        wrapped = _get(root, "memory_maps") or _get(root, "memoryMaps")
        if wrapped is None:
            return self.memory_map(root)
        n = self.in_map(root, {"memory_maps": "memoryMaps"})
        return n + sum(self.memory_map(m) for m in _maps(wrapped))

    def bus(self, bus: yaml.MappingNode) -> int:
        n = self.in_map(bus, BUS_KEYS)
        array = _get(bus, "array")
        if isinstance(array, yaml.MappingNode):
            n += self.in_map(array, BUS_ARRAY_KEYS)
        return n

    def ip_root(self, root: Optional[yaml.Node]) -> int:
        if not isinstance(root, yaml.MappingNode):
            return 0
        n = self.in_map(root, IP_CORE_KEYS)
        for b in _maps(_get(root, "busInterfaces")):
            n += self.bus(b)
        for c in _maps(_get(root, "clocks")):
            n += self.in_map(c, CLOCK_KEYS)
        for r in _maps(_get(root, "resets")):
            n += self.in_map(r, RESET_KEYS)
        for m in _maps(_get(root, "memoryMaps") or _get(root, "memory_maps")):
            if _get(m, "import") is None:
                n += self.memory_map(m)
        return n

    def apply(self) -> str:
        offsets = _line_offsets(self.text)

        def pos(mark: yaml.Mark) -> int:
            return offsets[mark.line] + mark.column

        edits: List[_Edit] = []
        for key in self.renames:
            edits.append((pos(key.start_mark), pos(key.end_mark), self.rename_to[id(key)]))
        for k, v in self.pair_drops:
            start = offsets[k.start_mark.line]
            end_line = max(v.end_mark.line, k.start_mark.line)
            # Drop whole lines the pair occupies (block style); flow style is left untouched.
            if v.end_mark.column == 0:
                end = offsets[v.end_mark.line]
            else:
                end = offsets[end_line + 1] if end_line + 1 < len(offsets) else len(self.text)
            edits.append((start, end, ""))
        out = self.text
        for start, end, repl in sorted(edits, key=lambda e: -e[0]):
            out = out[:start] + (repl or "") + out[end:]
        return out


def _line_offsets(text: str) -> List[int]:
    offsets = [0]
    for line in text.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    return offsets


def _migrate(text: str, kind: str) -> MigrationResult:
    try:
        root = yaml.compose(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML: {exc}") from exc
    r = _Renamer(text)
    count = r.mm_root(root) if kind == "memoryMap" else r.ip_root(root)
    if count == 0:
        return MigrationResult(text, False, 0)
    return MigrationResult(r.apply(), True, count)


def migrate_ip_core_yaml(text: str) -> MigrationResult:
    """Convert legacy snake_case keys in an ``.ip.yml`` document."""
    return _migrate(text, "ipCore")


def migrate_memory_map_yaml(text: str) -> MigrationResult:
    """Convert legacy snake_case keys in a ``.mm.yml`` document."""
    return _migrate(text, "memoryMap")
