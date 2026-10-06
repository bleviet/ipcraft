"""AST-based width-expression core (port of ``widthExprAst.ts``).

Parses a port-width expression such as ``AxiDataWidth_g/8`` or ``clog2(DEPTH)`` into a
small AST that can be evaluated numerically or serialized into HDL / tool dialects.
Hand-rolled recursive descent; no ``eval``.

Nodes are plain dicts::

    {"type": "Number", "value": float}
    {"type": "ParamRef", "name": str}
    {"type": "Unary", "op": "-", "operand": node}
    {"type": "Binary", "op": "+-*/", "left": node, "right": node}
    {"type": "Call", "fn": str, "args": [node]}
"""

from __future__ import annotations

import math
import re
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

Node = Dict[str, Any]

FUNCTION_ARITY = {"clog2": 1, "log2": 1, "ceil": 1, "floor": 1, "abs": 1, "min": 2, "max": 2}
VHDL_MATH_REAL_FUNCTIONS = {"clog2", "log2", "ceil", "floor"}
IPXACT_UNSUPPORTED = " IPXACT_UNSUPPORTED"


class _ParseError(Exception):
    pass


def js_number(value: float) -> str:
    """Format a number the way JavaScript's ``String(n)`` does."""
    if isinstance(value, bool):
        return str(int(value))
    if isinstance(value, int):
        return str(value)
    if math.isfinite(value) and value == int(value) and abs(value) < 1e21:
        return str(int(value))
    return repr(value)


def parse(expr: str) -> Optional[Node]:
    """Parse ``expr``; ``None`` on any syntax error, unknown function or wrong arity."""
    src = re.sub(r"\s+", "", expr)
    if not src:
        return None
    pos = 0

    def peek() -> str:
        return src[pos] if pos < len(src) else ""

    def parse_identifier() -> str:
        nonlocal pos
        start = pos
        while pos < len(src) and re.match(r"[A-Za-z0-9_]", src[pos]):
            pos += 1
        return src[start:pos]

    def parse_number() -> Node:
        nonlocal pos
        start = pos
        while pos < len(src) and re.match(r"[0-9.]", src[pos]):
            pos += 1
        try:
            value = float(src[start:pos])
        except ValueError:
            raise _ParseError("invalid number")
        return {"type": "Number", "value": value}

    def parse_primary() -> Node:
        nonlocal pos
        ch = peek()
        if ch == "(":
            pos += 1
            inner = parse_add_sub()
            if peek() != ")":
                raise _ParseError("expected )")
            pos += 1
            return inner
        if ch and "0" <= ch <= "9":
            return parse_number()
        if ch and re.match(r"[A-Za-z_]", ch):
            ident = parse_identifier()
            if peek() == "(":
                fn = ident.lower()
                if fn not in FUNCTION_ARITY:
                    raise _ParseError(f"unknown function {ident}")
                pos += 1
                args: List[Node] = []
                if peek() != ")":
                    args.append(parse_add_sub())
                    while peek() == ",":
                        pos += 1
                        args.append(parse_add_sub())
                if peek() != ")":
                    raise _ParseError("expected ) after arguments")
                pos += 1
                if len(args) != FUNCTION_ARITY[fn]:
                    raise _ParseError(f"{fn} expects {FUNCTION_ARITY[fn]} argument(s)")
                return {"type": "Call", "fn": fn, "args": args}
            return {"type": "ParamRef", "name": ident}
        raise _ParseError(f"unexpected token {ch or '<eof>'}")

    def parse_unary() -> Node:
        nonlocal pos
        if peek() == "-":
            pos += 1
            return {"type": "Unary", "op": "-", "operand": parse_unary()}
        return parse_primary()

    def parse_mul_div() -> Node:
        nonlocal pos
        left = parse_unary()
        while peek() in ("*", "/") and peek():
            op = src[pos]
            pos += 1
            left = {"type": "Binary", "op": op, "left": left, "right": parse_unary()}
        return left

    def parse_add_sub() -> Node:
        nonlocal pos
        left = parse_mul_div()
        while peek() in ("+", "-") and peek():
            op = src[pos]
            pos += 1
            left = {"type": "Binary", "op": op, "left": left, "right": parse_mul_div()}
        return left

    try:
        ast = parse_add_sub()
        if pos != len(src):
            return None
        return ast
    except _ParseError:
        return None


def _js_div(left: float, right: float) -> float:
    if right == 0:
        if left == 0 or math.isnan(left):
            return math.nan
        return math.inf if left > 0 else -math.inf
    return left / right


def _apply_function(fn: str, args: List[float]) -> Optional[float]:
    if fn == "clog2":
        n = args[0]
        if n <= 0:
            return None
        if n <= 1:
            return 0
        return math.ceil(math.log2(n))
    if fn == "log2":
        n = args[0]
        return None if n <= 0 else math.floor(math.log2(n))
    if fn == "ceil":
        return math.ceil(args[0])
    if fn == "floor":
        return math.floor(args[0])
    if fn == "abs":
        return abs(args[0])
    if fn == "min":
        return min(args[0], args[1])
    if fn == "max":
        return max(args[0], args[1])
    return None


