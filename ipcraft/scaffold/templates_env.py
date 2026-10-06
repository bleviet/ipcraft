"""Jinja2 environment emulating the Nunjucks behaviour the scaffold templates rely on.

Differences handled here:

* an empty list / dict is *truthy* in Nunjucks (JavaScript semantics);
* ``null`` renders as an empty string, booleans as ``true`` / ``false``, arrays as
  comma-joined values and whole floats without a fractional part;
* ``array.push(x)`` is available in templates;
* the filters registered by ``TemplateLoader.ts`` (``format``, ``selectattr`` with
  ``equalto``/``in``, ``list``, ``bin``, ``repeat``, ``snakecase``, ...).
"""

from __future__ import annotations

import json
import math
import os
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Union

import jinja2
import jinja2.compiler


class JList(list):
    """A list that is truthy even when empty, like a JavaScript array."""

    __bool__ = lambda self: True  # noqa: E731

    def push(self, item: Any) -> int:  # JavaScript Array.prototype.push
        self.append(item)
        return len(self)


class JDict(dict):
    """A dict that is truthy even when empty, like a JavaScript object."""

    __bool__ = lambda self: True  # noqa: E731


def to_js(value: Any) -> Any:
    """Deep-convert plain containers into JavaScript-like truthy containers."""
    if isinstance(value, dict):
        return JDict({k: to_js(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return JList(to_js(v) for v in value)
    return value


def js_finalize(value: Any) -> Any:
    """Render a value the way Nunjucks does."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if math.isfinite(value) and value == int(value) and abs(value) < 1e21:
            return str(int(value))
        return repr(value)
    if isinstance(value, (list, tuple)):
        return ",".join("" if v is None else str(js_finalize(v)) for v in value)
    if isinstance(value, dict):
        return "[object Object]"
    return value


# ---------------------------------------------------------------------------
# Filters (port of templateFilters.ts and TemplateLoader.ts)
# ---------------------------------------------------------------------------


def _split_words(value: Any) -> List[str]:
    if value is None:
        return []
    text = str(value)
    text = re.sub(r"[-_.\s]+", " ", text)
    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", text)
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    return [w for w in text.split(" ") if w]


def _capitalize(word: str) -> str:
    return word[:1].upper() + word[1:].lower()


def snakecase(value: Any) -> str:
    return "_".join(w.lower() for w in _split_words(value))


def constcase(value: Any) -> str:
    return "_".join(w.upper() for w in _split_words(value))


def camelcase(value: Any) -> str:
    words = _split_words(value)
    if not words:
        return ""
    return "".join([words[0].lower()] + [_capitalize(w) for w in words[1:]])


def pascalcase(value: Any) -> str:
    return "".join(_capitalize(w) for w in _split_words(value))


def log2_filter(value: Any) -> int:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return 0
    if not math.isfinite(n) or n <= 0:
        return 0
    return math.ceil(math.log2(n))


def ljust(value: Any, width: Any, fill_char: Any = " ") -> str:
    s = "" if value is None else str(value)
    try:
        w = max(0, int(float(width if width is not None else 0)))
    except (TypeError, ValueError):
        w = 0
    fill = fill_char if isinstance(fill_char, str) and fill_char else " "
    if len(s) >= w:
        return s
    pad = w - len(s)
    padding = (fill * (-(-pad // len(fill))))[:pad]
    return s + padding


_LATEX = {"\\": "\\textbackslash{}", "&": "\\&", "%": "\\%", "$": "\\$", "#": "\\#", "_": "\\_", "{": "\\{",
          "}": "\\}", "~": "\\textasciitilde{}", "^": "\\textasciicircum{}"}


def latexescape(value: Any) -> str:
    return re.sub(r"[\\&%$#_{}~^]", lambda m: _LATEX[m.group(0)], "" if value is None else str(value))


def format_filter(fmt: Any, value: Any) -> str:
    if not isinstance(fmt, str):
        return "" if value is None else str(value)
    m = re.search(r"%(-)?(0)?(\d+)?([sXx])", fmt)
    if not m:
        return "" if value is None else str(value)
    left = bool(m.group(1))
    zero = bool(m.group(2))
    width = int(m.group(3)) if m.group(3) else 0
    kind = m.group(4)
    if kind == "s":
        rendered = "" if value is None else str(js_finalize(value))
    else:
        try:
            num = float(value if value is not None else 0)
            rendered = format(int(num), "x") if math.isfinite(num) else "0"
        except (TypeError, ValueError):
            rendered = "0"
        if kind == "X":
            rendered = rendered.upper()
    if width > 0 and len(rendered) < width:
        pad_char = "0" if zero and not left else " "
        padding = pad_char * (width - len(rendered))
        rendered = rendered + padding if left else padding + rendered
    return rendered


def selectattr_filter(items: Any, attribute: str, operator: Optional[str] = None, compare: Any = None) -> List[Any]:
    lst = list(items) if isinstance(items, (list, tuple)) else []
    out = []
    for item in lst:
        value = item.get(attribute) if isinstance(item, dict) else None
        if operator == "equalto":
            ok = value == compare
        elif operator == "in":
            ok = isinstance(compare, (list, tuple)) and value in compare
        elif operator is None:
            ok = bool(value)
        else:
            ok = False
        if ok:
            out.append(item)
    return JList(out)


def list_filter(items: Any) -> List[Any]:
    return JList(items) if isinstance(items, (list, tuple)) else JList()


def bin_filter(value: Any, width: Any) -> str:
    try:
        num = float(value if value is not None else 0)
        w = int(float(width if width is not None else 0))
    except (TypeError, ValueError):
        return "0"
    if not math.isfinite(num) or w <= 0:
        return "0"
    b = format(int(num), "b")
    return b[-w:] if len(b) >= w else "0" * (w - len(b)) + b


def repeat_filter(char: Any, count: Any) -> str:
    try:
        n = max(0, int(float(count if count is not None else 0)))
    except (TypeError, ValueError):
        n = 0
    return ("" if char is None else str(char)) * n


def dump_filter(value: Any, spaces: Any = None) -> str:
    return json.dumps(value, separators=(",", ":") if spaces is None else None, indent=spaces, ensure_ascii=False)


def int_filter(value: Any, default: Any = 0) -> Any:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        m = re.match(r"\s*[+-]?\d+", str(value))
        return int(m.group(0)) if m else default


def js_to_string(value: Any) -> str:
    """``String(value)`` semantics used by the ``~`` operator and the ``string`` filter."""
    if isinstance(value, jinja2.Undefined):
        return "undefined"
    if value is None:
        return "null"
    if isinstance(value, (list, tuple)):
        return ",".join("" if (v is None or isinstance(v, jinja2.Undefined)) else js_to_string(v) for v in value)
    result = js_finalize(value)
    return result if isinstance(result, str) else str(result)


class _JsCodeGenerator(jinja2.compiler.CodeGenerator):
    """Compile ``a ~ b`` as JavaScript string concatenation instead of ``str()`` joins."""

    def visit_Concat(self, node, frame):  # noqa: N802 - jinja2 visitor naming
        self.write("environment.js_join((")
        for arg in node.nodes:
            self.visit(arg, frame)
            self.write(", ")
        self.write("))")


def _adapt_source(source: str) -> str:
    """Adapt Nunjucks-only syntax and whitespace rules to Jinja2.

    * ``.push(`` becomes ``.append(``;
    * Nunjucks keeps the newline following a ``{# comment #}`` even with ``trimBlocks``,
      whereas Jinja2 trims it, so the newline is doubled.
    """
    source = source.replace(".push(", ".append(")
    return re.sub(r"#\}(\r?\n)", r"#}\1\1", source)


class _JsEnvironment(jinja2.Environment):
    """Environment whose attribute lookup prefers dict items (``obj[key]``) like JavaScript."""

    code_generator_class = _JsCodeGenerator

    @staticmethod
    def js_join(parts: Any) -> str:
        return "".join(js_to_string(p) for p in parts)

    def getattr(self, obj: Any, attribute: str) -> Any:  # noqa: D102
        if isinstance(obj, dict):
            if attribute in obj:
                return obj[attribute]
            return self.undefined(obj=obj, name=attribute)
        return super().getattr(obj, attribute)


class _SourceLoader(jinja2.FileSystemLoader):
    """File loader that adapts Nunjucks-only syntax (``.push(`` -> ``.append(``)."""

    def get_source(self, environment, template):  # type: ignore[override]
        source, filename, uptodate = super().get_source(environment, template)
        return _adapt_source(source), filename, uptodate


class TemplateLoader:
    """Renders scaffold templates; the Python counterpart of ``TemplateLoader.ts``."""

    def __init__(self, search_paths: Union[str, Sequence[str]]):
        paths = [search_paths] if isinstance(search_paths, str) else list(search_paths)
        self.search_paths = paths
        env = _JsEnvironment(
            loader=_SourceLoader(paths),
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
            finalize=js_finalize,
            undefined=jinja2.ChainableUndefined,
        )
        env.filters.update({
            "format": format_filter,
            "selectattr": selectattr_filter,
            "list": list_filter,
            "bin": bin_filter,
            "repeat": repeat_filter,
            "snakecase": snakecase,
            "constcase": constcase,
            "camelcase": camelcase,
            "pascalcase": pascalcase,
            "log2": log2_filter,
            "ljust": ljust,
            "latexescape": latexescape,
            "dump": dump_filter,
            "int": int_filter,
            "string": js_to_string,
        })
        self.env = env

    def has_template(self, name: str) -> bool:
        return any(os.path.exists(os.path.join(p, name)) for p in self.search_paths)

    def render(self, template_name: str, context: Dict[str, Any]) -> str:
        return self.env.get_template(template_name).render(**context)

    def render_string(self, template: str, context: Dict[str, Any]) -> str:
        return self.env.from_string(_adapt_source(template)).render(**context)

    def evaluate_condition(self, condition: Optional[str], context: Dict[str, Any]) -> bool:
        if not condition:
            return True
        try:
            result = self.env.from_string(f"{{% if {condition} %}}true{{% else %}}false{{% endif %}}").render(**context)
        except Exception:  # noqa: BLE001 - mirrors the TS try/catch: a bad condition is false
            return False
        return result.strip() == "true"
