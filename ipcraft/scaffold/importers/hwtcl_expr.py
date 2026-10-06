"""Pure helpers for the ``_hw.tcl`` importer: the Tcl word tokenizer and the small ``expr`` subset
that appears in port widths and loop bounds (ports of ``hwTclTokens.ts`` and ``hwTclExpr.ts``)."""

from __future__ import annotations

import math
import re
from typing import Any, Callable, Dict, List, Mapping, Optional, Set, Tuple, Union

from ..jsutil import js_number

TCL_SYNTAX = re.compile(r"[$\[\]{}]|\bexpr\b")


def unquote_tcl_word(word: str) -> str:
    return word[1:-1] if re.match(r'^"[^"]*"$|^\{[^{}]*\}$', word) else word


def has_tcl_syntax(s: str) -> bool:
    return bool(TCL_SYNTAX.search(s))


def _matching_bracket(text: str, start: int) -> int:
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "[":
            depth += 1
        elif text[i] == "]":
            depth -= 1
            if depth == 0:
                return i
    return -1


def normalize_expr_text(text: str) -> str:
    t = text.strip()
    if t.startswith("[") and _matching_bracket(t, 0) == len(t) - 1:
        inner = t[1:-1].strip()
        if re.match(r"^expr\b", inner):
            t = inner
    t = re.sub(r"^expr\b\s*", "", t)
    if t.startswith("{") and t.endswith("}"):
        t = t[1:-1]
    t = re.sub(r'\[\s*get_parameter_value\s+("[^"]*"|\{[^{}]*\}|\w+)\s*\]', lambda m: unquote_tcl_word(m.group(1)), t)
    return t.strip()


def log2ceil_to_clog2(arg: str) -> Optional[str]:
    normalized = normalize_expr_text(unquote_tcl_word(arg.strip()))
    return None if normalized == "" or '"' in normalized or has_tcl_syntax(normalized) else f"clog2({normalized})"


CONDITION_OPS = ["==", "!=", "<=", ">=", "&&", "||", "<", ">", "!"]


def tokenize_expr(text: str, allow_condition: bool = False) -> Optional[List[Tuple[str, Any]]]:
    tokens: List[Tuple[str, Any]] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch.isspace():
            i += 1
        elif ch.isdigit():
            m = re.match(r"^\d+", text[i:])
            tokens.append(("num", int(m.group(0))))
            i += len(m.group(0))
        elif re.match(r"[A-Za-z_]", ch):
            m = re.match(r"^[A-Za-z_]\w*", text[i:])
            if m.group(0) == "expr":
                return None
            if m.group(0) == "clog2" and re.match(r"^\s*\(", text[i + len(m.group(0)):]):
                tokens.append(("fn", "clog2"))
            else:
                tokens.append(("id", m.group(0)))
            i += len(m.group(0))
        elif ch in "+-*/%()":
            tokens.append(("op", ch))
            i += 1
        else:
            op = next((o for o in CONDITION_OPS if text.startswith(o, i)), None) if allow_condition else None
            if not op:
                return None
            tokens.append(("op", op))
            i += len(op)
    return tokens if tokens else None


def _ceil_log2(e: float) -> int:
    bits = 0
    while 2 ** bits < e:
        bits += 1
    return bits


class _ExprSyntaxError(Exception):
    pass


def _js_floor_div(a: float, b: float) -> float:
    return math.floor(a / b)


