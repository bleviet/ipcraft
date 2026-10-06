"""Helpers for the ``_hw.tcl`` importer: loops, conditionals, procs, port effects and legacy ports
(ports of ``hwTclLoops.ts``, ``hwTclConditionals.ts``, ``hwTclProcs.ts``, ``hwTclPortEffects.ts``
and ``hwTclLegacyPorts.ts``)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Set, Tuple

from .hwtcl_expr import (
    evaluate_tcl_condition,
    evaluate_tcl_int,
    has_tcl_syntax,
    parse_tcl_tokens,
    resolve_tcl_width,
)
from .verilog import extract_verilog_interface

MAX_LOOP_ITERATIONS = 256

Word = Dict[str, str]  # {"kind": "brace"|"other", "text": str}


def parse_tcl_list(text: str) -> List[str]:
    items: List[str] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i].isspace():
            i += 1
        elif text[i] == '"':
            item = ""
            j = i + 1
            while j < n and text[j] != '"':
                if text[j] == "\\" and j + 1 < n:
                    j += 1
                item += text[j]
                j += 1
            items.append(item)
            i = j + 1
        elif text[i] == "{":
            depth = 0
            j = i
            while j < n:
                if text[j] == "{":
                    depth += 1
                elif text[j] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            items.append(text[i + 1:j])
            i = j + 1
        else:
            j = i
            while j < n and not text[j].isspace():
                j += 1
            items.append(text[i:j])
            i = j
    return items


def brace_delta(line: str) -> int:
    if line.lstrip().startswith("#"):
        return 0
    delta = 0
    i = 0
    while i < len(line):
        if line[i] == "\\":
            i += 1
        elif line[i] == "{":
            delta += 1
        elif line[i] == "}":
            delta -= 1
        i += 1
    return delta


def split_words(line: str) -> List[Word]:
    words: List[Word] = []
    i = 0
    n = len(line)
    while i < n:
        if line[i].isspace():
            i += 1
            continue
        if line[i] == "{":
            depth = 0
            j = i
            while j < n:
                if line[j] == "\\":
                    j += 1
                elif line[j] == "{":
                    depth += 1
                elif line[j] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            words.append({"kind": "brace", "text": line[i + 1:j]})
            i = j + 1
            continue
        j = i
        bracket_depth = 0
        while j < n and (bracket_depth > 0 or not line[j].isspace()):
            if line[j] == "[":
                bracket_depth += 1
            elif line[j] == "]":
                bracket_depth -= 1
            j += 1
        words.append({"kind": "other", "text": line[i:j]})
        i = j
    return words


def collect_loop_body(lines: List[str], header_idx: int) -> Dict[str, Any]:
    depth = brace_delta(lines[header_idx])
    if depth <= 0:
        words = split_words(lines[header_idx])
        last = words[-1] if words else None
        return {"body": [last["text"]] if last and last["kind"] == "brace" else [], "next": header_idx + 1}
    body: List[str] = []
    idx = header_idx + 1
    while idx < len(lines):
        depth += brace_delta(lines[idx])
        if depth <= 0:
            idx += 1
            break
        body.append(lines[idx])
        idx += 1
    return {"body": body, "next": idx}


def _eval_bound(text: str, ctx: dict) -> Optional[int]:
    return evaluate_tcl_int(ctx["substitute"](text), ctx["paramValues"])


def _resolve_for_loop(words: List[Word], ctx: dict) -> Optional[dict]:
    if len(words) < 4:
        return None
    _, init, cond, nxt = words[0], words[1], words[2], words[3]
    if init["kind"] != "brace" or cond["kind"] != "brace" or nxt["kind"] != "brace":
        return None
    init_m = re.match(r"^\s*set\s+(\w+)\s+(.+?)\s*$", init["text"])
    cond_m = re.match(r"^\s*\$(?:\{(\w+)\}|(\w+))\s*(<=|<)\s*(.+?)\s*$", cond["text"])
    next_m = re.match(r"^\s*incr\s+(\w+)(?:\s+(.+?))?\s*$", nxt["text"])
    if not init_m or not cond_m or not next_m:
        return None
    variable = init_m.group(1)
    if (cond_m.group(1) or cond_m.group(2)) != variable or next_m.group(1) != variable:
        return None
    start = _eval_bound(init_m.group(2), ctx)
    bound = _eval_bound(cond_m.group(4), ctx)
    step = 1 if next_m.group(2) is None else _eval_bound(next_m.group(2), ctx)
    if start is None or bound is None or step is None or step <= 0:
        return None
    inclusive = cond_m.group(3) == "<="
    values: List[str] = []
    v = start
    while (v <= bound) if inclusive else (v < bound):
        if len(values) >= MAX_LOOP_ITERATIONS:
            return None
        values.append(str(v))
        v += step
    return {"variable": variable, "values": values}


def _resolve_foreach_loop(words: List[Word], ctx: dict) -> Optional[dict]:
    if len(words) < 3:
        return None
    var_word, list_word = words[1], words[2]
    if var_word["kind"] != "other" or not re.match(r"^\w+$", var_word["text"]):
        return None
    if list_word["kind"] == "brace":
        values = parse_tcl_list(list_word["text"])
    else:
        ref = re.match(r"^\$(?:\{(\w+)\}|(\w+))$", list_word["text"])
        value = ctx["getVariable"](ref.group(1) or ref.group(2)) if ref else None
        if value is None:
            return None
        list_cmd = re.match(r"^\s*\[\s*list\b([\s\S]*)\]\s*$", value)
        if list_cmd:
            values = parse_tcl_list(list_cmd.group(1))
        elif has_tcl_syntax(value) or ctx["isParameter"](value.strip()):
            return None
        else:
            values = parse_tcl_list(value)
    if len(values) > MAX_LOOP_ITERATIONS or any(has_tcl_syntax(v) for v in values):
        return None
    return {"variable": var_word["text"], "values": values}


def resolve_loop(header: str, ctx: dict) -> Optional[dict]:
    words = split_words(header)
    if words and words[0]["text"] == "for":
        return _resolve_for_loop(words, ctx)
    if words and words[0]["text"] == "foreach":
        return _resolve_foreach_loop(words, ctx)
    return None


# -- conditionals ----------------------------------------------------------------


def collect_if_chain(lines: List[str], header_idx: int) -> dict:
    depth = brace_delta(lines[header_idx])
    nxt = header_idx + 1
    while depth > 0 and nxt < len(lines):
        depth += brace_delta(lines[nxt])
        nxt += 1
    chain_lines = [l for l in lines[header_idx:nxt] if not l.lstrip().startswith("#")]
    branches = _parse_branches(split_words("\n".join(chain_lines)))
    if branches is not None:
        return {"branches": branches, "parsed": True, "next": nxt}
    inner = lines[header_idx + 1: nxt if depth > 0 else nxt - 1]
    return {"branches": [{"condition": None, "body": inner}], "parsed": False, "next": nxt}


def _parse_branches(words: List[Word]) -> Optional[List[dict]]:
    branches: List[dict] = []
    i = 0
    if i >= len(words) or words[i]["text"] != "if":
        return None
    i += 1
    while True:
        cond = words[i] if i < len(words) else None
        body = words[i + 1] if i + 1 < len(words) else None
        i += 2
        if not cond or not body or cond["kind"] != "brace" or body["kind"] != "brace":
            return None
        branches.append({"condition": cond["text"], "body": body["text"].split("\n")})
        keyword = words[i] if i < len(words) else None
        i += 1
        if keyword is None:
            return branches
        if keyword["text"] == "else":
            else_body = words[i] if i < len(words) else None
            i += 1
            if not else_body or else_body["kind"] != "brace" or i != len(words):
                return None
            branches.append({"condition": None, "body": else_body["text"].split("\n")})
            return branches
        if keyword["text"] != "elseif":
            return None


def select_if_branches(chain: dict, evaluate: Callable[[str], Optional[bool]]) -> dict:
    all_ = {"bodies": [b["body"] for b in chain["branches"]], "resolved": False}
    if not chain["parsed"]:
        return all_
    for branch in chain["branches"]:
        taken = True if branch["condition"] is None else evaluate(branch["condition"])
        if taken is None:
            return all_
        if taken:
            return {"bodies": [branch["body"]], "resolved": True}
    return {"bodies": [], "resolved": True}


# -- procs ------------------------------------------------------------------------


def parse_proc_params(spec: str) -> List[dict]:
    out = []
    for item in parse_tcl_list(spec):
        parts = parse_tcl_list(item)
        name = parts[0] if parts else ""
        default = parts[1] if len(parts) > 1 else None
        out.append({"name": name} if default is None else {"name": name, "defaultValue": default})
    return out


def compute_proc_defaults(lines: List[str]) -> Dict[str, Dict[str, str]]:
    declared: Dict[str, List[dict]] = {}
    max_arity: Dict[str, int] = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        tokens = parse_tcl_tokens(line)
        if tokens and tokens[0] == "proc" and len(tokens) >= 3:
            declared[tokens[1]] = parse_proc_params(tokens[2])
        elif tokens:
            max_arity[tokens[0]] = max(max_arity.get(tokens[0], 0), len(tokens) - 1)
    result: Dict[str, Dict[str, str]] = {}
    for name, params in declared.items():
        passed = max_arity.get(name, 0)
        bindings: Dict[str, str] = {}
        for i, p in enumerate(params):
            if p.get("defaultValue") is not None and i >= passed:
                bindings[p["name"]] = p["defaultValue"]
        if bindings:
            result[name] = bindings
    return result


def _strip_space(s: str) -> str:
    return re.sub(r"\s+", "", s)


def _loop_form(p: str) -> List[str]:
    return ["setval0", "seti1", f"while{{$i<${p}}}{{", "setval[expr$val+1]", "seti[expr1<<$val]", "}", "return$val"]


def is_ceil_log2_proc(lines: List[str], header_idx: int) -> bool:
    header = lines[header_idx].strip()
    tokens = parse_tcl_tokens(header)
    if len(tokens) < 3 or tokens[0] != "proc" or tokens[1] != "log2ceil":
        return False
    params = parse_proc_params(tokens[2])
    if len(params) != 1:
        return False
    p = params[0]["name"]
    if _strip_space(header) == _strip_space(f'proc log2ceil {p} "expr {{int(ceil(log(\\${p})/[expr log(2)]))}}"'):
        return True
    body = collect_loop_body(lines, header_idx)["body"]
    code = [re.sub(r";$", "", _strip_space(l.strip())) for l in body if l.strip() != "" and not l.strip().startswith("#")]
    if len(code) == 1 and code[0] == f"return[expr{{int(ceil(log(${p})/log(2)))}}]":
        return True
    expected = _loop_form(p)
    return len(code) == len(expected) and all(c == e for c, e in zip(code, expected))


def has_ceil_log2_proc(lines: List[str]) -> bool:
    last = -1
    for i, line in enumerate(lines):
        if re.match(r"^\s*proc\s+log2ceil\b", line):
            last = i
    return last >= 0 and is_ceil_log2_proc(lines, last)


# -- port effects -------------------------------------------------------------------


def apply_port_property(interfaces: Mapping[str, dict], port_name: str, prop_name: str, value: str,
                        param_names: Set[str], param_values: Mapping[str, int], unresolved: bool) -> List[str]:
    prop = prop_name.upper()
    if prop not in ("TERMINATION", "WIDTH", "WIDTH_EXPR"):
        return []
    warnings: List[str] = []
    for iface in interfaces.values():
        for port in iface["ports"]:
            if port["portName"] != port_name:
                continue
            if unresolved:
                warnings.append(f'Port "{port_name}" on interface "{iface["name"]}": {prop} is changed under a condition '
                                f"that could not be evaluated, so the static declaration was kept.")
            elif prop == "TERMINATION":
                literal = value.strip().lower()
                if literal in ("true", "1"):
                    terminated: Optional[bool] = True
                elif literal in ("false", "0"):
                    terminated = False
                else:
                    terminated = evaluate_tcl_condition(value, param_values)
                if terminated is None:
                    warnings.append(f'Port "{port_name}" on interface "{iface["name"]}": {prop_name} "{value}" '
                                    f"could not be resolved, so the static termination was kept.")
                else:
                    port["terminated"] = terminated
            else:
                width = resolve_tcl_width(value, param_names)
                if width is None:
                    warnings.append(f'Port "{port_name}" on interface "{iface["name"]}": {prop_name} "{value}" '
                                    f"could not be resolved, so the static width was kept as a placeholder.")
                else:
                    port["width"] = width
    return warnings


def finalize_interfaces(interfaces: Mapping[str, dict], param_values: Mapping[str, int]) -> Dict[str, Any]:
    warnings: List[str] = []
    result: Dict[str, dict] = {}
    for key, iface in interfaces.items():
        ports: List[dict] = []
        for port in iface["ports"]:
            if port.get("terminated"):
                continue
            width = port.get("width")
            disabled_by = None
            if width == 0 and not isinstance(width, bool) and width is not None and not isinstance(width, str):
                disabled_by = "0"
            elif isinstance(width, str) and param_values.get(width) == 0:
                disabled_by = width
            if disabled_by is not None:
                if isinstance(width, str):
                    warnings.append(f'Port "{port["portName"]}" on interface "{iface["name"]}" was dropped: it is disabled '
                                    f'by default because parameter "{disabled_by}" defaults to 0.')
                else:
                    warnings.append(f'Port "{port["portName"]}" on interface "{iface["name"]}" was dropped: its width is 0.')
                continue
            if isinstance(width, (int, float)) and not isinstance(width, bool) and width < 0:
                warnings.append(f'Port "{port["portName"]}" on interface "{iface["name"]}": placeholder width {width} '
                                f"was left out because no elaboration set a width.")
                ports.append({**port, "width": None})
            else:
                ports.append(port)
        if len(iface["ports"]) == 0 or ports:
            result[key] = {**iface, "ports": ports}
    return {"interfaces": result, "warnings": warnings}


# -- legacy ports ----------------------------------------------------------------------


def has_legacy_port_declarations(content: str) -> bool:
    return bool(re.search(r"^\s*add_port_to_interface\b", content, re.MULTILINE))


def slice_verilog_module(source: str, module_name: Optional[str] = None) -> str:
    if not module_name:
        return source
    start = re.search(rf"\bmodule\s+{re.escape(module_name)}\b", source)
    if not start:
        return source
    end = re.search(r"\bendmodule\b", source[start.start():])
    return source[start.start(): start.start() + end.end()] if end else source[start.start():]


def _command_arg(content: str, command: str) -> Optional[str]:
    for raw in content.split("\n"):
        tokens = parse_tcl_tokens(raw.strip())
        if tokens and tokens[0] == command and len(tokens) >= 2:
            return tokens[1]
    return None


def read_legacy_ports(content: str, tcl_dir: str) -> dict:
    def unresolved(why: str) -> dict:
        return {"ports": None, "warning": f"Ports declared with add_port_to_interface could not be resolved: {why}."}

    source_file = _command_arg(content, "set_source_file")
    if not source_file:
        return unresolved("the file declares no set_source_file")
    if not re.search(r"\.s?v$", source_file, re.IGNORECASE):
        return unresolved(f'source file "{source_file}" is not Verilog or SystemVerilog')
    try:
        with open(os.path.abspath(os.path.join(tcl_dir, source_file)), encoding="utf-8") as fh:
            source = fh.read()
    except OSError:
        return unresolved(f'source file "{source_file}" could not be read')
    sliced = slice_verilog_module(source, _command_arg(content, "set_module"))
    ports = {p["name"]: {"direction": p["direction"], "width": p.get("width")}
             for p in extract_verilog_interface(sliced)["ports"]}
    return {"ports": ports}
