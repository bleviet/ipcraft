"""Legacy-key migration for ``.ip.yml`` / ``.mm.yml`` files.

Mirrors ``ipcraft migrate`` of the ipcraft-vscode CLI: legacy snake_case keys are
renamed to their canonical camelCase spelling on known node shapes only. Edits are
applied at the exact source positions of the key nodes, so comments, key order and
number spellings survive. A legacy key is dropped when its canonical key already
exists on the same mapping.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

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


IP_CORE_FORMAT_VERSIONS = ["1.0", "1.1"]
IP_CORE_FORMAT_VERSION = "1.1"
IP_CORE_LEGACY_FORMAT_VERSION = "1.0"


@dataclass
class MigrationResult:
    text: str
    changed: bool
    mutation_count: int
    from_version: Optional[str] = None
    to_version: Optional[str] = None


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

    def apply(self, root: yaml.Node) -> str:
        return _edit_lines(self.text, root, {id(k): self.rename_to[id(k)] for k in self.renames}, {},
                           self.pair_drops)


def _edit_lines(text: str, root: yaml.Node, renames: Dict[int, str], replacements: Dict[int, str],
                pair_drops: List[Tuple[yaml.Node, yaml.Node]], touch: Sequence[int] = ()) -> str:
    """Apply key renames, scalar replacements and pair drops at their source positions.

    The TS CLI re-renders each line an edit touches with the ``yaml`` library and keeps every other
    line verbatim (``serializeEdit``). So does this: a touched block-mapping line becomes
    ``key: value #comment`` with single spaces, flow collections padded as ``[ a, b ]`` and
    ``{ k: v }``, and scalars in their source spelling. Multi-line values are edited in place.
    ``touch`` names further nodes whose lines are rebuilt.
    """
    offsets = _line_offsets(text)

    def pos(mark: yaml.Mark) -> int:
        return offsets[mark.line] + mark.column

    # The line owner of a node: its block-mapping pair, or (None, item) for a flow item of a block sequence.
    owners: Dict[int, Optional[Tuple[Optional[yaml.Node], yaml.Node]]] = {}
    nodes: Dict[int, yaml.Node] = {}

    def walk(node: yaml.Node, owner: Optional[Tuple[Optional[yaml.Node], yaml.Node]]) -> None:
        owners[id(node)] = owner
        nodes[id(node)] = node
        if isinstance(node, yaml.MappingNode):
            for k, v in node.value:
                pair_owner = owner if node.flow_style else (k, v)
                owners[id(k)] = pair_owner
                nodes[id(k)] = k
                walk(v, pair_owner if node.flow_style or not isinstance(v, (yaml.MappingNode, yaml.SequenceNode))
                     or v.flow_style else None)
        elif isinstance(node, yaml.SequenceNode):
            for item in node.value:
                flow_item = isinstance(item, (yaml.MappingNode, yaml.SequenceNode)) and item.flow_style
                walk(item, owner if node.flow_style else (None, item) if flow_item else None)

    if root is not None:
        walk(root, None)
    dropped = {id(k) for k, _ in pair_drops}
    hex_fix = collect_hex_spellings(root)

    def render(node: yaml.Node) -> str:
        if isinstance(node, yaml.ScalarNode):
            if id(node) in replacements:
                return replacements[id(node)]
            if node.style is None and _HEX_RE.match(node.value):
                return f"0x{int(node.value, 16):x}"  # re-spelled by restore_hex_spellings below
            return text[pos(node.start_mark):pos(node.end_mark)]
        if isinstance(node, yaml.SequenceNode):
            items = [render(i) for i in node.value]
            return f"[ {', '.join(items)} ]" if items else "[]"
        pairs = [f"{renames.get(id(k), render(k))}: {render(v)}" for k, v in node.value if id(k) not in dropped]
        return f"{{ {', '.join(pairs)} }}" if pairs else "{}"

    def line_end(at: int) -> int:
        end = text.find("\n", at)
        end = len(text) if end < 0 else end
        return end - 1 if text[end - 1:end] == "\r" else end

    def trailing_comment(start: int, end: int) -> Optional[str]:
        m = re.fullmatch(r"[ \t]*(#.*?)?[ \t]*", text[start:end])
        return None if m is None else (f" {m.group(1)}" if m.group(1) else "")

    edits: List[_Edit] = []
    rebuilt = set()
    # A dropped pair inside a flow collection is rebuilt with its line; block pairs drop whole lines.
    flow_drops = [id(k) for k, _ in pair_drops if owners.get(id(k)) is not None and owners[id(k)][0] is not k]
    for node_id in list(renames) + list(replacements) + flow_drops + list(touch):
        owner = owners.get(node_id)
        if owner is None or id(owner[1]) in rebuilt:
            continue
        k, v = owner
        if k is None:
            start, end = pos(v.start_mark), line_end(pos(v.start_mark))
            comment = trailing_comment(pos(v.end_mark), end) if v.end_mark.line == v.start_mark.line else None
            if comment is not None:
                edits.append((start, end, restore_hex_spellings(f"{render(v)}{comment}", hex_fix)))
                rebuilt.add(id(v))
            continue
        k_line = k.start_mark.line
        start, end = pos(k.start_mark), line_end(pos(k.start_mark))
        key_text = renames.get(id(k), text[start:pos(k.end_mark)])
        colon = re.match(r"[ \t]*:", text[pos(k.end_mark):end])
        if colon is None or k.end_mark.line != k_line:
            continue
        after_colon = pos(k.end_mark) + colon.end()
        if v.start_mark.line > k_line or (isinstance(v, yaml.ScalarNode) and v.value == "" and v.style is None):
            comment = trailing_comment(after_colon, end)
            if comment is not None:
                edits.append((start, end, restore_hex_spellings(f"{key_text}:{comment}", hex_fix)))
                rebuilt.add(id(v))
            continue
        if v.end_mark.line != k_line or (isinstance(v, yaml.ScalarNode) and v.style in ("|", ">")):
            continue
        comment = trailing_comment(pos(v.end_mark), end)
        if comment is not None:
            edits.append((start, end, restore_hex_spellings(f"{key_text}: {render(v)}{comment}", hex_fix)))
            rebuilt.add(id(v))
    # Whatever could not be rebuilt as a line is edited in place.
    covered = [(s, e) for s, e, _ in edits]

    def inside(node: yaml.Node) -> bool:
        p = pos(node.start_mark)
        return any(s <= p < e for s, e in covered)

    for node_id, repl in list(renames.items()) + list(replacements.items()):
        node = nodes.get(node_id)
        if node is not None and not inside(node):
            edits.append((pos(node.start_mark), pos(node.end_mark), repl))
    for k, v in pair_drops:
        if inside(k):
            continue
        start = offsets[k.start_mark.line]
        end_line = max(v.end_mark.line, k.start_mark.line)
        # Drop whole lines the pair occupies (block style); flow style is left untouched.
        if v.end_mark.column == 0:
            end = offsets[v.end_mark.line]
        else:
            end = offsets[end_line + 1] if end_line + 1 < len(offsets) else len(text)
        edits.append((start, end, ""))
    out = text
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
    return MigrationResult(r.apply(root), True, count)


def detect_indent_seq(text: str) -> bool:
    """Whether sequence items are indented relative to their parent key (port of ``detectIndentSeq``)."""
    m = re.search(r"^([ \t]*)(?![#\s-])[^\n]*:[ \t]*\n(?:[ \t]*(?:#[^\n]*)?\n)*([ \t]*)- ", text, re.MULTILINE)
    return len(m.group(2)) > len(m.group(1)) if m else True


def _round_trip_yaml(text: str):
    from ruamel.yaml import YAML

    y = YAML(typ="rt")
    y.preserve_quotes = True
    y.width = 4096
    if detect_indent_seq(text):
        y.indent(mapping=2, sequence=4, offset=2)
    else:
        y.indent(mapping=2, sequence=2, offset=0)
    return y


def _to_ruamel(value: Any) -> Any:
    from ruamel.yaml.comments import CommentedMap, CommentedSeq

    if isinstance(value, dict):
        m = CommentedMap()
        for k, v in value.items():
            m[k] = _to_ruamel(v)
        return m
    if isinstance(value, (list, tuple)):
        sq = CommentedSeq()
        for v in value:
            sq.append(_to_ruamel(v))
        return sq
    return value


# libyaml where available, for parses that do not need source positions.
_FastLoader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)

_HEX_RE = re.compile(r"^0x[0-9a-fA-F]+$")


def collect_hex_spellings(root: Optional[yaml.Node]) -> Dict[str, str]:
    """Rendered hex (``0x<lowercase>``) -> source spelling; the last spelling of a value wins (``collectHexSpellings``)."""
    out: Dict[str, str] = {}

    def walk(node: Optional[yaml.Node]) -> None:
        if isinstance(node, yaml.ScalarNode):
            if node.style is None and _HEX_RE.match(node.value):
                out[f"0x{int(node.value, 16):x}"] = node.value
        elif isinstance(node, yaml.MappingNode):
            for k, v in node.value:
                walk(k)
                walk(v)
        elif isinstance(node, yaml.SequenceNode):
            for item in node.value:
                walk(item)

    walk(root)
    return out


def restore_hex_spellings(text: str, hex_fix: Dict[str, str]) -> str:
    for rendered, source in hex_fix.items():
        if rendered != source:
            text = re.sub(rf"\b{rendered}\b", source.replace("\\", "\\\\"), text)
    return text


def _js_json(value: Any) -> str:
    import json

    return json.dumps(_plain(value), separators=(",", ":"), ensure_ascii=False, default=str)


def _plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return int(value) if value == int(value) and abs(value) < 2 ** 53 else float(value)
    if isinstance(value, str):
        return str(value)
    return value


def _same_json(a: Any, b: Any) -> bool:
    return _js_json(a) == _js_json(b)


def _merge_node(current: Any, value: Any) -> Any:
    """Merge a plain value into a ruamel node, reusing matching nodes (port of ``mergeNode``)."""
    from ruamel.yaml.comments import CommentedMap, CommentedSeq
    from ruamel.yaml.scalarstring import ScalarString

    if _same_json(current, value):
        return current
    if isinstance(current, ScalarString) and isinstance(value, str):
        return type(current)(value)  # keep the quoting style
    if isinstance(value, list) and isinstance(current, CommentedSeq):
        used: set = set()
        items = []
        for v in value:
            match = next((i for i, item in enumerate(current) if i not in used and _same_json(item, v)), None)
            if match is not None:
                used.add(match)
                items.append(current[match])
                continue
            if isinstance(v, dict) and isinstance(v.get("name"), str):
                match = next((i for i, item in enumerate(current)
                              if i not in used and isinstance(item, dict) and item.get("name") == v["name"]), None)
                if match is not None:
                    used.add(match)
                    items.append(_merge_node(current[match], v))
                    continue
            items.append(_to_ruamel(v))
        # Comments follow reused items; new items start without (like fresh `yaml` nodes).
        old_ca = {id(current[i]): current.ca.items.get(i) for i in range(len(current))}
        current[:] = items
        current.ca.items.clear()
        for i, item in enumerate(items):
            if old_ca.get(id(item)):
                current.ca.items[i] = old_ca[id(item)]
        return current
    if isinstance(value, dict) and isinstance(current, CommentedMap):
        # ruamel attaches blank lines/comments after a mapping to its last key; the TS `yaml` library
        # attaches them to the next node, so they survive replacing that key. Carry them over.
        old_last = next(reversed(current), None) if current else None
        trailing = _split_trailing(current.ca.items.get(old_last)) if old_last is not None else None
        for k, v in value.items():
            if v is None and k not in current:
                continue
            if k not in current or not _same_json(current[k], v):
                current[k] = _merge_node(current.get(k), v)
        for k in [k for k in current if k not in value]:
            del current[k]
            current.ca.items.pop(k, None)
        new_last = next(reversed(current), None) if current else None
        if trailing and new_last is not None and new_last != old_last:
            if old_last in current.ca.items:
                current.ca.items[old_last][2] = trailing[0]
            current.ca.items.setdefault(new_last, [None, None, None, None])
            eol = current.ca.items[new_last][2]
            current.ca.items[new_last][2] = _join_trailing(eol, trailing[1])
        return current
    return _to_ruamel(value)


def _split_trailing(tokens: Any) -> Optional[Tuple[Any, Any]]:
    """Split a key's post-value token into (its end-of-line comment, the blank/comment lines after it)."""
    from ruamel.yaml.error import CommentMark
    from ruamel.yaml.tokens import CommentToken

    tok = tokens[2] if tokens and len(tokens) > 2 else None
    if not isinstance(tok, CommentToken) or "\n" not in tok.value:
        return None
    first, _, rest = tok.value.partition("\n")
    if not rest:
        return None
    eol = CommentToken(first + "\n", CommentMark(tok.column)) if first else None
    return eol, rest


