"""Bus-library loading, IP-core loading and conformance checking.

Ports of ``BusLibraryService.ts``, ``generator/loadIpCore.ts`` and ``shared/busConformance.ts``.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .buscontracts import (
    bus_alias_identity,
    canonicalize_bus_type,
    canonical_vlnv_of,
    normalize_bus_library,
    validate_bus_interfaces,
)
from .domain import normalize_ip_core

RESOURCES_DIR = Path(__file__).parent / "resources"
BUS_DEFINITIONS_DIR = RESOURCES_DIR / "bus_definitions"
SCHEMAS_DIR = RESOURCES_DIR / "schemas"

IP_CORE_FORMAT_VERSIONS = ["1.0", "1.1"]
IP_CORE_FORMAT_VERSION = "1.1"
IP_CORE_LEGACY_FORMAT_VERSION = "1.0"


class SchemaValidationError(ValueError):
    def __init__(self, message: str, issues: List[dict]):
        super().__init__(message)
        self.issues = issues


_validators: Dict[str, Any] = {}


def validate_against_schema(data: Any, schema_path: str) -> Dict[str, Any]:
    """Validate ``data`` against a JSON-schema file; returns ``{valid, error?, details?}``."""
    import jsonschema

    try:
        validator = _validators.get(schema_path)
        if validator is None:
            schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
            cls = jsonschema.validators.validator_for(schema, default=jsonschema.Draft7Validator)
            validator = cls(schema)
            _validators[schema_path] = validator
        errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    except Exception as exc:  # noqa: BLE001
        return {"valid": False, "error": f"Schema validation failed: {exc}"}
    if not errors:
        return {"valid": True}
    details = []
    parts = []
    for e in errors:
        path = list(e.absolute_path)
        if e.validator == "required":
            m = re.search(r"'([^']+)' is a required property", e.message)
            if m:
                path = path + [m.group(1)]
        details.append({"path": path, "keyword": e.validator, "message": e.message})
        loc = ".".join(str(p) for p in e.absolute_path) or "(root)"
        parts.append(f"{loc}: {e.message}")
    return {"valid": False, "error": "; ".join(parts), "details": details}


def schema_issues_from_validation(result: Dict[str, Any]) -> List[dict]:
    if result.get("valid"):
        return []
    if not result.get("details"):
        return [{"code": "SCHEMA_VALIDATION", "severity": "error", "source": "schema", "path": [],
                 "message": result.get("error") or "Schema validation failed."}]
    out = []
    for d in result["details"]:
        path = d["path"]
        out.append({
            "code": "SCHEMA_" + re.sub(r"[^a-zA-Z0-9]+", "_", d["keyword"]).upper(),
            "severity": "error", "source": "schema", "path": path,
            "message": (".".join(str(p) for p in path) + ": " if path else "") + d["message"],
        })
    return out


def normalize_parameter_data_type(raw: Optional[str]) -> str:
    t = str(raw if raw is not None else "")
    t = re.sub(r"\s+range\s+.*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*\(.*\)\s*$", "", t).strip().lower()
    if t == "boolean":
        return "boolean"
    if t == "string":
        return "string"
    if t in ("natural", "positive", "unsigned"):
        return "natural"
    return "integer"


def read_ip_core_format_version(data: dict) -> Dict[str, Any]:
    declared = data.get("apiVersion")
    if declared is None:
        return {"ok": True, "version": IP_CORE_LEGACY_FORMAT_VERSION}
    if declared in IP_CORE_FORMAT_VERSIONS:
        return {"ok": True, "version": declared}
    if not isinstance(declared, str):
        return {"ok": False, "message": f"apiVersion must be a quoted string such as '{IP_CORE_FORMAT_VERSION}' "
                                        f"(found {json.dumps(declared)})."}
    return {"ok": False, "message": f"This file declares apiVersion {declared}, but this IPCraft supports up to "
                                    f"{IP_CORE_FORMAT_VERSION}. Upgrade IPCraft to open it."}


def load_ip_core_data(input_path: str, source_text: Optional[str] = None) -> dict:
    content = source_text if source_text is not None else Path(input_path).read_text(encoding="utf-8")
    parsed = yaml.safe_load(content)
    if not parsed or not isinstance(parsed, dict):
        raise ValueError("Invalid IP core YAML")
    version = read_ip_core_format_version(parsed)
    if not version["ok"]:
        raise ValueError(version["message"])
    params = parsed.get("parameters")
    if isinstance(params, list):
        for p in params:
            if isinstance(p, dict) and "dataType" in p:
                p["dataType"] = normalize_parameter_data_type(p["dataType"])
    result = validate_against_schema(parsed, str(SCHEMAS_DIR / "ip_core.schema.json"))
    if not result["valid"]:
        raise SchemaValidationError(f"IP core YAML schema validation failed: {result.get('error')}",
                                    schema_issues_from_validation(result))
    return normalize_ip_core(parsed)


# ---------------------------------------------------------------------------
# Bus library
# ---------------------------------------------------------------------------


def is_bus_def_record(parsed: Any) -> bool:
    return isinstance(parsed, dict) and any(
        isinstance(v, dict) and isinstance(v.get("ports"), list) for v in parsed.values())


def _schema_diagnostic(source_file: str, message: str) -> dict:
    return {"code": "BUS_DEF_SCHEMA_INVALID", "severity": "error", "sourceFile": source_file, "path": [], "message": message}


def load_default_sources(directory: Optional[str] = None) -> Dict[str, list]:
    d = Path(directory) if directory else BUS_DEFINITIONS_DIR
    if not d.is_dir():
        raise ValueError(f"Default bus library directory not found at {d}")
    schema_path = str(SCHEMAS_DIR / "bus_definition.schema.json")
    sources = []
    for f in sorted(p for p in d.iterdir() if p.is_file() and p.name.endswith(".yml")):
        parsed = yaml.safe_load(f.read_text(encoding="utf-8"))
        validation = validate_against_schema(parsed, schema_path)
        if not validation["valid"]:
            raise ValueError(f"Invalid bundled bus definition at {f}: {validation.get('error') or 'schema validation failed'}")
        sources.append({"sourceFile": str(f), "sourceKind": "builtin", "definitions": parsed})
    return {"sources": sources, "diagnostics": []}


def _collect_bus_def_files(dir_path: str) -> List[str]:
    files: List[str] = []
    try:
        entries = sorted(os.scandir(dir_path), key=lambda e: e.name)
    except OSError:
        return files
    for e in entries:
        if e.is_dir():
            files.extend(_collect_bus_def_files(e.path))
        elif e.is_file() and (e.name.endswith(".yml") or e.name.endswith(".yaml")) \
                and not e.name.endswith(".ip.yml") and not e.name.endswith(".mm.yml"):
            files.append(e.path)
    return files


def load_from_directories(paths: List[str], source_kind: str = "ipLocal") -> Dict[str, list]:
    schema_path = str(SCHEMAS_DIR / "bus_definition.schema.json")
    sources: List[dict] = []
    diagnostics: List[dict] = []
    for d in paths:
        for f in _collect_bus_def_files(d):
            try:
                parsed = yaml.safe_load(Path(f).read_text(encoding="utf-8"))
                if not is_bus_def_record(parsed):
                    continue
                validation = validate_against_schema(parsed, schema_path)
                if not validation["valid"]:
                    diagnostics.append(_schema_diagnostic(f, f"Invalid bus definition: {validation.get('error') or 'schema validation failed'}"))
                else:
                    sources.append({"sourceFile": f, "sourceKind": source_kind, "definitions": parsed})
            except Exception as exc:  # noqa: BLE001
                diagnostics.append(_schema_diagnostic(f, f"Could not load bus definition: {exc}"))
    return {"sources": sources, "diagnostics": diagnostics}


def _select_winning_sources(sources: List[dict]) -> List[dict]:
    winners: Dict[str, dict] = {}
    canonical_owners: Dict[str, str] = {}
    for source in sources:
        for key, entry in source["definitions"].items():
            canonical = canonical_vlnv_of(entry) if isinstance(entry, dict) else None
            prior = winners.get(key)
            prior_canonical = canonical_vlnv_of(prior["entry"]) if prior else None
            if prior_canonical:
                canonical_owners.pop(prior_canonical, None)
            if canonical:
                prior_key = canonical_owners.get(canonical)
                if prior_key is not None and prior_key != key:
                    winners.pop(prior_key, None)
                canonical_owners[canonical] = key
            winners[key] = {"source": source, "key": key, "entry": entry}
    return [{"sourceFile": w["source"]["sourceFile"], "sourceKind": w["source"]["sourceKind"],
             "definitions": {w["key"]: w["entry"]}} for w in winners.values()]


def normalize_sources(*loads: Dict[str, list]) -> dict:
    semantic: List[dict] = []
    accepted: List[dict] = []
    for load in loads:
        for source in load["sources"]:
            for key, entry in source["definitions"].items():
                candidate = {"sourceFile": source["sourceFile"], "sourceKind": source["sourceKind"], "definitions": {key: entry}}
                result = normalize_bus_library([candidate])
                if key not in result["definitions"]:
                    if source["sourceKind"] == "builtin":
                        detail = " ".join(d["message"] for d in result["diagnostics"])
                        raise ValueError(f"Invalid bundled bus definition at {source['sourceFile']}: {detail}")
                    semantic.extend(result["diagnostics"])
                    continue
                accepted.append(candidate)
    normalized = normalize_bus_library(_select_winning_sources(accepted))
    diagnostics = [d for load in loads for d in load["diagnostics"]] + semantic + normalized["diagnostics"]
    return {"definitions": normalized["definitions"], "aliases": normalized["aliases"], "diagnostics": diagnostics}


_default_sources_cache: Optional[Dict[str, list]] = None


def ipcraft_config_dir() -> str:
    """OS-specific application data directory shared with the VS Code extension."""
    import sys

    home = os.path.expanduser("~")
    if sys.platform == "win32":
        return os.path.join(os.environ.get("APPDATA") or os.path.join(home, "AppData", "Roaming"), "ipcraft")
    if sys.platform == "darwin":
        return os.path.join(home, "Library", "Application Support", "ipcraft")
    return os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config"), "ipcraft")


def vivado_interface_cache_dir(version: Optional[str] = None) -> str:
    from urllib.parse import quote

    parts = [ipcraft_config_dir(), "vivado"] + ([quote(version, safe="!~*'()")] if version else []) + ["bus_definitions"]
    return os.path.join(*parts)


def resolve_vivado_cache_version(resource_path: Optional[str], kind: str = "interfaces") -> Optional[str]:
    """Version of the Vivado cache selected by the last successful scan for this resource (or ``None``)."""
    import hashlib

    if not resource_path:
        return None
    scope = resource_path
    scope_hash = hashlib.sha256(scope.encode("utf-8")).hexdigest()
    sel_path = os.path.join(ipcraft_config_dir(), "vivado", "cache-selections", f"{scope_hash}.{kind}.json")
    try:
        selection = json.loads(Path(sel_path).read_text(encoding="utf-8"))
        if (selection.get("formatVersion") == 1 and selection.get("scope") == scope
                and selection.get("kind") == kind and selection.get("pinnedVersion") == ""):
            return selection.get("selectedVersion")
    except (OSError, ValueError):
        pass
    return None


def load_bus_library(input_path: Optional[str] = None, ip_core: Optional[dict] = None,
                     extra_dirs: Optional[List[str]] = None, include_vivado_cache: bool = True) -> dict:
    """The normalized library used for an IP core: built-ins, configured dirs and ``useBusLibrary``."""
    global _default_sources_cache
    if _default_sources_cache is None:
        _default_sources_cache = load_default_sources()
    loads = [_default_sources_cache]
    configured_dirs = list(extra_dirs or [])
    if input_path and include_vivado_cache:
        cache_dir = vivado_interface_cache_dir(resolve_vivado_cache_version(os.path.abspath(input_path)))
        if os.path.isdir(cache_dir):
            configured_dirs.append(cache_dir)
    if configured_dirs:
        loads.append(load_from_directories(configured_dirs, "configured"))
    use_lib = str((ip_core or {}).get("useBusLibrary") or "")
    if use_lib and input_path:
        loads.append(load_from_directories([os.path.abspath(os.path.join(os.path.dirname(input_path), use_lib))], "ipLocal"))
    return normalize_sources(*loads)


def bus_definitions_for_templates(library: dict) -> Dict[str, dict]:
    out = {}
    for key, contract in library["definitions"].items():
        vendor, lib, name, version = contract["canonicalVlnv"].split(":")
        entry: Dict[str, Any] = {
            "busType": {"vendor": vendor, "library": lib, "name": name, "version": version},
            "ports": [{
                "name": p["name"], "width": p.get("width"), "direction": p.get("direction"),
                "presence": p["presence"], **({"role": p["role"]} if p["role"] in ("data", "byteQualifier") else {}),
            } for p in contract["ports"]],
        }
        if contract.get("artifactSource"):
            entry["source"] = contract["artifactSource"]
        out[key] = entry
    return out


# ---------------------------------------------------------------------------
# Conformance
# ---------------------------------------------------------------------------

BUS_VLNV_CONDUIT = "ipcraft:busif:conduit:1.0"


def _is_valid_vlnv(value: Any) -> bool:
    return isinstance(value, str) and bool(re.match(r"^[^:\s]+:[^:\s]+:[^:\s]+:[^:\s]+$", value))


def check_bus_conformance(ip_core: dict, library: dict) -> dict:
    bus_interfaces = ip_core.get("busInterfaces") or []
    parameters = ip_core.get("parameters") or []
    diagnostics = validate_bus_interfaces(bus_interfaces, parameters, library)
    unresolved: List[dict] = []
    blocking_unresolved = False
    for idx, bi in enumerate(bus_interfaces):
        if canonicalize_bus_type(bi.get("type"), library):
            continue
        if bi.get("mode") == "conduit" and (bi.get("conduitPorts") or bi.get("type") == BUS_VLNV_CONDUIT
                                            or not _is_valid_vlnv(bi.get("type"))):
            continue
        if not bi.get("rawPortMaps"):
            blocking_unresolved = True
        unresolved.append({
            "code": "BUS_TYPE_UNRESOLVED", "severity": "warning", "source": "protocol",
            "path": ["busInterfaces", idx, "type"], "interfaceName": bi.get("name"),
            "message": f"Bus type '{bi.get('type')}' could not be resolved in the active bus library.",
        })
    issues = [{"code": d["code"], "severity": d["severity"], "source": "protocol", "path": d["path"],
               "message": d["message"], "interfaceName": d["interfaceName"]} for d in diagnostics] + unresolved
    seen = set()
    dedup = []
    for i in issues:
        key = f"{i['source']}|{i['code']}|{json.dumps(i['path'])}"
        if key not in seen:
            seen.add(key)
            dedup.append(i)
    return {
        "issues": dedup,
        "hasKnownErrors": any(d["severity"] == "error" and d["state"] in ("concrete", "invalid") for d in diagnostics),
        "hasUnresolved": blocking_unresolved or any(
            d["severity"] == "error" and d["state"] in ("symbolic", "unresolved") for d in diagnostics),
    }


def blocks_generation(report: dict) -> bool:
    return report["hasKnownErrors"] or report["hasUnresolved"]