def evaluate(ast: Node, param_defaults: Optional[Mapping[str, float]]) -> Optional[float]:
    """Evaluate numerically; ``None`` if a parameter is unresolved or out of domain."""
    defaults = param_defaults or {}

    def visit(node: Node) -> Optional[float]:
        t = node["type"]
        if t == "Number":
            return node["value"]
        if t == "ParamRef":
            v = defaults.get(node["name"])
            return v if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None
        if t == "Unary":
            o = visit(node["operand"])
            return None if o is None else -o
        if t == "Binary":
            left = visit(node["left"])
            right = visit(node["right"])
            if left is None or right is None:
                return None
            op = node["op"]
            if op == "+":
                return left + right
            if op == "-":
                return left - right
            if op == "*":
                return left * right
            return _js_div(left, right)
        if t == "Call":
            args = [visit(a) for a in node["args"]]
            if any(a is None for a in args):
                return None
            return _apply_function(node["fn"], args)  # type: ignore[arg-type]
        return None

    return visit(ast)


def eval_width_expr(expr: str, param_defaults: Optional[Mapping[str, float]]) -> Optional[int]:
    """Integer result of ``expr`` or ``None`` (port of ``evalWidthExpr``)."""
    ast = parse(expr)
    if ast is None:
        return None
    result = evaluate(ast, param_defaults)
    if result is None or not math.isfinite(result):
        return None
    return int(result)  # truncation toward zero, like Math.trunc


def contains_param_ref(ast: Node) -> bool:
    t = ast["type"]
    if t == "ParamRef":
        return True
    if t == "Number":
        return False
    if t == "Unary":
        return contains_param_ref(ast["operand"])
    if t == "Binary":
        return contains_param_ref(ast["left"]) or contains_param_ref(ast["right"])
    return any(contains_param_ref(a) for a in ast["args"])


def contains_call(ast: Node) -> bool:
    t = ast["type"]
    if t == "Call":
        return True
    if t in ("Number", "ParamRef"):
        return False
    if t == "Unary":
        return contains_call(ast["operand"])
    return contains_call(ast["left"]) or contains_call(ast["right"])


def width_expr_uses_math_real(expr: str) -> bool:
    ast = parse(expr)
    if ast is None or not contains_param_ref(ast):
        return False

    def visit(node: Node) -> bool:
        t = node["type"]
        if t == "Call":
            return node["fn"] in VHDL_MATH_REAL_FUNCTIONS or any(visit(a) for a in node["args"])
        if t == "Unary":
            return visit(node["operand"])
        if t == "Binary":
            return visit(node["left"]) or visit(node["right"])
        return False

    return visit(ast)


def serialize(
    ast: Node,
    dialect: str,
    param_ref: Optional[Callable[[str], str]] = None,
) -> Tuple[str, bool]:
    """Serialize to ``canonical|systemverilog|vhdl|tcl|ipxact``; returns ``(code, used_function)``."""
    if not contains_param_ref(ast):
        value = evaluate(ast, {})
        if value is not None and math.isfinite(value):
            return str(int(value)), False

    state = {"used": False, "unsupported": False}

    def precedence(node: Node) -> int:
        if node["type"] == "Binary":
            return 1 if node["op"] in "+-" else 2
        if node["type"] == "Unary":
            return 3
        return 4

    def wrap(child: Node, parent: Node, is_right: bool = False) -> str:
        code = visit(child)
        cp, pp = precedence(child), precedence(parent)
        if cp < pp or (is_right and cp == pp):
            return f"({code})"
        return code

    def visit(node: Node) -> str:
        t = node["type"]
        if t == "Number":
            return js_number(node["value"])
        if t == "ParamRef":
            return param_ref(node["name"]) if param_ref else node["name"]
        if t == "Unary":
            return f"-{wrap(node['operand'], node)}"
        if t == "Binary":
            return f"{wrap(node['left'], node)}{node['op']}{wrap(node['right'], node, True)}"
        state["used"] = True
        a = [visit(x) for x in node["args"]]
        fn = node["fn"]
        if dialect == "canonical":
            return f"{fn}({','.join(a)})"
        if dialect == "systemverilog":
            return _sv_call(fn, a)
        if dialect == "vhdl":
            return _vhdl_call(fn, a)
        if dialect == "tcl":
            return _tcl_call(fn, a)
        result = _ipxact_call(fn, a)
        if result == IPXACT_UNSUPPORTED:
            state["unsupported"] = True
        return result

    code = visit(ast)
    if state["unsupported"]:
        return IPXACT_UNSUPPORTED, state["used"]
    return code, state["used"]


def _sv_call(fn: str, a: List[str]) -> str:
    if fn == "clog2":
        return f"$clog2({a[0]})"
    if fn in ("ceil", "floor"):
        return a[0]
    if fn == "abs":
        return f"(({a[0]}) < 0 ? -({a[0]}) : ({a[0]}))"
    if fn == "min":
        return f"(({a[0]}) < ({a[1]}) ? ({a[0]}) : ({a[1]}))"
    if fn == "max":
        return f"(({a[0]}) > ({a[1]}) ? ({a[0]}) : ({a[1]}))"
    raise ValueError("log2 has no SystemVerilog serialization")