def _join_trailing(eol: Any, rest: str) -> Any:
    from ruamel.yaml.error import CommentMark
    from ruamel.yaml.tokens import CommentToken

    if eol is None:
        return CommentToken("\n" + rest, CommentMark(0))
    return CommentToken(eol.value + rest, CommentMark(eol.column))


def _hunks(a: List[str], b: List[str]) -> List[Tuple[int, int, List[str]]]:
    """Line hunks turning ``a`` into ``b`` as replacements of ``a[start:end]``."""
    import difflib

    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag != "equal":
            out.append((i1, i2, b[j1:j2]))
    return out


_RESYNC_WINDOW = 64


def _reformat_hunks(a: List[str], b: List[str]) -> List[Tuple[int, int, List[str]]]:
    """Near-linear alignment of the baseline against the original text (port of ``reformatHunks``)."""
    out = []
    i = j = 0
    while i < len(a) and j < len(b):
        if a[i] == b[j]:
            i += 1
            j += 1
            continue
        found = None
        for k in range(1, 2 * _RESYNC_WINDOW + 1):
            for di in range(max(0, k - _RESYNC_WINDOW), min(k, _RESYNC_WINDOW) + 1):
                dj = k - di
                if (i + di < len(a) and j + dj < len(b) and a[i + di] == b[j + dj]
                        and (a[i + di].strip() != ""
                             or (a[i + di + 1] if i + di + 1 < len(a) else None)
                             == (b[j + dj + 1] if j + dj + 1 < len(b) else None))):
                    found = (di, dj)
                    break
            if found:
                break
        if not found:
            break
        out.append((i, i + found[0], b[j:j + found[1]]))
        i += found[0]
        j += found[1]
    if i < len(a) or j < len(b):
        out.append((i, len(a), b[j:]))
    return out