def eval_tokens(tokens: List[Tuple[str, Any]], lookup: Callable[[str], Optional[float]], condition: bool = False) -> dict:
    pos = 0
    invalid = False

    def peek_op() -> Optional[str]:
        return tokens[pos][1] if pos < len(tokens) and tokens[pos][0] == "op" else None

    def next_token():
        nonlocal pos
        if pos >= len(tokens):
            return None
        t = tokens[pos]
        pos += 1
        return t

    def parse_primary() -> float:
        nonlocal invalid
        t = next_token()
        if t is None:
            raise _ExprSyntaxError()
        kind, val = t
        if kind == "num":
            return val
        if kind == "fn":
            open_ = next_token()
            if open_ is None or open_ != ("op", "("):
                raise _ExprSyntaxError()
            arg = parse_or() if condition else parse_sum()
            close = next_token()
            if close is None or close != ("op", ")"):
                raise _ExprSyntaxError()
            return _ceil_log2(arg)
        if kind == "id":
            v = lookup(val)
            if v is None:
                invalid = True
                return 0
            return v
        if val == "(":
            v = parse_or() if condition else parse_sum()
            close = next_token()
            if close is None or close != ("op", ")"):
                raise _ExprSyntaxError()
            return v
        raise _ExprSyntaxError()

    def parse_unary() -> float:
        nonlocal pos
        if peek_op() == "-":
            pos += 1
            return -parse_unary()
        if condition and peek_op() == "!":
            pos += 1
            return 1 if parse_unary() == 0 else 0
        return parse_primary()

    def parse_product() -> float:
        nonlocal pos, invalid
        v = parse_unary()
        op = peek_op()
        while op in ("*", "/", "%"):
            pos += 1
            rhs = parse_unary()
            if op == "*":
                v *= rhs
            elif rhs == 0:
                invalid = True
            elif op == "/":
                v = _js_floor_div(v, rhs)
            else:
                v = v - rhs * _js_floor_div(v, rhs)
            op = peek_op()
        return v

    def parse_sum() -> float:
        nonlocal pos
        v = parse_product()
        op = peek_op()
        while op in ("+", "-"):
            pos += 1
            rhs = parse_product()
            v = v + rhs if op == "+" else v - rhs
            op = peek_op()
        return v

    def left_assoc(nxt: Callable[[], float], ops: Mapping[str, Callable[[float, float], float]]) -> Callable[[], float]:
        def run() -> float:
            nonlocal pos
            v = nxt()
            op = peek_op()
            while op is not None and op in ops:
                pos += 1
                v = ops[op](v, nxt())
                op = peek_op()
            return v

        return run

    b = lambda x: 1 if x else 0  # noqa: E731
    relational = {"<": lambda a, c: b(a < c), ">": lambda a, c: b(a > c), "<=": lambda a, c: b(a <= c), ">=": lambda a, c: b(a >= c)}
    equality = {"==": lambda a, c: b(a == c), "!=": lambda a, c: b(a != c)}
    parse_relational = left_assoc(parse_sum, relational)
    parse_equality = left_assoc(parse_relational, equality)
    parse_and = left_assoc(parse_equality, {"&&": lambda a, c: b(a != 0 and c != 0)})
    parse_or = left_assoc(parse_and, {"||": lambda a, c: b(a != 0 or c != 0)})

    try:
        v = parse_or() if condition else parse_sum()
        if pos != len(tokens):
            return {"syntaxOk": False, "value": None}
        unsafe = invalid or not float(v).is_integer() or abs(v) > 2**53 - 1
        return {"syntaxOk": True, "value": None if unsafe else int(v)}
    except _ExprSyntaxError:
        return {"syntaxOk": False, "value": None}


def reduce_tcl_expr(text: str, param_names: Set[str]) -> Union[int, str, None]:
    normalized = normalize_expr_text(text)
    tokens = tokenize_expr(normalized)
    if not tokens:
        return None
    ids = [t for t in tokens if t[0] == "id"]
    if any(t[1] not in param_names for t in ids):
        return None
    if not ids:
        return eval_tokens(tokens, lambda n: None)["value"]
    if not eval_tokens(tokens, lambda n: 1)["syntaxOk"]:
        return None
    return re.sub(r"\s+", " ", normalized)


def evaluate_tcl_int(text: str, param_values: Mapping[str, int]) -> Optional[int]:
    tokens = tokenize_expr(normalize_expr_text(text))
    return eval_tokens(tokens, lambda n: param_values.get(n))["value"] if tokens else None


def evaluate_tcl_condition(text: str, param_values: Mapping[str, int]) -> Optional[bool]:
    tokens = tokenize_expr(normalize_expr_text(text), True)
    if not tokens:
        return None
    value = eval_tokens(tokens, lambda n: param_values.get(n), True)["value"]
    return None if value is None else value != 0