def _vhdl_call(fn: str, a: List[str]) -> str:
    if fn == "clog2":
        return f"integer(ceil(log2(real({a[0]}))))"
    if fn == "log2":
        return f"integer(floor(log2(real({a[0]}))))"
    if fn == "ceil":
        return f"integer(ceil(real({a[0]})))"
    if fn == "floor":
        return f"integer(floor(real({a[0]})))"
    if fn == "abs":
        return f"abs({a[0]})"
    if fn == "min":
        return f"minimum({a[0]}, {a[1]})"
    return f"maximum({a[0]}, {a[1]})"


def _tcl_call(fn: str, a: List[str]) -> str:
    if fn == "clog2":
        return f"int(ceil(log({a[0]})/log(2)))"
    if fn == "log2":
        return f"int(floor(log({a[0]})/log(2)))"
    if fn == "ceil":
        return f"int(ceil({a[0]}))"
    if fn == "floor":
        return f"int(floor({a[0]}))"
    if fn == "abs":
        return f"abs({a[0]})"
    if fn == "min":
        return f"min({a[0]},{a[1]})"
    return f"max({a[0]},{a[1]})"


def _ipxact_call(fn: str, a: List[str]) -> str:
    if fn == "clog2":
        return f"ceiling(log(2, {a[0]}))"
    if fn == "log2":
        return f"floor(log(2, {a[0]}))"
    if fn == "ceil":
        return f"ceiling({a[0]})"
    if fn == "floor":
        return f"floor({a[0]})"
    if fn == "abs":
        return f"abs({a[0]})"
    return IPXACT_UNSUPPORTED


def normalize_function_names(expr: str) -> str:
    def repl(m: "re.Match[str]") -> str:
        lower = m.group(1).lower()
        return f"{lower}{m.group(2)}" if lower in FUNCTION_ARITY else m.group(0)

    return re.sub(r"([A-Za-z_][A-Za-z0-9_]*)(\s*\()", repl, expr)


def strip_redundant_outer_parens(s: str) -> str:
    if not (s.startswith("(") and s.endswith(")")):
        return s
    depth = 0
    for i, ch in enumerate(s):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return s[1:-1].strip() if i == len(s) - 1 else s
    return s


def _unwrap_call(s: str, name: str) -> Optional[str]:
    m = re.match(rf"^{name}\s*\(", s, re.IGNORECASE)
    if not m:
        return None
    open_idx = m.end() - 1
    depth = 0
    for i in range(open_idx, len(s)):
        if s[i] == "(":
            depth += 1
        elif s[i] == ")":
            depth -= 1
            if depth == 0:
                return s[open_idx + 1 : i] if i == len(s) - 1 else None
    return None


def _match_any_call(s: str, names: List[str]) -> Optional[Tuple[str, str]]:
    for name in names:
        inner = _unwrap_call(s, name)
        if inner is not None:
            return name.lower(), inner
    return None


def _split_top_level_args(s: str) -> List[str]:
    parts: List[str] = []
    depth = 0
    current = ""
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += ch
    parts.append(current)
    return [p.strip() for p in parts]


def collapse_vhdl_function_call(text: str) -> Optional[str]:
    s = text.strip()
    outer = _match_any_call(s, ["integer"])
    if outer:
        cf = _match_any_call(outer[1], ["ceil", "floor"])
        if not cf:
            return None
        log2 = _match_any_call(cf[1], ["log2"])
        real = _match_any_call((log2 or cf)[1], ["real"])
        if not real:
            return None
        inner = real[1].strip()
        if parse(inner) is None:
            return None
        if log2:
            return f"clog2({inner})" if cf[0] == "ceil" else f"log2({inner})"
        return f"{cf[0]}({inner})"
    mm = _match_any_call(s, ["minimum", "maximum"])
    if mm:
        args = _split_top_level_args(mm[1])
        if len(args) == 2 and all(parse(a) is not None for a in args):
            return f"{'min' if mm[0] == 'minimum' else 'max'}({args[0]}, {args[1]})"
    return None


def collapse_vhdl_function_calls_in_expr(expr: str) -> str:
    m = re.search(r"\b(integer|minimum|maximum)\s*\(", expr, re.IGNORECASE)
    if not m:
        return expr
    start = m.start()
    open_idx = m.end() - 1
    depth = 0
    close_idx = -1
    for i in range(open_idx, len(expr)):
        if expr[i] == "(":
            depth += 1
        elif expr[i] == ")":
            depth -= 1
            if depth == 0:
                close_idx = i
                break
    if close_idx == -1:
        return expr
    canonical_inner = collapse_vhdl_function_calls_in_expr(expr[open_idx + 1 : close_idx])
    call = f"{expr[start:open_idx + 1]}{canonical_inner})"
    replacement = collapse_vhdl_function_call(call) or call
    after = collapse_vhdl_function_calls_in_expr(expr[close_idx + 1 :])
    return f"{expr[:start]}{replacement}{after}"