def serialize_edit(text: str, baseline: str, edited: str) -> str:
    """Three-way line merge of an edit (port of ``serializeEdit``).

    ``baseline`` and ``edited`` are renders of the unedited and the edited document. Regions where
    the original ``text`` differs from the baseline are formatting only and keep the original lines
    unless an edit touches them; if the merge does not load to the edited data, ``edited`` wins.
    """
    if baseline == text:
        return edited
    base_lines = baseline.split("\n")
    edits = _hunks(base_lines, edited.split("\n"))
    kept = [r for r in _reformat_hunks(base_lines, text.split("\n"))
            if not any(e[0] < r[1] and e[1] > r[0] for e in edits)]
    merged: List[str] = []
    pos = 0
    for start, end, lines in sorted(kept + edits, key=lambda h: (h[0], h[1])):
        merged.extend(base_lines[pos:start])
        merged.extend(lines)
        pos = max(pos, end)
    merged.extend(base_lines[pos:])
    result = "\n".join(merged)
    if edited.endswith("\n") and not result.endswith("\n"):
        result += "\n"
    try:
        same = _same_json(yaml.load(result, Loader=_FastLoader), yaml.load(edited, Loader=_FastLoader))
    except yaml.YAMLError:
        same = False
    return result if same else edited


def _render(y: Any, doc: Any, hex_fix: Dict[str, str]) -> str:
    """Dump like the TS ``yaml`` render: hex scalars as ``0x<lowercase>``, then the last-seen spellings restored."""
    from ruamel.yaml.comments import CommentedMap, CommentedSeq
    from ruamel.yaml.scalarint import HexInt

    def canon(node: Any) -> None:
        items = node.items() if isinstance(node, CommentedMap) else enumerate(node) if isinstance(node, CommentedSeq) else []
        for k, v in list(items):
            if isinstance(v, HexInt):
                node[k] = HexInt(int(v))
            else:
                canon(v)

    canon(doc)
    _place_comments_like_yaml_lib(doc, 0, detect_indent_seq_of(y))
    out = io.StringIO()
    y.dump(doc, out)
    return _pad_flow_collections(restore_hex_spellings(out.getvalue(), hex_fix))