def numeric_param_values(params: List[dict]) -> Dict[str, int]:
    values: Dict[str, int] = {}
    for p in params:
        raw = (p.get("defaultValue") or "").strip()
        if not raw:
            continue
        if re.match(r"^(?:true|false)$", raw, re.IGNORECASE):
            value: Optional[float] = 1 if raw.lower() == "true" else 0
        else:
            value = js_number(raw)
        if value is not None and float(value).is_integer():
            values[p["name"]] = int(value)
    return values


def resolve_tcl_width(raw: str, param_names: Set[str]) -> Union[int, str, None]:
    if re.match(r"^\s*-?\d+\s*$", raw):
        return int(raw)
    resolved = reduce_tcl_expr(raw, param_names) if re.match(r"^\s*(?:expr\b|clog2\()", raw) else raw
    if resolved is None or (isinstance(resolved, str) and has_tcl_syntax(resolved)):
        return None
    return resolved


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------


def substitute_tcl_variables(value: str, variables: Mapping[str, str]) -> str:
    result = ""
    i = 0
    while i < len(value):
        if value[i] == "\\" and i + 1 < len(value) and value[i + 1] == "$":
            result += "$"
            i += 2
            continue
        if value[i] != "$":
            result += value[i]
            i += 1
            continue
        end = i + 1
        if end < len(value) and value[end] == "{":
            closing = value.find("}", end + 1)
            if closing == -1:
                result += "$"
                i += 1
                continue
            name = value[end + 1:closing]
            end = closing + 1
        else:
            m = re.match(r"^[A-Za-z0-9_:]+", value[end:])
            if not m:
                result += "$"
                i += 1
                continue
            name = m.group(0)
            end += len(name)
        result += variables.get(name, value[i:end])
        i = end
    return result


def parse_tcl_tokens(line: str, variables: Optional[Mapping[str, str]] = None, rewrite_log2ceil: bool = False) -> List[str]:
    variables = variables or {}
    tokens: List[str] = []
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if ch in " \t":
            i += 1
            continue
        if ch == '"':
            i += 1
            val = ""
            while i < n and line[i] != '"':
                if line[i] == "\\" and i + 1 < n:
                    escaped = line[i + 1]
                    val += f"\\{escaped}" if escaped == "$" else escaped
                    i += 2
                    continue
                val += line[i]
                i += 1
            i += 1
            tokens.append(substitute_tcl_variables(val, variables))
            continue
        if ch == "{":
            i += 1
            val = ""
            depth = 1
            while i < n and depth > 0:
                if line[i] == "\\" and i + 1 < n:
                    val += line[i] + line[i + 1]
                    i += 2
                    continue
                if line[i] == "{":
                    depth += 1
                elif line[i] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                val += line[i]
                i += 1
            i += 1
            tokens.append(val)
            continue
        if ch == "[":
            depth = 1
            i += 1
            body = ""
            while i < n and depth > 0:
                if line[i] == "[":
                    depth += 1
                elif line[i] == "]":
                    depth -= 1
                    if depth == 0:
                        break
                body += line[i]
                i += 1
            i += 1
            m = re.match(r"^\s*get_parameter_value\s+(\S+)\s*$", body)
            if m:
                tokens.append(substitute_tcl_variables(unquote_tcl_word(m.group(1)), variables))
            else:
                substituted = substitute_tcl_variables(body, variables)
                m2 = re.match(r"^\s*log2ceil\s+([\s\S]*?)\s*$", substituted) if rewrite_log2ceil else None
                clog2 = log2ceil_to_clog2(m2.group(1)) if m2 else None
                tokens.append(clog2 if clog2 is not None else (substituted if re.match(r"^\s*expr\b", body) else f"[{substituted}]"))
            continue
        val = ""
        while i < n and line[i] not in " \t":
            val += line[i]
            i += 1
        tokens.append(substitute_tcl_variables(val, variables))
    return tokens
