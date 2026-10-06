"""Small helpers that reproduce JavaScript semantics the ported code relies on."""

from __future__ import annotations

import math
import re
from typing import Any, Optional

import yaml


def js_number(s: str) -> Optional[float]:
    """``Number(s)`` for a string; ``None`` when the result is ``NaN``."""
    s = s.strip()
    if s == "":
        return 0
    try:
        if re.match(r"^[+-]?0[xX][0-9a-fA-F]+$", s) and not re.match(r"^[+-]", s):
            return int(s, 16)
        if re.match(r"^0[bB][01]+$", s):
            return int(s, 2)
        if re.match(r"^0[oO][0-7]+$", s):
            return int(s, 8)
        if not re.match(r"^[+-]?(\d+\.?\d*([eE][+-]?\d+)?|\.\d+([eE][+-]?\d+)?|Infinity)$", s):
            return None
        v = float(s.replace("Infinity", "inf"))
        return int(v) if math.isfinite(v) and v == int(v) and abs(v) < 2**53 else v
    except ValueError:
        return None


def js_finite_number(s: str) -> Optional[float]:
    n = js_number(s)
    return n if n is not None and math.isfinite(n) else None


def js_to_string(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and math.isfinite(v) and v == int(v):
        return str(int(v))
    return str(v)


def _fold_line(line: str, width: int) -> str:
    """Port of js-yaml's ``foldLine`` (breaks a long line at spaces)."""
    if line == "" or line[0] == " ":
        return line
    start = curr = nxt = 0
    result = ""
    for m in re.finditer(r" [^ ]", line):
        nxt = m.start()
        if nxt - start > width:
            end = curr if curr > start else nxt
            result += "\n" + line[start:end]
            start = end + 1
        curr = nxt
    result += "\n"
    if len(line) - start > width and curr > start:
        result += line[start:curr] + "\n" + line[curr + 1:]
    else:
        result += line[start:]
    return result[1:]


def _fold_string(string: str, width: int) -> str:
    """Port of js-yaml's ``foldString``."""
    line_re = re.compile(r"(\n+)([^\n]*)")
    next_lf = string.find("\n")
    next_lf = next_lf if next_lf != -1 else len(string)
    result = _fold_line(string[:next_lf], width)
    prev_more_indented = string[:1] in ("\n", " ")
    for m in line_re.finditer(string, next_lf):
        prefix, line = m.group(1), m.group(2)
        more_indented = line[:1] == " "
        result += ("\n" if not prev_more_indented and not more_indented and line != "" else "") + prefix
        result += _fold_line(line, width)
        prev_more_indented = more_indented
    return result


class _FoldingEmitterMixin:
    """Emit long single-line strings as js-yaml would: a folded block scalar (``>-``)."""

    js_line_width = -1

    def _js_width(self) -> int:
        # js-yaml: lineWidth = max(min(lineWidth, 40), lineWidth - indent * level)
        return max(min(self.js_line_width, 40), self.js_line_width - max(self.indent, 2))

    def _is_foldable(self, text: str) -> bool:
        if self.js_line_width == -1 or self.simple_key_context or not text:
            return False
        width = self._js_width()
        prev = -1
        foldable = False
        for i, ch in enumerate(text):
            if ch == "\n":
                foldable = foldable or (i - prev - 1 > width and text[prev + 1:prev + 2] != " ")
                prev = i
        foldable = foldable or (len(text) - prev - 1 > width and text[prev + 1:prev + 2] != " ")
        return foldable

    def choose_scalar_style(self):  # noqa: D102
        ev = self.event
        value = ev.value
        if ev.style is None and ev.implicit[0] and isinstance(value, str) and not self.simple_key_context:
            if "\r" not in value and "\t" not in value and value[:1] not in (" ", "\n") and value[-1:] != " ":
                if self._is_foldable(value):
                    return ">"
                if "\n" in value:
                    return "|"
        return super().choose_scalar_style()

    def write_folded(self, text):  # noqa: D102
        clip = text.endswith("\n")
        keep = clip and (text[-2:-1] == "\n" or text == "\n")
        chomp = "+" if keep else ("" if clip else "-")
        self.write_indicator(">" + chomp, True)
        if chomp == "+":
            self.open_ended = True
        self.write_line_break()
        folded = _fold_string(text, self._js_width())
        for line in folded.rstrip("\n").split("\n") if folded != "" else []:
            if line:
                self.write_indent()
                self.write_indicator(line, False, whitespace=True) if False else self._write_raw(line)
            self.write_line_break()
        self.whitespace = True

    def _write_raw(self, line: str) -> None:
        self.stream.write(line)
        self.column += len(line)


class _Plain(str):
    """Marker for strings that must never be folded."""


class _JsYamlDumper(_FoldingEmitterMixin, yaml.SafeDumper):
    """PyYAML dumper that approximates js-yaml's block style (indented sequences, no folding)."""

    def increase_indent(self, flow: bool = False, indentless: bool = False):  # noqa: D102
        return super().increase_indent(flow, False)

    def ignore_aliases(self, data: Any) -> bool:  # noqa: D102
        return True


# js-yaml decides whether to quote a string by testing it against its implicit-type resolvers (core
# schema regexes, not PyYAML's YAML 1.1 ones) and additionally quotes the YAML 1.1 booleans y/Y/n/N.
_JS_INT = re.compile(r"^(?:[-+]?[0-9]+|0b[01]+|0o[0-7]+|0x[0-9a-fA-F]+|[-+]?[1-9][0-9]*(?::[0-5]?[0-9])+)$")
_JS_FLOAT = re.compile(r"^(?:[-+]?(?:\.[0-9]+|[0-9]+(?:\.[0-9]*)?)(?:[eE][-+]?[0-9]+)?|[-+]?\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN))$")
_JS_BOOL = re.compile(r"^(?:yes|Yes|YES|no|No|NO|true|True|TRUE|false|False|FALSE|on|On|ON|off|Off|OFF|y|Y|n|N)$")


def _rebuild_resolvers() -> None:
    implicit: dict = {}
    for first, entries in yaml.SafeDumper.yaml_implicit_resolvers.items():
        for tag, regexp in entries:
            if tag in ("tag:yaml.org,2002:int", "tag:yaml.org,2002:float", "tag:yaml.org,2002:bool"):
                continue
            implicit.setdefault(first, []).append((tag, regexp))
    for first in list("-+0123456789."):
        implicit.setdefault(first, []).append(("tag:yaml.org,2002:int", _JS_INT))
        implicit.setdefault(first, []).append(("tag:yaml.org,2002:float", _JS_FLOAT))
    for first in list("yYnNtTfFoO"):
        implicit.setdefault(first, []).append(("tag:yaml.org,2002:bool", _JS_BOOL))
    _JsYamlDumper.yaml_implicit_resolvers = implicit


_rebuild_resolvers()


def _represent_none(dumper: yaml.SafeDumper, _data: None):
    return dumper.represent_scalar("tag:yaml.org,2002:null", "null")


def _represent_str(dumper: yaml.SafeDumper, data: str):
    if data == "--":
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="'")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


_JsYamlDumper.add_representer(type(None), _represent_none)
_JsYamlDumper.add_representer(str, _represent_str)


def js_yaml_dump(data: Any, line_width: int = -1) -> str:
    """Serialize like ``js-yaml``'s ``dump(data, {noRefs: true, sortKeys: false, lineWidth, indent: 2})``."""
    class _D(_JsYamlDumper):
        js_line_width = line_width

    return yaml.dump(data, Dumper=_D, sort_keys=False, width=2**31 - 1, indent=2,
                     allow_unicode=True, default_flow_style=False)


def js_parse_int(s: Any, radix: int = 10) -> Optional[int]:
    """``parseInt(s, radix)`` — leading-integer prefix; ``None`` for ``NaN``."""
    text = str(s).strip()
    if radix == 16:
        m = re.match(r"^[+-]?(?:0[xX])?([0-9a-fA-F]+)", text)
        if not m:
            return None
        v = int(m.group(1), 16)
        return -v if text.startswith("-") else v
    m = re.match(r"^[+-]?\d+", text)
    return int(m.group(0)) if m else None