def detect_indent_seq_of(y: Any) -> bool:
    return bool(y.sequence_dash_offset)


def _place_comments_like_yaml_lib(node: Any, indent: int, indent_seq: bool) -> None:
    """Put comments where the TS ``yaml`` library renders them.

    End-of-line comments get a single space (``value # c``); a comment on the line of a key
    whose value is a block mapping or sequence moves to its own line at the top of that block.
    """
    from ruamel.yaml.comments import CommentedMap, CommentedSeq
    from ruamel.yaml.error import CommentMark
    from ruamel.yaml.tokens import CommentToken

    if not isinstance(node, (CommentedMap, CommentedSeq)):
        return
    for tokens in node.ca.items.values():
        for tok in tokens:
            for t in tok if isinstance(tok, list) else [tok]:
                if isinstance(t, CommentToken) and t.value.startswith("#"):
                    t.column = 0
    if isinstance(node, CommentedSeq):
        for item in node:
            _place_comments_like_yaml_lib(item, indent + 2, indent_seq)
        return
    for k, v in node.items():
        if not isinstance(v, (CommentedMap, CommentedSeq)) or v.fa.flow_style() or not len(v):
            continue
        child = indent + 2 if isinstance(v, CommentedMap) or indent_seq else indent
        tokens = node.ca.items.get(k)
        tok = tokens[2] if tokens and len(tokens) > 2 else None
        if isinstance(tok, CommentToken) and tok.value.startswith("#"):
            first, _, rest = tok.value.partition("\n")
            tokens[2] = CommentToken(f"\n{' ' * child}{first}\n{rest}", CommentMark(0))
            if v.ca.comment:
                v.ca.comment[0] = None
        _place_comments_like_yaml_lib(v, child, indent_seq)


