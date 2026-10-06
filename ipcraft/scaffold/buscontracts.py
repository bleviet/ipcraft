"""Declarative bus-contract engine (port of ``shared/busContracts``).

A bus *library* is a dict ``{"definitions": {key: contract}, "aliases": [...],
"diagnostics": [...]}``.  Contracts, ports, resolved widths and diagnostics are plain
dicts keyed with the same camelCase names the TypeScript implementation uses, so the
two stay easy to compare.
"""

from __future__ import annotations

import copy
import math
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from . import widthexpr as wx

BYTE_LANE_WIDTH = 8
MAX_SAFE_INTEGER = 2**53 - 1
MIN_SAFE_INTEGER = -(2**53 - 1)

CANONICAL_ROLES = {"clock", "reset", "data", "byteQualifier", "control"}
DERIVED_OPERATIONS = {
    "copyPort",
    "multiplyBy",
    "divideBy",
    "multiplyProperties",
    "ceilLog2",
    "bitsForMaximum",
    "maxEncodableValue",
}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _is_safe_int(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return abs(value) <= MAX_SAFE_INTEGER
    return isinstance(value, float) and math.isfinite(value) and value == int(value) and abs(value) <= MAX_SAFE_INTEGER


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and len(value) > 0


# ---------------------------------------------------------------------------
# Library normalization
# ---------------------------------------------------------------------------


def add_diag(diags: List[dict], source_file: str, code: str, severity: str, path: list, message: str) -> None:
    diags.append({"code": code, "severity": severity, "sourceFile": source_file, "path": path, "message": message})


def short_alias_key(value: str) -> str:
    return re.sub(r"[\s_.-]", "", value.strip().lower())


def normalize_bus_alias(alias: dict, canonical: str) -> Optional[dict]:
    if alias.get("kind") == "short":
        short = str(alias.get("value", "")).strip().lower()
        return {"kind": "short", "canonicalVlnv": canonical, "shortValue": short} if short else None
    if not all(_nonempty(alias.get(k)) for k in ("vendor", "library", "name", "version")):
        return None
    return {
        "kind": "vlnv",
        "canonicalVlnv": canonical,
        "vendor": alias["vendor"],
        "library": alias["library"],
        "name": alias["name"],
        "version": alias["version"],
    }


def bus_alias_identity(alias: dict) -> str:
    if alias["kind"] == "short":
        return f"short:{short_alias_key(alias.get('shortValue') or '')}"
    return f"vlnv:{alias.get('vendor')}:{alias.get('library')}:{alias.get('name')}:{alias.get('version')}"


def normalize_mode_policy(contract: Optional[dict]) -> Optional[dict]:
    if not contract:
        return {"producer": "master", "consumer": "slave", "aliases": {}}
    mp = contract.get("modePolicy") or {}
    producer = (mp.get("producer") or "").strip().lower()
    consumer = (mp.get("consumer") or "").strip().lower()
    if not producer or not consumer or producer == consumer:
        return None
    aliases: Dict[str, str] = {}
    for alias, target in (mp.get("aliases") or {}).items():
        na, nt = alias.strip().lower(), target.strip().lower()
        if not na or nt not in (producer, consumer):
            return None
        aliases[na] = nt
    return {"producer": producer, "consumer": consumer, "aliases": aliases}


def canonical_vlnv_of(entry: dict) -> Optional[str]:
    bt = entry.get("busType")
    if not isinstance(bt, dict) or not all(_nonempty(bt.get(k)) for k in ("vendor", "library", "name", "version")):
        return None
    return f"{bt['vendor']}:{bt['library']}:{bt['name']}:{bt['version']}"


def bus_display_name(entry: dict) -> str:
    bt = entry["busType"]
    if bt.get("displayName"):
        return bt["displayName"]
    return "-".join(p[:1].upper() + p[1:] for p in re.split(r"[_-]", bt["name"]) if p)


def _normalize_polarity(polarity: Any, port: dict, key: str, index: int, source_file: str, diags: List[dict]):
    if polarity is None and "polarity" not in port:
        return None, True
    path = [key, "ports", index, "polarity"]

    def bad(sub: Optional[list] = None, msg: Optional[str] = None):
        add_diag(diags, source_file, "BUS_DEF_INVALID_PORT_POLARITY", "error", path + (sub or []),
                 msg or f"Port '{port.get('name')}' has an invalid polarity declaration.")
        return None, False

    if port.get("direction") == "inout" or not isinstance(polarity, dict):
        return bad()
    if polarity.get("default") not in ("activeHigh", "activeLow"):
        return bad(["default"])
    roles = polarity.get("roles")
    if not isinstance(roles, dict):
        return bad(["roles"])
    if not _nonempty(roles.get("activeHigh")):
        return bad(["roles", "activeHigh"])
    if not _nonempty(roles.get("activeLow")):
        return bad(["roles", "activeLow"])
    if roles["activeHigh"].lower() == roles["activeLow"].lower():
        return bad(["roles", "activeLow"], f"Port '{port.get('name')}' must declare distinct activeHigh and activeLow roles.")
    return {"default": polarity["default"], "roles": {"activeHigh": roles["activeHigh"], "activeLow": roles["activeLow"]}}, True


def normalize_port(port: dict, key: str, index: int, source_file: str, diags: List[dict]) -> Optional[dict]:
    if not _nonempty(port.get("name")):
        add_diag(diags, source_file, "BUS_DEF_INVALID_PORT", "error", [key, "ports", index, "name"],
                 "Bus port names must be non-empty strings.")
        return None
    polarity, ok = _normalize_polarity(port.get("polarity"), port, key, index, source_file, diags)
    if not ok:
        return None
    role = "control"
    if port.get("role") is not None:
        if port["role"] in CANONICAL_ROLES:
            role = port["role"]
        else:
            add_diag(diags, source_file, "BUS_DEF_UNKNOWN_PORT_ROLE", "warning", [key, "ports", index, "role"],
                     f"Unknown role '{port['role']}' on port '{port['name']}'; treating it as control.")
    width_policy = port.get("widthPolicy") or ("derived" if port.get("derivedWidth") else "root")
    if width_policy == "derived" and not port.get("derivedWidth"):
        add_diag(diags, source_file, "BUS_DEF_INVALID_DERIVATION", "error", [key, "ports", index, "derivedWidth"],
                 f"Derived port '{port['name']}' must declare derivedWidth.")
        return None
    if width_policy != "derived" and port.get("derivedWidth"):
        add_diag(diags, source_file, "BUS_DEF_INVALID_DERIVATION", "error", [key, "ports", index, "derivedWidth"],
                 "Only a derived port may declare derivedWidth.")
        return None
    out: Dict[str, Any] = {"name": port["name"]}
    if port.get("width") is not None:
        out["width"] = port["width"]
    if port.get("direction") is not None:
        out["direction"] = port["direction"]
    out["presence"] = port.get("presence") or "required"
    out["role"] = role
    if polarity:
        out["polarity"] = polarity
    out["widthPolicy"] = width_policy
    if port.get("derivedWidth"):
        out["derivedWidth"] = copy.deepcopy(port["derivedWidth"])
    if port.get("overrideConstraintRuleId"):
        out["overrideConstraintRuleId"] = port["overrideConstraintRuleId"]
    return out


def normalize_property(decl: dict) -> Optional[dict]:
    t = decl.get("type")
    if t not in ("integer", "boolean", "string"):
        return None

    def matches(v: Any) -> bool:
        if t == "integer":
            return _is_safe_int(v)
        if t == "boolean":
            return isinstance(v, bool)
        return isinstance(v, str)

    default, minimum, maximum = decl.get("default"), decl.get("minimum"), decl.get("maximum")
    allowed = decl.get("allowedValues")
    if default is not None and not matches(default):
        return None
    if allowed is not None and any(not matches(v) for v in allowed):
        return None
    if t != "integer" and (minimum is not None or maximum is not None or decl.get("derive") is not None):
        return None
    if t == "integer":
        if (minimum is not None and not _is_safe_int(minimum)) or (maximum is not None and not _is_safe_int(maximum)):
            return None
        if minimum is not None and maximum is not None and minimum > maximum:
            return None
        if _is_number(default) and ((minimum is not None and default < minimum) or (maximum is not None and default > maximum)):
            return None
    if default is not None and allowed is not None and default not in allowed:
        return None
    out: Dict[str, Any] = {"type": t}
    for k in ("default", "minimum", "maximum", "allowedValues"):
        if decl.get(k) is not None:
            out[k] = copy.deepcopy(decl[k])
    if decl.get("derive"):
        out["derive"] = copy.deepcopy(decl["derive"])
    return out


def operation_references(op: dict, path: list) -> List[dict]:
    refs: List[dict] = []

    def ref(kind: str, name: str, p: list) -> dict:
        return {"node": f"{kind}:{name}", "kind": kind, "name": name, "path": p}

    if op.get("port"):
        refs.append(ref("port", op["port"], path + ["port"]))
    if op.get("property"):
        refs.append(ref("property", op["property"], path + ["property"]))
    if op.get("divisorProperty"):
        refs.append(ref("property", op["divisorProperty"], path + ["divisorProperty"]))
    if "properties" in op:
        for i, name in enumerate(op["properties"]):
            refs.append(ref("property", name, path + ["properties", i]))
    return refs


def constraint_references(c: dict, path: list) -> List[dict]:
    refs: List[dict] = []

    def ref(kind: str, name: str, p: list) -> dict:
        return {"node": f"{kind}:{name}", "kind": kind, "name": name, "path": p}

    if c.get("port"):
        refs.append(ref("port", c["port"], path + ["port"]))
    if c.get("kind") == "portWidthQuotient":
        refs.append(ref("port", c["dividendPort"], path + ["dividendPort"]))
    if c.get("kind") == "portWidthsEqual":
        for i, n in enumerate(c["ports"]):
            refs.append(ref("port", n, path + ["ports", i]))
    if c.get("kind") == "portPresenceRequires":
        for i, n in enumerate(c["requires"]):
            refs.append(ref("port", n, path + ["requires", i]))
    if c.get("property"):
        refs.append(ref("property", c["property"], path + ["property"]))
    if c.get("kind") == "productEqualsPort":
        for i, n in enumerate(c["properties"]):
            refs.append(ref("property", n, path + ["properties", i]))
    return refs


def has_dependency_cycle(graph: Mapping[str, Sequence[str]]) -> bool:
    states: Dict[str, str] = {}

    def visit(node: str) -> bool:
        st = states.get(node)
        if st == "visiting":
            return True
        if st == "visited":
            return False
        states[node] = "visiting"
        for dep in graph.get(node, []):
            if visit(dep):
                return True
        states[node] = "visited"
        return False

    return any(visit(n) for n in list(graph))


def _normalize_entry(key: str, entry: dict, source: dict, diags: List[dict]):
    errors_before = sum(1 for d in diags if d["severity"] == "error")
    sf = source["sourceFile"]
    canonical = canonical_vlnv_of(entry)
    if not canonical or not isinstance(entry.get("ports"), list):
        add_diag(diags, sf, "BUS_DEF_MALFORMED_CONTRACT", "error", [key],
                 f"Bus definition '{key}' is missing valid busType metadata or ports.")
        return None
    contract_raw = entry.get("contract")
    mode_policy = normalize_mode_policy(contract_raw)
    if not mode_policy:
        add_diag(diags, sf, "BUS_DEF_INVALID_MODE_POLICY", "error", [key, "contract", "modePolicy"],
                 f"Bus definition '{key}' has an invalid mode policy.")

    ports: List[dict] = []
    port_names = set()
    for index, port in enumerate(entry["ports"]):
        normalized = normalize_port(port, key, index, sf, diags)
        if not normalized:
            continue
        if normalized["name"] in port_names:
            add_diag(diags, sf, "BUS_DEF_DUPLICATE_PORT", "error", [key, "ports", index, "name"],
                     f"Port '{normalized['name']}' is declared more than once.")
            continue
        port_names.add(normalized["name"])
        ports.append(normalized)

    role_owners = {p["name"].lower(): p["name"] for p in ports}
    for index, port in enumerate(entry["ports"]):
        normalized = next((c for c in ports if c["name"] == port.get("name")), None)
        if not normalized or not normalized.get("polarity"):
            continue
        for role in ("activeHigh", "activeLow"):
            name = normalized["polarity"]["roles"][role]
            owner = role_owners.get(name.lower())
            if owner is not None and owner != normalized["name"]:
                add_diag(diags, sf, "BUS_DEF_PORT_ROLE_COLLISION", "error",
                         [key, "ports", index, "polarity", "roles", role],
                         f"Port polarity role '{name}' collides with '{owner}'.")
                continue
            role_owners[name.lower()] = normalized["name"]

    properties: Dict[str, dict] = {}
    raw_props = (contract_raw or {}).get("interfaceProperties") or {}
    for name, decl in raw_props.items():
        normalized_prop = normalize_property(decl)
        if not normalized_prop:
            add_diag(diags, sf, "BUS_DEF_INVALID_PROPERTY", "error", [key, "contract", "interfaceProperties", name],
                     f"Interface property '{name}' has an invalid declaration.")
        else:
            properties[name] = normalized_prop
    property_names = set(properties)

    graph: Dict[str, List[str]] = {}

    def validate_refs(refs: List[dict]) -> None:
        for r in refs:
            declared = r["name"] in port_names if r["kind"] == "port" else r["name"] in property_names
            if not declared:
                add_diag(diags, sf,
                         "BUS_DEF_UNDECLARED_PORT" if r["kind"] == "port" else "BUS_DEF_UNDECLARED_PROPERTY",
                         "error", r["path"],
                         f"Derived contract operand references undeclared {r['kind']} '{r['name']}'.")

    for index, port in enumerate(entry["ports"]):
        dw = port.get("derivedWidth")
        if not dw:
            continue
        if dw.get("operation") not in DERIVED_OPERATIONS:
            add_diag(diags, sf, "BUS_DEF_INVALID_DERIVATION", "error",
                     [key, "ports", index, "derivedWidth", "operation"],
                     f"Unknown derivation operation '{dw.get('operation')}'.")
            continue
        refs = operation_references(dw, [key, "ports", index, "derivedWidth"])
        validate_refs(refs)
        graph[f"port:{port['name']}"] = [r["node"] for r in refs]

    for name, decl in raw_props.items():
        derive = decl.get("derive")
        if not derive:
            continue
        if derive.get("operation") not in DERIVED_OPERATIONS:
            add_diag(diags, sf, "BUS_DEF_INVALID_DERIVATION", "error",
                     [key, "contract", "interfaceProperties", name, "derive", "operation"],
                     f"Unknown derivation operation '{derive.get('operation')}'.")
            continue
        refs = operation_references(derive, [key, "contract", "interfaceProperties", name, "derive"])
        validate_refs(refs)
        graph[f"property:{name}"] = [r["node"] for r in refs]

    constraints = (contract_raw or {}).get("constraints") or []
    for index, c in enumerate(constraints):
        validate_refs(constraint_references(c, [key, "contract", "constraints", index]))
    for index, port in enumerate(ports):
        rid = port.get("overrideConstraintRuleId")
        if rid and not any(c.get("ruleId") == rid for c in constraints):
            add_diag(diags, sf, "BUS_DEF_UNDECLARED_CONSTRAINT", "error", [key, "ports", index, "overrideConstraintRuleId"],
                     f"Port '{port['name']}' references undeclared constraint '{rid}'.")

    if has_dependency_cycle(graph):
        add_diag(diags, sf, "BUS_DEF_DERIVATION_CYCLE", "error", [key, "contract", "interfaceProperties"],
                 f"Bus definition '{key}' contains a circular derivation.")

    aliases: List[dict] = []
    for index, alias in enumerate(entry.get("aliases") or []):
        normalized_alias = normalize_bus_alias(alias, canonical)
        if not normalized_alias:
            add_diag(diags, sf, "BUS_DEF_INVALID_ALIAS", "error", [key, "aliases", index],
                     f"Bus definition '{key}' contains an invalid alias.")
        else:
            aliases.append(normalized_alias)

    errors_after = sum(1 for d in diags if d["severity"] == "error")
    if errors_after > errors_before or not mode_policy:
        return None

    contract = {
        "version": (contract_raw or {}).get("version"),
        "key": key,
        "canonicalVlnv": canonical,
        "displayName": bus_display_name(entry),
        "interfaceKind": (contract_raw or {}).get("interfaceKind") or "conduit",
        "modePolicy": mode_policy,
        "ports": ports,
        "interfaceProperties": properties,
        "constraints": copy.deepcopy(constraints),
        "sourceFile": sf,
        "sourceKind": source["sourceKind"],
    }
    if entry.get("source"):
        contract["artifactSource"] = entry["source"]
    return contract, aliases


def normalize_bus_library(inputs: Sequence[dict]) -> dict:
    definitions: Dict[str, dict] = {}
    aliases: List[dict] = []
    diagnostics: List[dict] = []
    alias_owners: Dict[str, str] = {}
    for source in inputs:
        for key, entry in source["definitions"].items():
            normalized = _normalize_entry(key, entry, source, diagnostics)
            if not normalized:
                continue
            contract, entry_aliases = normalized
            collision = False
            for index, alias in enumerate(entry_aliases):
                identity = bus_alias_identity(alias)
                owner = alias_owners.get(identity)
                if owner is not None and owner != contract["canonicalVlnv"]:
                    collision = True
                    add_diag(diagnostics, source["sourceFile"], "BUS_DEF_ALIAS_COLLISION", "error",
                             [key, "aliases", index], f"Alias '{identity}' is already assigned to '{owner}'.")
            if collision:
                continue
            definitions[key] = contract
            for alias in entry_aliases:
                identity = bus_alias_identity(alias)
                alias_owners[identity] = contract["canonicalVlnv"]
                if not any(bus_alias_identity(e) == identity for e in aliases):
                    aliases.append(alias)
    return {"definitions": definitions, "aliases": aliases, "diagnostics": diagnostics}


# ---------------------------------------------------------------------------
# Canonicalization
# ---------------------------------------------------------------------------


def _parse_vlnv(value: str) -> Optional[dict]:
    parts = value.split(":")
    if len(parts) != 4 or any(len(p) == 0 for p in parts):
        return None
    return dict(zip(("vendor", "library", "name", "version"), parts))


def _to_match(contract: dict, matched_by: str) -> dict:
    return {"key": contract["key"], "canonicalVlnv": contract["canonicalVlnv"], "contract": contract, "matchedBy": matched_by}


def canonicalize_bus_type(type_: Any, library: dict) -> Optional[dict]:
    if not isinstance(type_, str):
        return None
    trimmed = type_.strip()
    defs = list(library["definitions"].values())
    for d in defs:
        if d["canonicalVlnv"] == trimmed:
            return _to_match(d, "canonicalVlnv")
    short_key = short_alias_key(trimmed)
    for alias in library["aliases"]:
        if alias["kind"] == "short" and short_alias_key(alias.get("shortValue") or "") == short_key:
            contract = next((d for d in defs if d["canonicalVlnv"] == alias["canonicalVlnv"]), None)
            return _to_match(contract, "shortAlias") if contract else None
    parsed = _parse_vlnv(trimmed)
    if not parsed:
        return None
    for alias in library["aliases"]:
        if (alias["kind"] == "vlnv" and alias["vendor"] == parsed["vendor"] and alias["library"] == parsed["library"]
                and alias["name"] == parsed["name"] and (alias["version"] == "*" or alias["version"] == parsed["version"])):
            contract = next((d for d in defs if d["canonicalVlnv"] == alias["canonicalVlnv"]), None)
            return _to_match(contract, "structuredAlias") if contract else None
    return None


def normalize_interface_mode(contract: dict, mode: Any) -> Optional[str]:
    if not isinstance(mode, str):
        return None
    n = mode.strip().lower()
    mp = contract["modePolicy"]
    if n == mp["producer"]:
        return mp["producer"]
    if n == mp["consumer"]:
        return mp["consumer"]
    return mp["aliases"].get(n)


def is_consumer_interface(contract: dict, mode: Any) -> bool:
    return normalize_interface_mode(contract, mode) == contract["modePolicy"]["consumer"]


def is_memory_mapped_consumer(contract: dict, mode: Any) -> bool:
    return contract["interfaceKind"] == "memoryMapped" and is_consumer_interface(contract, mode)


def is_declarative_contract(contract: Optional[dict]) -> bool:
    return bool(contract) and contract.get("version") == 1


# ---------------------------------------------------------------------------
# Polarity
# ---------------------------------------------------------------------------


def resolve_default_physical_suffix(port: dict, polarity: Optional[str] = None) -> str:
    selected = polarity or (port.get("polarity") or {}).get("default")
    role = port["polarity"]["roles"][selected] if selected and port.get("polarity") else port["name"]
    return role.lower()


def port_name_candidates(port: dict) -> List[dict]:
    if not port.get("polarity"):
        return [{"suffix": port["name"], "roleSuffix": resolve_default_physical_suffix(port)}]
    default = port["polarity"]["default"]
    roles = port["polarity"]["roles"]
    other = "activeLow" if default == "activeHigh" else "activeHigh"
    candidates = [
        {"suffix": roles[default], "roleSuffix": resolve_default_physical_suffix(port, default),
         "polarity": default, "isDefaultRole": True},
        {"suffix": port["name"], "roleSuffix": resolve_default_physical_suffix(port, default),
         "polarity": default, "isDefaultRole": True},
        {"suffix": roles[other], "roleSuffix": resolve_default_physical_suffix(port, other), "polarity": other},
    ]
    seen = set()
    out = []
    for c in candidates:
        k = c["suffix"].lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(c)
    return out


def match_bus_port_role(ports: Sequence[dict], authored_name: str) -> Optional[dict]:
    n = authored_name.lower()
    for port in ports:
        if port["name"].lower() == n:
            m: Dict[str, Any] = {"port": port}
            if port.get("polarity"):
                m["polarity"] = port["polarity"]["default"]
            return m
    for port in ports:
        if not port.get("polarity"):
            continue
        for polarity in ("activeHigh", "activeLow"):
            if port["polarity"]["roles"][polarity].lower() == n:
                return {"port": port, "polarity": polarity}
    return None


def _record_role(match: Optional[dict], authored: str, roles: Dict[str, dict]) -> None:
    if not match or not match["port"].get("polarity") or not match.get("polarity"):
        return
    key = match["port"]["name"].lower()
    roles.pop(key, None)
    roles[key] = {
        "port": match["port"],
        "polarity": match["polarity"],
        "suffix": match["port"]["polarity"]["roles"][match["polarity"]],
        "isLegacyAlias": match["port"]["name"].lower() != authored.lower(),
    }


def _canonicalize_names(ports, names, roles) -> Optional[List[str]]:
    if names is None:
        return None
    result: List[str] = []
    for authored in names:
        match = match_bus_port_role(ports, authored)
        if not match:
            result.append(authored)
            continue
        name = match["port"]["name"]
        existing = next((i for i, c in enumerate(result) if c.lower() == name.lower()), -1)
        if existing >= 0:
            result.pop(existing)
        result.append(name)
        _record_role(match, authored, roles)
    return result


def _canonicalize_map(ports, entries, roles) -> Optional[Dict[str, Any]]:
    if entries is None:
        return None
    result: Dict[str, Any] = {}
    for authored, value in entries.items():
        match = match_bus_port_role(ports, authored)
        name = match["port"]["name"] if match else authored
        existing = next((k for k in result if k.lower() == name.lower()), None)
        if existing is not None:
            del result[existing]
        result[name] = value
        _record_role(match, authored, roles)
    return result


def _canonicalize_polarity_overrides(ports, overrides) -> Optional[Dict[str, str]]:
    if overrides is None:
        return None
    result: Dict[str, str] = {}
    for authored, polarity in overrides.items():
        m = match_bus_port_role(ports, authored)
        name = m["port"]["name"] if m else authored
        existing = next((k for k in result if k.lower() == name.lower()), None)
        if existing is not None:
            del result[existing]
        result[name] = polarity
    return result


def _lookup_override(overrides: Optional[Mapping[str, Any]], name: str) -> Any:
    result = None
    for k, v in (overrides or {}).items():
        if k.lower() == name.lower():
            result = v
    return result


def _has_explicit(overrides, port) -> bool:
    return any(k.lower() == port["name"].lower() for k in (overrides or {}))


def drop_legacy_quotient_overrides(ports, overrides):
    if not overrides:
        return overrides
    result = overrides
    for port in ports:
        d = port.get("derivedWidth")
        if (port.get("widthPolicy") != "derived" or not d or d.get("operation") != "divideBy"
                or "port" not in d or "divisor" not in d):
            continue
        authored = overrides.get(port["name"])
        dividend = overrides.get(d["port"])
        if isinstance(authored, str) and isinstance(dividend, str) and authored.strip() == dividend.strip():
            if result is overrides:
                result = dict(overrides)
            result.pop(port["name"], None)
    return result


def resolve_effective_port_polarity(port: dict, bus_interface: dict) -> Optional[str]:
    if not port.get("polarity"):
        return None
    override = _lookup_override(bus_interface.get("portPolarityOverrides"), port["name"])
    return override if override in ("activeHigh", "activeLow") else port["polarity"]["default"]


def resolve_interface_role(port: dict, bus_interface: dict) -> str:
    pol = resolve_effective_port_polarity(port, bus_interface)
    return port["polarity"]["roles"][pol] if pol and port.get("polarity") else port["name"]


def resolve_physical_suffix(port: dict, bus_interface: dict) -> str:
    override = _lookup_override(bus_interface.get("portNameOverrides"), port["name"])
    if isinstance(override, str):
        return override
    return resolve_default_physical_suffix(port, resolve_effective_port_polarity(port, bus_interface))


def canonicalize_bus_interface_ports(contract: dict, bus_interface: dict, bus_index: int) -> dict:
    ports = contract["ports"]
    identity_roles: Dict[str, dict] = {}
    keyed_roles: Dict[str, dict] = {}
    use_optional = _canonicalize_names(ports, bus_interface.get("useOptionalPorts"), identity_roles)
    width_overrides = drop_legacy_quotient_overrides(
        ports, _canonicalize_map(ports, bus_interface.get("portWidthOverrides"), keyed_roles))
    name_overrides = _canonicalize_map(ports, bus_interface.get("portNameOverrides"), keyed_roles)
    absent = _canonicalize_names(ports, bus_interface.get("absentPorts"), identity_roles)
    polarity_overrides = _canonicalize_polarity_overrides(ports, bus_interface.get("portPolarityOverrides"))

    roles = dict(keyed_roles)
    roles.update(identity_roles)

    merged = dict(polarity_overrides or {})
    for r in roles.values():
        if _has_explicit(polarity_overrides, r["port"]):
            continue
        if r["polarity"] == (r["port"].get("polarity") or {}).get("default"):
            continue
        merged[r["port"]["name"]] = r["polarity"]

    for r in roles.values():
        if not r["isLegacyAlias"] or not r["port"].get("polarity") or not _has_explicit(polarity_overrides, r["port"]):
            continue
        probe = dict(bus_interface)
        if merged:
            probe["portPolarityOverrides"] = merged
        if resolve_effective_port_polarity(r["port"], probe) == r["polarity"]:
            continue
        if _lookup_override(name_overrides, r["port"]["name"]) is None:
            name_overrides = dict(name_overrides or {})
            name_overrides[r["port"]["name"]] = r["suffix"]

    canonical = dict(bus_interface)

    def set_or_drop(key: str, value: Any, nonempty: bool) -> None:
        if nonempty:
            canonical[key] = value
        else:
            canonical.pop(key, None)

    set_or_drop("useOptionalPorts", use_optional, bool(use_optional))
    set_or_drop("portWidthOverrides", width_overrides, bool(width_overrides))
    set_or_drop("portNameOverrides", name_overrides, bool(name_overrides))
    set_or_drop("absentPorts", absent, bool(absent))
    set_or_drop("portPolarityOverrides", merged, bool(merged))

    mutations: List[Tuple[list, Any]] = []
    for field in ("useOptionalPorts", "portWidthOverrides", "portNameOverrides", "absentPorts", "portPolarityOverrides"):
        if bus_interface.get(field) != canonical.get(field):
            mutations.append((["busInterfaces", bus_index, field], canonical.get(field)))
    return {"busInterface": canonical, "mutations": mutations}


# ---------------------------------------------------------------------------
# Expressions & resolution
# ---------------------------------------------------------------------------


def collect_parameter_names(expression: dict) -> set:
    names: set = set()

    def visit(n: dict) -> None:
        t = n["type"]
        if t == "ParamRef":
            names.add(n["name"])
        elif t == "Unary":
            visit(n["operand"])
        elif t == "Binary":
            visit(n["left"])
            visit(n["right"])
        elif t == "Call":
            for a in n["args"]:
                visit(a)

    visit(expression)
    return names


def normalize_expression(expression: dict) -> dict:
    t = expression["type"]
    if t in ("Number", "ParamRef"):
        n = dict(expression)
    elif t == "Unary":
        n = {**expression, "operand": normalize_expression(expression["operand"])}
    elif t == "Binary":
        n = {**expression, "left": normalize_expression(expression["left"]), "right": normalize_expression(expression["right"])}
    else:
        n = {**expression, "args": [normalize_expression(a) for a in expression["args"]]}
    if not collect_parameter_names(n):
        v = wx.evaluate(n, {})
        if v is not None and math.isfinite(v):
            return {"type": "Number", "value": v}
    return n


def expressions_equal(left: Optional[dict], right: Optional[dict]) -> bool:
    if not left or not right:
        return False
    return _canon_json(normalize_expression(left)) == _canon_json(normalize_expression(right))


def _canon_json(node: dict) -> str:
    import json

    def conv(n: dict) -> dict:
        out = dict(n)
        if n["type"] == "Number":
            v = n["value"]
            out["value"] = int(v) if isinstance(v, float) and v == int(v) else v
        for k in ("operand", "left", "right"):
            if k in n:
                out[k] = conv(n[k])
        if "args" in n:
            out["args"] = [conv(a) for a in n["args"]]
        return out

    return json.dumps(conv(node), sort_keys=True)


def create_parameter_context(parameters: Sequence[dict]) -> dict:
    def raw(p: dict) -> Any:
        v = p.get("value")
        return v if v is not None else p.get("defaultValue")

    names = {p["name"] for p in parameters}
    defaults: Dict[str, float] = {}
    for p in parameters:
        v = raw(p)
        if _is_number(v):
            defaults[p["name"]] = v
    for _ in range(len(parameters)):
        changed = False
        for p in parameters:
            if p["name"] in defaults:
                continue
            v = raw(p)
            if not isinstance(v, str):
                continue
            expr = wx.parse(v)
            resolved = wx.evaluate(expr, defaults) if expr else None
            if resolved is not None and math.isfinite(resolved):
                defaults[p["name"]] = resolved
                changed = True
        if not changed:
            break
    domains: Dict[str, List[float]] = {}
    for p in parameters:
        allowed = [v for v in (p.get("allowedValues") or []) if _is_number(v)]
        if allowed:
            domains[p["name"]] = list(allowed)
        elif p["name"] in defaults:
            domains[p["name"]] = [defaults[p["name"]]]
    return {"names": names, "defaults": defaults, "domains": domains}


def resolve_parameter_defaults(parameters: Sequence[dict]) -> Dict[str, float]:
    return dict(create_parameter_context(parameters)["defaults"])


def _valid_number(value: float, minimum: float) -> bool:
    return _is_safe_int(value) and value >= minimum and value <= MAX_SAFE_INTEGER


def _int_if_whole(v: float) -> Any:
    return int(v) if isinstance(v, float) and v == int(v) else v


def resolve_numeric_value(raw: Any, context: dict, minimum: float = 1) -> dict:
    if _is_number(raw):
        if _valid_number(raw, minimum):
            return {"state": "concrete", "value": _int_if_whole(raw)}
        return {"state": "invalid", "reason": f"Expected a safe integer greater than or equal to {minimum}."}
    if not isinstance(raw, str):
        return {"state": "unresolved", "reason": "No numeric value was declared."}
    parsed = wx.parse(raw)
    if not parsed:
        return {"state": "invalid", "reason": f"Invalid width expression '{raw}'."}
    expression = normalize_expression(parsed)
    unknown = [n for n in collect_parameter_names(expression) if n not in context["names"]]
    if unknown:
        return {"state": "unresolved", "expression": expression,
                "reason": f"Undeclared parameter{'' if len(unknown) == 1 else 's'}: {', '.join(unknown)}."}
    value = wx.evaluate(expression, dict(context["defaults"]))
    if value is None:
        return {"state": "symbolic", "expression": expression, "reason": "No concrete parameter default is available."}
    if not _valid_number(value, minimum):
        return {"state": "invalid", "expression": expression,
                "reason": f"Expression must resolve to a safe integer greater than or equal to {minimum}."}
    return {"state": "concrete", "value": _int_if_whole(value), "expression": expression}


def resolve_numeric_expression(expression: dict, context: dict, minimum: float = 1) -> dict:
    normalized = normalize_expression(expression)
    unknown = [n for n in collect_parameter_names(normalized) if n not in context["names"]]
    if unknown:
        return {"state": "unresolved", "expression": normalized, "reason": "Expression is unresolved."}
    value = wx.evaluate(normalized, dict(context["defaults"]))
    if value is None:
        return {"state": "symbolic", "expression": normalized}
    if not _valid_number(value, minimum):
        return {"state": "invalid", "expression": normalized, "reason": "Expression is not a valid integer."}
    return {"state": "concrete", "value": _int_if_whole(value), "expression": normalized}


def numeric_expression(value: dict) -> Optional[dict]:
    if value.get("expression"):
        return value["expression"]
    return {"type": "Number", "value": value["value"]} if value.get("value") is not None else None


def binary_expression(op: str, left: dict, right: dict) -> Optional[dict]:
    le, re_ = numeric_expression(left), numeric_expression(right)
    if le and re_:
        return normalize_expression({"type": "Binary", "op": op, "left": le, "right": re_})
    return None


def evaluate_resolved(value: Optional[dict], parameters: Mapping[str, float]) -> Optional[float]:
    if not value:
        return None
    if value.get("expression"):
        return wx.evaluate(value["expression"], dict(parameters))
    return value.get("value")


def parameter_expression(value: Optional[dict]) -> Optional[dict]:
    if (value and _is_number(value.get("value")) and value.get("expression")
            and wx.contains_param_ref(value["expression"])):
        return value["expression"]
    return None


def uses_function_call(expression: dict) -> bool:
    t = expression["type"]
    if t == "Call":
        return True
    if t == "Unary":
        return uses_function_call(expression["operand"])
    if t == "Binary":
        return uses_function_call(expression["left"]) or uses_function_call(expression["right"])
    return False


def _is_numeric_value(value: Optional[dict]) -> bool:
    return bool(value) and (_is_number(value.get("value")) or "expression" in value)


def _unresolved_from(values: Sequence[Optional[dict]]) -> dict:
    if any(v is not None and v.get("state") == "invalid" for v in values):
        return {"state": "invalid", "reason": "A derivation operand is invalid."}
    if any(v is None or v.get("state") == "unresolved" for v in values):
        return {"state": "unresolved", "reason": "A derivation operand is unresolved."}
    return {"state": "symbolic", "reason": "A derivation remains symbolic."}


def derive_operation(op: dict, port_widths: Mapping[str, dict], properties: Mapping[str, dict],
                     context: dict, minimum: float) -> dict:
    operand = None
    if op.get("port"):
        operand = port_widths.get(op["port"])
    elif op.get("property"):
        prop = properties.get(op["property"])
        operand = prop if _is_numeric_value(prop) else None
    name = op["operation"]
    if name == "copyPort":
        return operand or {"state": "unresolved", "reason": "The source port is unresolved."}
    if name == "multiplyBy":
        multiplier = {"state": "concrete", "value": op["multiplier"]}
        expr = operand and binary_expression("*", operand, multiplier)
        return resolve_numeric_expression(expr, context, minimum) if expr else _unresolved_from([operand])
    if name == "divideBy":
        if "divisorProperty" in op:
            divisor = properties.get(op["divisorProperty"])
        else:
            divisor = {"state": "concrete", "value": op["divisor"]}
        nd = divisor if _is_numeric_value(divisor) else None
        expr = operand and nd and binary_expression("/", operand, nd)
        return resolve_numeric_expression(expr, context, minimum) if expr else _unresolved_from([operand, nd])
    if name == "multiplyProperties":
        left_name, right_name = op["properties"]
        left, right = properties.get(left_name), properties.get(right_name)
        nl = left if _is_numeric_value(left) else None
        nr = right if _is_numeric_value(right) else None
        expr = nl and nr and binary_expression("*", nl, nr)
        return resolve_numeric_expression(expr, context, minimum) if expr else _unresolved_from([nl, nr])
    if name in ("ceilLog2", "bitsForMaximum"):
        if not operand:
            return {"state": "unresolved", "reason": "The logarithm operand is unresolved."}
        argument = numeric_expression(operand)
        if name == "bitsForMaximum" and argument:
            argument = {"type": "Binary", "op": "+", "left": argument, "right": {"type": "Number", "value": 1}}
        expr = {"type": "Call", "fn": "clog2", "args": [argument]} if argument else None
        return resolve_numeric_expression(expr, context, minimum) if expr else _unresolved_from([operand])
    if name == "maxEncodableValue":
        if operand is None or operand.get("value") is None or operand.get("state") != "concrete":
            return _unresolved_from([operand])
        return resolve_numeric_value(2 ** operand["value"] - 1, context, minimum)
    return {"state": "unresolved", "reason": "Unknown operation."}


def _same_resolution(left: Optional[dict], right: Optional[dict]) -> bool:
    import json

    def enc(v: Optional[dict]) -> str:
        if v is None:
            return "null"
        out = {k: (_canon_json(x) if k == "expression" else x) for k, x in v.items()}
        return json.dumps(out, sort_keys=True, default=str)

    return enc(left) == enc(right)


def _resolve_to_fixpoint(max_passes: int, update_pass) -> None:
    for _ in range(max_passes):
        if not update_pass():
            return


def is_port_active(port: dict, bus_interface: dict) -> bool:
    absent = {n.lower() for n in (bus_interface.get("absentPorts") or [])}
    if port["name"].lower() in absent:
        return False
    if port["presence"] == "required":
        return True
    selected = {n.lower() for n in (bus_interface.get("useOptionalPorts") or [])}
    return port["name"].lower() in selected


def _reverse_direction(d: Optional[str]) -> Optional[str]:
    return {"in": "out", "out": "in"}.get(d or "")


def build_active_ports(contract: dict, bus_interface: dict, normalized_mode: Optional[str],
                       port_widths: Mapping[str, dict]) -> List[dict]:
    consumer = normalized_mode == contract["modePolicy"]["consumer"]
    out = []
    for port in contract["ports"]:
        if not is_port_active(port, bus_interface):
            continue
        pol = resolve_effective_port_polarity(port, bus_interface)
        p = dict(port)
        if pol:
            p["effectivePolarity"] = pol
        p["interfaceRole"] = resolve_interface_role(port, bus_interface)
        p["physicalSuffix"] = resolve_physical_suffix(port, bus_interface)
        p["needsPolarityInversion"] = pol == "activeLow"
        eff = _reverse_direction(port.get("direction")) if consumer else port.get("direction")
        if eff is not None:
            p["effectiveDirection"] = eff
        p["effectiveWidth"] = port_widths[port["name"]]
        out.append(p)
    return out


def _semantic_value(raw: Any, decl: dict, context: dict) -> dict:
    if decl["type"] == "integer":
        if _is_number(raw) or isinstance(raw, str):
            return resolve_numeric_value(raw, context, decl.get("minimum", MIN_SAFE_INTEGER))
        return {"state": "invalid", "reason": "Expected an integer or integer expression."}
    if decl["type"] == "boolean":
        if isinstance(raw, bool):
            return {"state": "concrete", "value": raw}
        return {"state": "invalid", "reason": "Expected a boolean value."}
    if isinstance(raw, str):
        return {"state": "concrete", "value": raw}
    return {"state": "invalid", "reason": "Expected a string value."}


def resolve_properties(contract: dict, bus_interface: dict, port_widths: Mapping[str, dict],
                       context: dict, bus_index: int, diagnostics: List[dict]) -> Dict[str, dict]:
    resolved: Dict[str, dict] = {}
    authored = bus_interface.get("interfaceProperties") or {}
    name_ = bus_interface.get("name")
    if is_declarative_contract(contract):
        for n in authored:
            if n not in contract["interfaceProperties"]:
                diagnostics.append({
                    "code": "BUS_UNKNOWN_INTERFACE_PROPERTY", "ruleId": "BUS_UNKNOWN_INTERFACE_PROPERTY",
                    "severity": "error", "state": "invalid", "interfaceName": name_,
                    "path": ["busInterfaces", bus_index, "interfaceProperties", n],
                    "message": f"Unknown interface property '{n}'. Valid properties: {', '.join(contract['interfaceProperties'])}.",
                })
    for n, decl in contract["interfaceProperties"].items():
        if n in authored:
            value = _semantic_value(authored[n], decl, context)
            resolved[n] = value
            if value["state"] != "concrete":
                diagnostics.append({
                    "code": "BUS_INTERFACE_PROPERTY_VALUE", "ruleId": "BUS_INTERFACE_PROPERTY_VALUE",
                    "severity": "error", "state": value["state"], "interfaceName": name_,
                    "path": ["busInterfaces", bus_index, "interfaceProperties", n],
                    "message": f"Interface property '{n}' is invalid: {value.get('reason') or 'the value could not be resolved'}",
                })
        elif decl.get("default") is not None:
            resolved[n] = _semantic_value(decl["default"], decl, context)
        else:
            resolved[n] = {"state": "unresolved", "reason": "The property is not declared."}

    def derives_from_inactive(derive: dict) -> bool:
        if "port" not in derive:
            return False
        port = next((p for p in contract["ports"] if p["name"] == derive["port"]), None)
        return port is not None and not is_port_active(port, bus_interface)

    def update() -> bool:
        changed = False
        for n, decl in contract["interfaceProperties"].items():
            if n in authored or decl.get("default") is not None or not decl.get("derive") or derives_from_inactive(decl["derive"]):
                continue
            nxt = derive_operation(decl["derive"], port_widths, resolved, context, decl.get("minimum", MIN_SAFE_INTEGER))
            if not _same_resolution(nxt, resolved.get(n)):
                resolved[n] = nxt
                changed = True
        return changed

    _resolve_to_fixpoint(len(contract["interfaceProperties"]), update)

    for n, decl in contract["interfaceProperties"].items():
        value = resolved.get(n)
        if not value or value["state"] != "concrete":
            continue
        v = value.get("value")
        invalid = (
            (_is_number(v) and ((decl.get("minimum") is not None and v < decl["minimum"])
                                or (decl.get("maximum") is not None and v > decl["maximum"])))
            or (decl.get("allowedValues") is not None and v not in decl["allowedValues"])
        )
        if invalid:
            resolved[n] = {**value, "state": "invalid", "reason": "Value violates its declaration."}
            diagnostics.append({
                "code": "BUS_INTERFACE_PROPERTY_VALUE", "ruleId": "BUS_INTERFACE_PROPERTY_VALUE",
                "severity": "error", "state": "invalid", "interfaceName": name_,
                "path": ["busInterfaces", bus_index, "interfaceProperties", n],
                "message": f"Interface property '{n}' violates its contract declaration.",
            })
    return resolved


# ---------------------------------------------------------------------------
# Data lanes
# ---------------------------------------------------------------------------


def data_lane_kind(contract: Optional[dict]) -> str:
    return "symbol" if contract and "dataBitsPerSymbol" in contract["interfaceProperties"] else "byte"


def resolve_data_lane(resolution: dict, bus_interface: dict) -> dict:
    contract = resolution["match"]["contract"] if resolution.get("match") else None
    kind = data_lane_kind(contract)
    if kind == "byte":
        return {"kind": kind, "width": BYTE_LANE_WIDTH}
    prop = resolution["properties"].get("dataBitsPerSymbol")
    expression = parameter_expression(prop)
    if expression and not uses_function_call(expression):
        code, _ = wx.serialize(expression, "canonical")
        return {"kind": kind, "width": code if expression["type"] == "ParamRef" else f"({code})"}
    resolved_width = prop.get("value") if prop else None
    if _is_number(resolved_width):
        return {"kind": "symbol", "width": resolved_width}
    authored = (bus_interface.get("interfaceProperties") or {}).get("dataBitsPerSymbol")
    return {"kind": kind, "width": authored if (_is_number(authored) or isinstance(authored, str)) else BYTE_LANE_WIDTH}


# ---------------------------------------------------------------------------
# Constraint evaluation
# ---------------------------------------------------------------------------


def _numeric_property(properties: Mapping[str, dict], name: str) -> Optional[dict]:
    p = properties.get(name)
    if not p:
        return None
    return p if (_is_number(p.get("value")) or "expression" in p) else None


def _relation_state(values: Sequence[dict]) -> str:
    for s in ("invalid", "unresolved", "symbolic"):
        if any(v["state"] == s for v in values):
            return s
    return "concrete"


def _value_at(value: Optional[dict], parameters: Mapping[str, float]) -> Optional[float]:
    e = evaluate_resolved(value, parameters)
    return e if e is not None and math.isfinite(e) else None


def _constraint_values(c: dict, inp: dict) -> List[dict]:
    values: List[dict] = []

    def add_port(n: Any) -> None:
        if isinstance(n, str) and inp["portWidths"].get(n):
            values.append(inp["portWidths"][n])

    def add_prop(n: Any) -> None:
        if isinstance(n, str):
            v = _numeric_property(inp["properties"], n)
            if v:
                values.append(v)

    if "port" in c:
        add_port(c["port"])
    if c["kind"] == "portWidthQuotient":
        add_port(c["dividendPort"])
    if c["kind"] == "portWidthsEqual":
        for n in c["ports"]:
            add_port(n)
    if "property" in c:
        add_prop(c["property"])
    if c["kind"] == "productEqualsPort":
        for n in c["properties"]:
            add_prop(n)
    return values


def _active_names(inp: dict) -> set:
    return {p["name"] for p in inp["activePorts"]}


def _structurally_proven(c: dict, inp: dict) -> bool:
    k = c["kind"]
    if k == "portWidthsEqual":
        active = _active_names(inp)
        ports = [n for n in c["ports"] if n in active]
        exprs = [numeric_expression(inp["portWidths"][n]) for n in ports]
        return len(exprs) >= 2 and all(expressions_equal(e, exprs[0]) for e in exprs)
    if k == "portWidthQuotient":
        if c["port"] not in _active_names(inp):
            return True
        target = inp["portWidths"][c["port"]]
        dividend = inp["portWidths"][c["dividendPort"]]
        expected = binary_expression("/", dividend, {"state": "concrete", "value": c["divisor"]})
        return expressions_equal(numeric_expression(target), expected)
    if k == "productEqualsPort":
        left = _numeric_property(inp["properties"], c["properties"][0])
        right = _numeric_property(inp["properties"], c["properties"][1])
        expected = binary_expression("*", left, right) if left and right else None
        return expressions_equal(numeric_expression(inp["portWidths"][c["port"]]), expected)
    if k == "propertyFitsPort":
        derive = (inp["contract"]["interfaceProperties"].get(c["property"]) or {}).get("derive")
        return (c["property"] not in (inp["busInterface"].get("interfaceProperties") or {})
                and bool(derive) and derive.get("operation") == "maxEncodableValue" and derive.get("port") == c["port"])
    return False


def _evaluate_relation(c: dict, inp: dict, parameters: Mapping[str, float]) -> dict:
    active = _active_names(inp)
    port = inp["portWidths"].get(c.get("port") or "") if "port" in c else None
    prop = _numeric_property(inp["properties"], c.get("property") or "") if "property" in c else None
    subject = port or prop
    k = c["kind"]
    if k == "range":
        v = _value_at(subject, parameters)
        if v is None:
            return {"valid": None}
        return {"valid": (c.get("minimum") is None or v >= c["minimum"]) and (c.get("maximum") is None or v <= c["maximum"])}
    if k == "allowedValues":
        v = _value_at(subject, parameters)
        return {"valid": None} if v is None else {"valid": v in c["values"]}
    if k == "multipleOf":
        v = _value_at(subject, parameters)
        return {"valid": None} if v is None else {"valid": v % c["value"] == 0}
    if k == "powerOfTwo":
        v = _value_at(subject, parameters)
        if v is None:
            return {"valid": None}
        ok = float(v).is_integer() and v > 0 and (int(v) & (int(v) - 1)) == 0 \
            and (c.get("minimum") is None or v >= c["minimum"]) and (c.get("maximum") is None or v <= c["maximum"])
        return {"valid": ok}
    if k == "portWidthsEqual":
        names = [n for n in c["ports"] if n in active]
        if len(names) < 2:
            return {"valid": True}
        values = [_value_at(inp["portWidths"].get(n), parameters) for n in names]
        if any(v is None for v in values):
            return {"valid": None}
        return {"valid": all(v == values[0] for v in values), "suggestedValue": values[0]}
    if k == "portWidthQuotient":
        if c["port"] not in active:
            return {"valid": True}
        target = _value_at(inp["portWidths"].get(c["port"]), parameters)
        dividend = _value_at(inp["portWidths"].get(c["dividendPort"]), parameters)
        if target is None or dividend is None:
            return {"valid": None}
        expected = dividend / c["divisor"]
        return {"valid": target == expected, "suggestedValue": expected}
    if k == "productEqualsPort":
        names = c["properties"]
        target = _value_at(inp["portWidths"].get(c["port"]), parameters)
        left = _value_at(_numeric_property(inp["properties"], names[0]), parameters)
        right = _value_at(_numeric_property(inp["properties"], names[1]), parameters)
        if target is None or left is None or right is None:
            return {"valid": None}
        return {"valid": target == left * right, "suggestedValue": left * right}
    if k == "portPresenceRequires":
        if c["port"] not in active:
            return {"valid": True}
        return {"valid": all(n in active for n in c["requires"])}
    if k == "propertyRequiredWhenPortPresent":
        if c["port"] not in active:
            return {"valid": True}
        v = inp["properties"].get(c["property"])
        return {"valid": v is not None and v["state"] not in ("unresolved", "invalid")}
    if k == "propertyFitsPort":
        if c["port"] not in active:
            return {"valid": True}
        width = _value_at(inp["portWidths"].get(c["port"]), parameters)
        maximum = _value_at(_numeric_property(inp["properties"], c["property"]), parameters)
        if width is None or maximum is None:
            return {"valid": None}
        return {"valid": 0 <= maximum <= 2 ** width - 1, "suggestedValue": 2 ** width - 1}
    return {"valid": None}


def _constraint_path(c: dict, inp: dict) -> list:
    if c.get("property"):
        return ["busInterfaces", inp["busIndex"], "interfaceProperties", c["property"]]
    if c.get("port"):
        return ["busInterfaces", inp["busIndex"], "portWidthOverrides", c["port"]]
    if c["kind"] == "portWidthsEqual" and c["ports"]:
        return ["busInterfaces", inp["busIndex"], "portWidthOverrides", c["ports"][0]]
    return ["busInterfaces", inp["busIndex"], "type"]


def _diagnostic_for(c: dict, inp: dict, state: str, suggested: Optional[float] = None) -> dict:
    d = {
        "code": c["code"], "ruleId": c["ruleId"], "severity": c["severity"], "state": state,
        "interfaceName": inp["busInterface"].get("name"), "path": _constraint_path(c, inp),
        "message": c.get("message") or f"{c['ruleId']} is not satisfied.",
    }
    if suggested is not None and _is_safe_int(suggested):
        d["suggestedValue"] = _int_if_whole(suggested)
    return d


def _enumerate_domains(names: Sequence[str], context: dict):
    domains = [context["domains"].get(n) for n in names]
    if any(d is None for d in domains):
        return None
    out: List[Dict[str, float]] = []

    def visit(i: int, values: Dict[str, float]) -> None:
        if i == len(names):
            out.append(dict(values))
            return
        for v in domains[i] or []:
            values[names[i]] = v
            visit(i + 1, values)

    visit(0, {})
    return out


def evaluate_contract_constraints(inp: dict) -> List[dict]:
    diagnostics: List[dict] = []
    for c in inp["contract"]["constraints"]:
        if c.get("port") and c["port"] not in _active_names(inp):
            continue
        values = _constraint_values(c, inp)
        state = _relation_state(values)
        if state == "invalid":
            diagnostics.append(_diagnostic_for(c, inp, "invalid"))
            continue
        if _structurally_proven(c, inp):
            continue
        default_result = _evaluate_relation(c, inp, inp["parameterContext"]["defaults"])
        if default_result["valid"] is False:
            diagnostics.append(_diagnostic_for(c, inp, "concrete", default_result.get("suggestedValue")))
        names: List[str] = []
        for v in values:
            if v.get("expression"):
                for n in collect_parameter_names(v["expression"]):
                    if n not in names:
                        names.append(n)
        if not names:
            if default_result["valid"] is None:
                diagnostics.append(_diagnostic_for(c, inp, state))
            continue
        domain_size = 1
        for n in names:
            domain_size *= len(inp["parameterContext"]["domains"].get(n) or [])
        if domain_size > 256:
            diagnostics.append({
                "code": "CONFORMANCE_DOMAIN_NOT_EXHAUSTIVE", "ruleId": c["ruleId"], "severity": "warning",
                "state": "unresolved", "interfaceName": inp["busInterface"].get("name"),
                "path": _constraint_path(c, inp),
                "message": f"{c['ruleId']} references {domain_size} allowed-value combinations; the limit is 256.",
            })
            continue
        combos = _enumerate_domains(names, inp["parameterContext"])
        if combos is None:
            if default_result["valid"] is None:
                diagnostics.append(_diagnostic_for(c, inp, "unresolved"))
            continue
        if default_result["valid"] is not False and any(
                _evaluate_relation(c, inp, combo)["valid"] is False for combo in combos):
            diagnostics.append(_diagnostic_for(c, inp, "concrete"))
    return diagnostics


# ---------------------------------------------------------------------------
# Interface resolution
# ---------------------------------------------------------------------------


def _equivalent(left: dict, right: dict) -> bool:
    if left["state"] == "concrete" and right["state"] == "concrete":
        return left["value"] == right["value"]
    return expressions_equal(left.get("expression"), right.get("expression"))


def _policy_diagnostic(code: str, bus_interface: dict, bus_index: int, port_name: str, expected: dict) -> dict:
    d = {
        "code": code, "ruleId": code, "severity": "error", "state": "invalid",
        "interfaceName": bus_interface.get("name"),
        "path": ["busInterfaces", bus_index, "portWidthOverrides", port_name],
        "message": f"{port_name} must match its {'fixed' if code == 'BUS_FIXED_WIDTH_OVERRIDE' else 'derived'} contract width.",
    }
    if expected.get("value") is not None:
        d["suggestedValue"] = expected["value"]
    return d


def _linked_override_diagnostic(contract: dict, port: dict, bus_interface: dict, bus_index: int, expected: dict):
    rid = port.get("overrideConstraintRuleId")
    if not rid:
        return None
    c = next((x for x in contract["constraints"] if x.get("ruleId") == rid), None)
    if not c:
        return None
    d = {
        "code": c["code"], "ruleId": c["ruleId"], "severity": c["severity"], "state": "invalid",
        "interfaceName": bus_interface.get("name"),
        "path": ["busInterfaces", bus_index, "portWidthOverrides", port["name"]],
        "message": c.get("message") or f"{c['ruleId']} is not satisfied.",
    }
    if expected.get("value") is not None:
        d["suggestedValue"] = expected["value"]
    return d


_POLARITY_MESSAGES = {
    "unknownPort": lambda n: f"Port polarity override '{n}' is not declared by this bus contract.",
    "portNotConfigurable": lambda n: f"Port '{n}' does not declare configurable polarity in this bus contract.",
    "invalidValue": lambda n: f"Port polarity override '{n}' must be 'activeHigh' or 'activeLow'.",
}


def _empty_resolution() -> dict:
    return {"match": None, "canonicalBusInterface": None, "normalizedMode": None, "authoredPortWidths": {},
            "authoredProperties": {}, "portWidths": {}, "properties": {}, "activePorts": [], "diagnostics": []}


def resolve_bus_interface(bus_interface: dict, bus_index: int, parameters: Sequence[dict], library: dict) -> dict:
    match = canonicalize_bus_type(bus_interface.get("type"), library)
    if not match:
        return _empty_resolution()
    contract = match["contract"]
    canonical = canonicalize_bus_interface_ports(contract, bus_interface, bus_index)["busInterface"]
    diagnostics: List[dict] = []
    normalized_mode = normalize_interface_mode(contract, canonical.get("mode"))
    if not normalized_mode:
        diagnostics.append({
            "code": "BUS_INTERFACE_MODE", "ruleId": "BUS_INTERFACE_MODE", "severity": "error", "state": "invalid",
            "interfaceName": canonical.get("name"), "path": ["busInterfaces", bus_index, "mode"],
            "message": (f"Mode '{canonical['mode']}' is not declared by {contract['canonicalVlnv']}."
                        if isinstance(canonical.get("mode"), str) else f"Mode is required by {contract['canonicalVlnv']}."),
        })
    context = create_parameter_context(parameters)
    overrides = canonical.get("portWidthOverrides") or {}
    port_widths: Dict[str, dict] = {}
    for port in contract["ports"]:
        raw = overrides[port["name"]] if port["widthPolicy"] == "root" and port["name"] in overrides else port.get("width", 1)
        port_widths[port["name"]] = resolve_numeric_value(raw, context)

    def is_active(name: str) -> bool:
        p = next((c for c in contract["ports"] if c["name"] == name), None)
        return p is not None and is_port_active(p, canonical)

    for c in contract["constraints"]:
        if c["kind"] != "portWidthsEqual":
            continue
        source = next((n for n in c["ports"] if is_active(n)), None)
        if source is None:
            continue
        for n in c["ports"]:
            if not is_active(n):
                port_widths[n] = port_widths[source]

    properties = resolve_properties(contract, canonical, port_widths, context, bus_index, diagnostics)

    def update() -> bool:
        changed = False
        for port in contract["ports"]:
            if port["widthPolicy"] != "derived" or not port.get("derivedWidth"):
                continue
            nxt = derive_operation(port["derivedWidth"], port_widths, properties, context, 1)
            if not _same_resolution(nxt, port_widths.get(port["name"])):
                port_widths[port["name"]] = nxt
                changed = True
        return changed

    _resolve_to_fixpoint(len(contract["ports"]), update)

    for port in contract["ports"]:
        if port["widthPolicy"] == "root":
            continue
        if not is_port_active(port, canonical):
            continue
        expected = port_widths[port["name"]]
        if port["name"] not in overrides:
            continue
        authored = resolve_numeric_value(overrides[port["name"]], context)
        if not _equivalent(authored, expected):
            code = "BUS_FIXED_WIDTH_OVERRIDE" if port["widthPolicy"] == "fixed" else "BUS_DERIVED_WIDTH_OVERRIDE"
            diagnostics.append(_policy_diagnostic(code, canonical, bus_index, port["name"], expected))
            linked = _linked_override_diagnostic(contract, port, canonical, bus_index, expected)
            if linked:
                diagnostics.append(linked)
        port_widths[port["name"]] = authored

    for port_name, polarity in (canonical.get("portPolarityOverrides") or {}).items():
        port = next((c for c in contract["ports"] if c["name"].lower() == port_name.lower()), None)
        rejection = None
        if not port:
            rejection = "unknownPort"
        elif not port.get("polarity"):
            rejection = "portNotConfigurable"
        elif polarity not in ("activeHigh", "activeLow"):
            rejection = "invalidValue"
        if rejection:
            diagnostics.append({
                "code": "BUS_PORT_POLARITY_OVERRIDE", "ruleId": "BUS_PORT_POLARITY_OVERRIDE", "severity": "error",
                "state": "invalid", "interfaceName": canonical.get("name"),
                "path": ["busInterfaces", bus_index, "portPolarityOverrides", port_name],
                "message": _POLARITY_MESSAGES[rejection](port_name),
            })

    active_ports = build_active_ports(contract, canonical, normalized_mode, port_widths)
    active_names = {p["name"] for p in active_ports}
    for port in contract["ports"]:
        width = port_widths[port["name"]]
        if (port["name"] in active_names and width["state"] == "invalid"
                and not any(d["path"] and d["path"][-1] == port["name"] for d in diagnostics)):
            diagnostics.append({
                "code": "BUS_PORT_WIDTH_INVALID", "ruleId": "BUS_PORT_WIDTH_INVALID", "severity": "error",
                "state": "invalid", "interfaceName": canonical.get("name"),
                "path": ["busInterfaces", bus_index, "portWidthOverrides", port["name"]],
                "message": width.get("reason") or f"Port '{port['name']}' has an invalid width.",
            })

    diagnostics.extend(evaluate_contract_constraints({
        "contract": contract, "busInterface": canonical, "busIndex": bus_index, "parameters": parameters,
        "parameterContext": context, "portWidths": port_widths, "properties": properties, "activePorts": active_ports,
    }))
    return {
        "match": match, "canonicalBusInterface": canonical, "normalizedMode": normalized_mode,
        "authoredPortWidths": dict(overrides), "authoredProperties": dict(canonical.get("interfaceProperties") or {}),
        "portWidths": port_widths, "properties": properties, "activePorts": active_ports, "diagnostics": diagnostics,
    }


def validate_bus_interfaces(bus_interfaces: Sequence[dict], parameters: Sequence[dict], library: dict) -> List[dict]:
    diagnostics: List[dict] = []
    for index, bi in enumerate(bus_interfaces):
        resolution = resolve_bus_interface(bi, index, parameters, library)
        diagnostics.extend(resolution["diagnostics"])
        if not bi.get("memoryMapRef"):
            continue
        count = (bi.get("array") or {}).get("count")
        supported = (
            resolution["match"] is not None
            and is_memory_mapped_consumer(resolution["match"]["contract"], bi.get("mode"))
            and (count is None or count <= 1)
        )
        if not supported:
            diagnostics.append({
                "code": "BUS_MEMORY_MAP_UNSUPPORTED", "ruleId": "BUS_MEMORY_MAP_UNSUPPORTED", "severity": "error",
                "state": "invalid", "interfaceName": bi.get("name"),
                "path": ["busInterfaces", index, "memoryMapRef"],
                "message": f"Interface '{bi.get('name')}' cannot expose a memory map in its current type and mode.",
            })
    return diagnostics


# ---------------------------------------------------------------------------
# Name sets & observed ports
# ---------------------------------------------------------------------------


def reconstruct_bus_port_name_set(iface: dict, library: dict) -> Optional[set]:
    if iface.get("conduitPorts"):
        return None
    probe = dict(iface)
    probe["mode"] = iface.get("mode") or ""
    resolution = resolve_bus_interface(probe, 0, [], library)
    if not resolution["match"]:
        physical = [p.get("physical") for p in (iface.get("rawPortMaps") or [])] + \
                   [p.get("name") for p in (iface.get("ports") or [])]
        physical = [n for n in physical if isinstance(n, str) and n]
        return {n.lower() for n in physical} if physical else None
    prefix = (iface.get("physicalPrefix") or "").lower()
    names = set()
    for port in resolution["activePorts"]:
        if port["role"] in ("clock", "reset"):
            continue
        names.add(f"{prefix}{port['physicalSuffix']}".lower())
    return names


# ---------------------------------------------------------------------------
# Vendor import helpers (observedPorts.ts / vendorProperties.ts)
# ---------------------------------------------------------------------------


def reconcile_observed_bus_ports(contract_ports: Sequence[dict], observed_ports: Sequence[dict], physical_prefix: str) -> dict:
    """Reconcile vendor-observed ports with canonical contract selections."""
    present: set = set()
    width_overrides: Dict[str, Any] = {}
    name_overrides: Dict[str, str] = {}
    polarity_overrides: Dict[str, str] = {}
    for observed in observed_ports:
        match = match_bus_port_role(contract_ports, observed["logicalName"])
        if not match:
            continue
        definition = match["port"]
        present.add(definition["name"].upper())
        ow = observed.get("width")
        if ow is not None and isinstance(definition.get("width"), (int, float)) and not isinstance(definition.get("width"), bool) \
                and (isinstance(ow, str) or ow != definition["width"]):
            width_overrides[definition["name"]] = ow
        elif ow is not None:
            width_overrides.pop(definition["name"], None)
        phys = observed["physicalName"]
        suffix = phys[len(physical_prefix):] if phys.startswith(physical_prefix) else phys
        selected = match.get("polarity") or (definition.get("polarity") or {}).get("default")
        default_suffix = resolve_default_physical_suffix(definition, selected)
        if suffix != default_suffix:
            name_overrides[definition["name"]] = suffix
        else:
            name_overrides.pop(definition["name"], None)
        if definition.get("polarity") and selected is not None and selected != definition["polarity"]["default"]:
            polarity_overrides[definition["name"]] = selected
        else:
            polarity_overrides.pop(definition["name"], None)
    use_optional = [p["name"] for p in contract_ports if p["presence"] == "optional" and p["name"].upper() in present]
    out: Dict[str, Any] = {}
    if use_optional:
        out["useOptionalPorts"] = use_optional
    if width_overrides:
        out["portWidthOverrides"] = width_overrides
    if name_overrides:
        out["portNameOverrides"] = name_overrides
    if polarity_overrides:
        out["portPolarityOverrides"] = polarity_overrides
    return out


def _parse_vendor_boolean(raw: str, prop: str, location: str) -> bool:
    if re.match(r"^(?:1|true)$", raw, re.IGNORECASE):
        return True
    if re.match(r"^(?:0|false)$", raw, re.IGNORECASE):
        return False
    raise ValueError(f"{location} has invalid boolean value '{raw}' for {prop}.")


def _parse_vendor_integer(raw: str, prop: str, location: str) -> int:
    from .jsutil import js_number

    numeric = None if raw.strip() == "" else js_number(raw)
    if numeric is not None and _is_safe_int(numeric):
        return int(numeric)
    raise ValueError(f"{location} has invalid integer value '{raw}' for {prop}.")


def import_vendor_contract_metadata(contract: dict, raw_properties: Mapping[str, str],
                                    mirrored_properties: Optional[Mapping[str, str]] = None,
                                    symbolic_properties: Optional[set] = None,
                                    static_properties: Optional[Mapping[str, str]] = None,
                                    data_width: Any = None, location: str = "") -> dict:
    warnings: List[str] = []
    is_symbol_lane = data_lane_kind(contract) == "symbol"

    def literal_or_skip(raw: Optional[str], name: str, parse):
        if raw is None:
            return None
        value_location = f"{location}.parameters.{name}"
        if not (symbolic_properties and name in symbolic_properties):
            return parse(raw, name, value_location)
        try:
            return parse(raw, name, value_location)
        except ValueError:
            fallback = (static_properties or {}).get(name)
            warnings.append(
                f"{value_location}: computed value '{raw}' is not a literal and was not imported; set {name} in the .ip.yml if needed."
                if fallback is None else
                f"{value_location}: computed value '{raw}' is not a literal; imported the static default '{fallback}'.")
            return None if fallback is None else parse(fallback, name, value_location)

    current_raw = raw_properties.get("dataBitsPerSymbol") if is_symbol_lane else None
    legacy_raw = raw_properties.get("bitsPerSymbol") if is_symbol_lane else None
    current = literal_or_skip(current_raw, "dataBitsPerSymbol", _parse_vendor_integer)
    legacy = literal_or_skip(legacy_raw, "bitsPerSymbol", _parse_vendor_integer)
    if current is not None and legacy is not None and current != legacy:
        raise ValueError(f"{location} declares conflicting dataBitsPerSymbol ('{current_raw}') and bitsPerSymbol ('{legacy_raw}').")
    for name in (mirrored_properties or {}):
        if name != "endianness" and name not in contract["interfaceProperties"]:
            raise ValueError(f"{location}.mirror.{name} is not declared by the bus contract.")

    def parse_property(raw: str, name: str, value_location: str):
        decl = contract["interfaceProperties"][name]
        if decl["type"] == "integer":
            return _parse_vendor_integer(raw, name, value_location)
        if decl["type"] == "boolean":
            return _parse_vendor_boolean(raw, name, value_location)
        return raw

    standard: Dict[str, Any] = {}
    for name in contract["interfaceProperties"]:
        if name == "dataBitsPerSymbol":
            raw = current_raw if current_raw is not None else legacy_raw
            value = current if current is not None else legacy
        else:
            raw = raw_properties.get(name)
            value = literal_or_skip(raw, name, lambda v, n, loc, _n=name: parse_property(v, _n, f"{location}.parameters.{_n}"))
        if raw is None or value is None:
            continue
        standard[name] = value
        mirrored_raw = (mirrored_properties or {}).get(name)
        if mirrored_raw is not None:
            mirrored = parse_property(mirrored_raw, name, f"{location}.mirror.{name}")
            if standard[name] != mirrored:
                raise ValueError(f"{location}.{name}: standard value '{raw}' conflicts with IPCraft mirror '{mirrored_raw}'")
    interface_properties: Dict[str, Any] = {}
    if mirrored_properties is not None:
        for name in contract["interfaceProperties"]:
            raw = mirrored_properties.get(name)
            if raw is not None:
                interface_properties[name] = parse_property(raw, name, f"{location}.mirror.{name}")
    else:
        interface_properties.update(standard)
    if (mirrored_properties is None and is_symbol_lane and "symbolsPerBeat" not in interface_properties
            and _is_number(interface_properties.get("dataBitsPerSymbol")) and _is_number(data_width)
            and data_width % interface_properties["dataBitsPerSymbol"] == 0):
        interface_properties["symbolsPerBeat"] = _int_if_whole(data_width / interface_properties["dataBitsPerSymbol"])
    ordering = raw_properties.get("firstSymbolInHighOrderBits") if is_symbol_lane else None
    first_symbol_high = literal_or_skip(ordering, "firstSymbolInHighOrderBits", _parse_vendor_boolean)
    standard_endianness = None if first_symbol_high is None else ("big" if first_symbol_high else "little")
    mirrored_endianness = (mirrored_properties or {}).get("endianness")
    if mirrored_endianness is not None and mirrored_endianness not in ("big", "little"):
        raise ValueError(f"{location}.mirror.endianness has invalid value '{mirrored_endianness}'; expected 'big' or 'little'.")
    if standard_endianness is not None and mirrored_endianness is not None and standard_endianness != mirrored_endianness:
        raise ValueError(f"{location}.endianness: standard value '{standard_endianness}' conflicts with IPCraft mirror '{mirrored_endianness}'")
    endianness = mirrored_endianness if mirrored_properties is not None else standard_endianness
    out: Dict[str, Any] = {}
    if interface_properties:
        out["interfaceProperties"] = interface_properties
    if endianness is not None:
        out["endianness"] = endianness
    if warnings:
        out["warnings"] = warnings
    return out