def _pad_flow_collections(text: str) -> str:
    """Re-render single-line flow collections the way the TS ``yaml`` library does (``[ a ]``, ``{ k: v }``)."""
    root = yaml.compose(text)
    flows: List[int] = []

    def walk(node: Optional[yaml.Node]) -> None:
        if isinstance(node, (yaml.MappingNode, yaml.SequenceNode)) and node.flow_style:
            flows.append(id(node))
            return
        if isinstance(node, yaml.MappingNode):
            for _k, v in node.value:
                walk(v)
        elif isinstance(node, yaml.SequenceNode):
            for item in node.value:
                walk(item)

    walk(root)
    return _edit_lines(text, root, {}, {}, [], flows) if flows else text


def _edit_document(text: str, edit) -> str:
    """Apply ``edit(doc)`` (returns whether it changed anything) as a format-preserving edit."""
    y = _round_trip_yaml(text)
    doc = y.load(text)
    if not hasattr(doc, "items"):
        raise ValueError("Invalid YAML: must be an object")
    hex_fix = collect_hex_spellings(yaml.compose(text, Loader=_FastLoader))
    baseline = _render(y, doc, hex_fix)  # rendering only normalizes, so the same doc is edited next
    if not edit(doc):
        return text
    return serialize_edit(text, baseline, _render(y, doc, hex_fix))


def _apply_mutation(text: str, path: list, value: Any) -> str:
    """Set (or with ``value is None`` delete) ``path`` (port of ``applyYamlMutation``)."""

    def edit(doc: Any) -> bool:
        node = doc
        for part in path[:-1]:
            try:
                node = node[part]
            except (KeyError, IndexError, TypeError):
                return False
        key = path[-1]
        if value is None:
            if isinstance(node, dict) and key in node:
                del node[key]
                return True
            return False
        current = node.get(key) if isinstance(node, dict) else None
        if _same_json(current, value):
            return False
        node[key] = _merge_node(current, value)
        return True

    return _edit_document(text, edit)


def _stamp_api_version(text: str, version: str) -> str:
    """Set ``apiVersion`` in place, or insert it single-quoted right after ``vlnv``."""
    from ruamel.yaml.scalarstring import ScalarString, SingleQuotedScalarString

    def edit(doc: Any) -> bool:
        if "apiVersion" in doc:
            existing = doc["apiVersion"]
            doc["apiVersion"] = type(existing)(version) if isinstance(existing, ScalarString) else version
        else:
            keys = list(doc.keys())
            doc.insert(keys.index("vlnv") + 1 if "vlnv" in keys else 0, "apiVersion",
                       SingleQuotedScalarString(version))
        return True

    return _edit_document(text, edit)


def _apply_mutations(text: str, mutations: List[Tuple[list, Any]], stamp_version: str) -> str:
    """Apply ``(path, value)`` edits (``value is None`` deletes) and stamp ``apiVersion`` after ``vlnv``."""
    for path, value in mutations:
        text = _apply_mutation(text, path, value)
    return _stamp_api_version(text, stamp_version)


def _read_version(data: dict) -> str:
    declared = data.get("apiVersion")
    if declared is None:
        return IP_CORE_LEGACY_FORMAT_VERSION
    if declared in IP_CORE_FORMAT_VERSIONS:
        return declared
    if not isinstance(declared, str):
        raise ValueError(f"apiVersion must be a quoted string such as '{IP_CORE_FORMAT_VERSION}' (found {int(declared) if isinstance(declared, float) and declared == int(declared) else declared!r}).")
    raise ValueError(f"This file declares apiVersion {declared}, but this IPCraft supports up to "
                     f"{IP_CORE_FORMAT_VERSION}. Upgrade IPCraft to open it.")


def _bus_list(data: dict) -> List[Tuple[int, dict]]:
    buses = data.get("busInterfaces")
    if not isinstance(buses, list):
        return []
    return [(i, b) for i, b in enumerate(buses) if isinstance(b, dict)]


def dotted_bus_type_mutations(data: dict, library: dict) -> List[Tuple[list, Any]]:
    """Type rewrites for bus interfaces spelled with a dotted VLNV that resolves to a contract."""
    from .scaffold.buscontracts import canonicalize_bus_type, canonicalize_dotted_bus_type

    mutations: List[Tuple[list, Any]] = []
    for index, bus in _bus_list(data):
        if canonicalize_bus_type(bus.get("type"), library):
            continue
        match = canonicalize_dotted_bus_type(bus.get("type"), library)
        if match:
            mutations.append((["busInterfaces", index, "type"], match["canonicalVlnv"]))
    return mutations


def dangling_memory_map_ref_mutations(data: dict, library: dict,
                                      memory_map_names: Sequence[str]) -> List[Tuple[list, Any]]:
    """Repoint a dangling ``memoryMapRef`` at the only defined memory map.

    Unambiguous only when exactly one map exists and exactly one bus interface names a missing map
    and is a memory-mapped slave.
    """
    from .scaffold.buscontracts import canonicalize_bus_type, is_memory_mapped_consumer

    if len(memory_map_names) != 1:
        return []
    dangling = [(i, b) for i, b in _bus_list(data)
                if isinstance(b.get("memoryMapRef"), str) and b["memoryMapRef"] not in memory_map_names]
    if len(dangling) != 1:
        return []
    index, bus = dangling[0]
    match = canonicalize_bus_type(bus.get("type"), library)
    if not match or not is_memory_mapped_consumer(match["contract"], bus.get("mode")):
        return []
    return [(["busInterfaces", index, "memoryMapRef"], memory_map_names[0])]


def _render_scalar(node: yaml.ScalarNode, value: str) -> str:
    if node.style == "'":
        return "'" + value.replace("'", "''") + "'"
    if node.style == '"' or not value or value != value.strip() or re.search(r":\s|\s#|^[-?:,\[\]{}#&*!|>'\"%@`]", value):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


def _replace_scalars(text: str, mutations: List[Tuple[list, str]]) -> str:
    """Replace existing scalar values at ``path``, keeping their quoting; see ``_edit_lines``."""
    root = yaml.compose(text)
    replacements: Dict[int, str] = {}
    for path, value in mutations:
        node: Optional[yaml.Node] = root
        for part in path:
            if isinstance(part, int) and isinstance(node, yaml.SequenceNode) and part < len(node.value):
                node = node.value[part]
            elif isinstance(part, str) and isinstance(node, yaml.MappingNode):
                node = _get(node, part)
            else:
                node = None
            if node is None:
                break
        if isinstance(node, yaml.ScalarNode) and node.value != value:
            replacements[id(node)] = _render_scalar(node, value)
    return _edit_lines(text, root, {}, replacements, []) if replacements else text


def migrate_ip_core_yaml(text: str, library: Optional[dict] = None,
                         memory_map_names: Optional[Sequence[str]] = None) -> MigrationResult:
    """Convert legacy snake_case keys; with a bus ``library`` also upgrade to the latest format version.

    With a ``library``, dotted bus types (``ipcraft.busif.axi4_lite.1.0``) are rewritten to their
    canonical colon VLNV at any version, and when ``memory_map_names`` is given a single dangling
    ``memoryMapRef`` is repointed at the only defined map. The upgrade (``apiVersion`` 1.0 -> 1.1)
    canonicalizes every bus interface against its bus contract (e.g. Avalon-MM ``*_n`` ports become
    ``portPolarityOverrides``) and stamps ``apiVersion``.
    """
    renamed = _migrate(text, "ipCore")
    if library is None:
        return renamed
    try:
        parsed = yaml.safe_load(renamed.text)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Invalid YAML: must be an object")
    normalized_text = renamed.text
    dotted = dotted_bus_type_mutations(parsed, library)
    if dotted:
        normalized_text = _replace_scalars(normalized_text, dotted)
        parsed = yaml.safe_load(normalized_text)
    repair = dangling_memory_map_ref_mutations(parsed, library, memory_map_names) if memory_map_names is not None else []
    if repair:
        normalized_text = _replace_scalars(normalized_text, repair)
        parsed = yaml.safe_load(normalized_text)
    normalized_count = renamed.mutation_count + len(dotted) + len(repair)

    from_version = _read_version(parsed)
    if from_version == IP_CORE_FORMAT_VERSION:
        return MigrationResult(normalized_text, normalized_count > 0, normalized_count, from_version, from_version)

    from .scaffold.buscontracts import canonicalize_bus_interface_ports, canonicalize_bus_type

    mutations: List[Tuple[list, Any]] = []
    for index, bus in enumerate(parsed.get("busInterfaces") or []):
        if not isinstance(bus, dict):
            continue
        match = canonicalize_bus_type(str(bus.get("type") or ""), library)
        if not match:
            continue
        mutations.extend(canonicalize_bus_interface_ports(match["contract"], bus, index)["mutations"])
    new_text = _apply_mutations(normalized_text, mutations, IP_CORE_FORMAT_VERSION)
    return MigrationResult(new_text, True, normalized_count + len(mutations) + 1, from_version, IP_CORE_FORMAT_VERSION)


def migrate_vendor_to_targets(text: str) -> Tuple[bool, str, List[str]]:
    """Rewrite the legacy ``vendor: altera|xilinx|both|none`` field to ``targets: [...]``."""
    try:
        doc_data = yaml.safe_load(text)
    except yaml.YAMLError:
        return False, text, ["parse error — skipped"]
    if not isinstance(doc_data, dict) or "vendor" not in doc_data or doc_data["vendor"] is None:
        return False, text, []
    vendor = str(doc_data["vendor"])
    targets = {"altera": ["quartus"], "xilinx": ["vivado"], "both": ["vivado", "quartus"]}.get(vendor, [])
    y = _round_trip_yaml(text)
    doc = y.load(text)
    del doc["vendor"]
    doc["targets"] = _to_ruamel(targets)
    out = io.StringIO()
    y.dump(doc, out)
    note = f"vendor: '{vendor}' → targets: [{', '.join(repr(t) for t in targets)}]"
    return True, out.getvalue(), [note]


def migrate_memory_map_yaml(text: str) -> MigrationResult:
    """Convert legacy snake_case keys in a ``.mm.yml`` document."""
    return _migrate(text, "memoryMap")
