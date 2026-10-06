"""Register processing and bus-port projection (port of ``registerProcessor.ts``,
``resolvers/shadowRegisters.ts``, ``resolvers/endiannessPolicy.ts`` and
``resolvers/boundaryTransforms.ts``)."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence

from . import widthexpr as wx
from .buscontracts import (
    BYTE_LANE_WIDTH,
    _int_if_whole,
    canonicalize_bus_type,
    is_consumer_interface,
    is_memory_mapped_consumer,
    reconstruct_bus_port_name_set,
    resolve_parameter_defaults,
)
from .domain import normalize_memory_map, resolve_memory_map_imports

# Bus registry (generator/buses/builtin.ts): canonical VLNV -> (template id, library key)
BUS_REGISTRY = {
    "ipcraft:busif:axi4_lite:1.0": ("axil", "AXI4_LITE"),
    "ipcraft:busif:axi4_full:1.0": ("axi4", "AXI4_FULL"),
    "ipcraft:busif:avalon_mm:1.0": ("avmm", "AVALON_MEMORY_MAPPED"),
    "ipcraft:busif:axi_stream:1.0": ("axis", "AXI_STREAM"),
    "ipcraft:busif:avalon_st:1.0": ("avst", "AVALON_STREAMING"),
}
BUS_VLNV = {
    "AXI4_LITE": "ipcraft:busif:axi4_lite:1.0",
    "AXI4_FULL": "ipcraft:busif:axi4_full:1.0",
    "AXI_STREAM": "ipcraft:busif:axi_stream:1.0",
    "AVALON_MM": "ipcraft:busif:avalon_mm:1.0",
    "AVALON_ST": "ipcraft:busif:avalon_st:1.0",
    "CONDUIT": "ipcraft:busif:conduit:1.0",
}


def registry_normalize(type_name: str, library: dict) -> Dict[str, str]:
    match = canonicalize_bus_type(type_name, library)
    provider = BUS_REGISTRY.get(match["canonicalVlnv"]) if match else None
    if provider:
        return {"libraryKey": provider[1], "templateType": provider[0]}
    return {"libraryKey": "", "templateType": "custom"}


def get_string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and "value" in value:
        return str(value["value"])
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


# ---------------------------------------------------------------------------
# Width helpers
# ---------------------------------------------------------------------------


def resolve_string_width(s: str, param_defaults: Dict[str, float]) -> Dict[str, Any]:
    ast = wx.parse(s)
    numeric = wx.eval_width_expr(s, param_defaults)
    if numeric is None:
        numeric = 1
    if ast and not wx.contains_param_ref(ast):
        return {"numeric": numeric, "expr": None}
    return {"numeric": numeric, "expr": s}


def build_parameterized_port_types(width_expr: str) -> Dict[str, str]:
    import re

    ast = wx.parse(width_expr)
    if not ast:
        compound = bool(re.search(r"[+\-*/]", width_expr))
        fmt = f"({width_expr})" if compound else width_expr
        return {"type": f"std_logic_vector({fmt}-1 downto 0)", "sv_type": f"logic [{fmt}-1:0]"}
    is_leaf = ast["type"] in ("Number", "ParamRef")
    vhdl = wx.serialize(ast, "vhdl")[0]
    sv = wx.serialize(ast, "systemverilog")[0]
    fv = vhdl if is_leaf else f"({vhdl})"
    fs = sv if is_leaf else f"({sv})"
    return {"type": f"std_logic_vector({fv}-1 downto 0)", "sv_type": f"logic [{fs}-1:0]"}


def get_vhdl_port_type(width: int) -> str:
    return "std_logic" if width == 1 else f"std_logic_vector({width - 1} downto 0)"


def get_sv_port_type(width: int) -> str:
    return "logic" if width == 1 else f"logic [{width - 1}:0]"


def to_tcl_width_expression(expr: str, parameter_names: Sequence[str]) -> str:
    import re

    ast = wx.parse(expr)
    if not ast:
        return expr
    upper = {n.upper() for n in parameter_names}
    has_param = [False]

    def param_ref(name: str) -> str:
        u = name.upper()
        if u in upper:
            has_param[0] = True
            return f"[get_parameter_value {u}]"
        return name

    converted = wx.serialize(ast, "tcl", param_ref)[0]
    if not has_param[0]:
        return expr
    if re.match(r"^\[get_parameter_value [a-zA-Z0-9_]+\]$", converted.strip()):
        return converted
    return f"[expr {converted}]"


# ---------------------------------------------------------------------------
# Endianness policy / boundary transforms
# ---------------------------------------------------------------------------


def needs_lane_swap(endianness: str, width: Any, lane_width: Any, direction: str, is_parameterized: bool = False) -> bool:
    return (
        endianness == "big"
        and direction in ("in", "out")
        and (
            is_parameterized
            or isinstance(width, str)
            or isinstance(lane_width, str)
            or (isinstance(width, (int, float)) and isinstance(lane_width, (int, float))
                and lane_width > 0 and width > lane_width and width % lane_width == 0)
        )
    )


def needs_bit_reverse(endianness: str, width: Any, direction: str, is_parameterized: bool = False) -> bool:
    return (
        endianness == "big"
        and direction in ("in", "out")
        and (is_parameterized or (isinstance(width, (int, float)) and not isinstance(width, bool) and width > 1))
    )


def build_port_swap_projection(role: Optional[str], direction: str, width: Any, is_parameterized: bool,
                               metadata: dict) -> dict:
    if role == "data":
        return {"role": role, "swapKind": "lane", "laneWidth": metadata["laneWidth"], "laneKind": metadata["laneKind"],
                "needsSwap": needs_lane_swap(metadata["endianness"], width, metadata["laneWidth"], direction, is_parameterized)}
    if role == "byteQualifier":
        return {"role": role, "swapKind": "bit", "laneWidth": 1, "laneKind": metadata["laneKind"],
                "needsSwap": needs_bit_reverse(metadata["endianness"], width, direction, is_parameterized)}
    return {"needsSwap": False}


def build_boundary_transforms(ports: Sequence[dict], reserved_names: set) -> dict:
    unavailable = {n.lower() for n in reserved_names}
    allocated: set = set()
    transforms: List[dict] = []
    for port in ports:
        if not port["needsSwap"] and not port["needsPolarityInversion"]:
            continue
        base = f"{port['name']}_{'be' if port['needsSwap'] else 'inv'}"
        internal = base
        suffix = 2
        while internal.lower() in unavailable:
            internal = f"{base}_{suffix}"
            suffix += 1
        unavailable.add(internal.lower())
        allocated.add(internal)
        t = {
            "name": port["name"], "internalName": internal, "direction": port["direction"], "type": port["type"],
            "svType": port["svType"], "width": port["width"], "widthExpr": port["widthExpr"],
            "isParameterized": port["isParameterized"], "invert": port["needsPolarityInversion"],
        }
        if port["needsSwap"] and port.get("swapKind"):
            t["swapKind"] = port["swapKind"]
        if port["needsSwap"] and port.get("laneWidth") is not None:
            t["laneWidth"] = port["laneWidth"]
        if port["needsSwap"] and port.get("laneKind"):
            t["laneKind"] = port["laneKind"]
        transforms.append(t)
    return {"ports": transforms, "internalNames": allocated}


# ---------------------------------------------------------------------------
# Bus interface helpers
# ---------------------------------------------------------------------------


def get_bus_type_for_template(ip_core: dict, library: dict) -> str:
    first_consumer: Optional[str] = None
    for bus in ip_core.get("busInterfaces") or []:
        match = canonicalize_bus_type(get_string(bus.get("type")), library)
        contract = match["contract"] if match else None
        if not contract:
            continue
        if is_consumer_interface(contract, get_string(bus.get("mode"))):
            template_type = registry_normalize(get_string(bus.get("type")), library)["templateType"]
            if first_consumer is None:
                first_consumer = template_type
            if contract["interfaceKind"] == "memoryMapped":
                return template_type
    return first_consumer or "axil"


def has_memory_mapped_consumer_interface(ip_core: dict, library: dict) -> bool:
    for bus in ip_core.get("busInterfaces") or []:
        match = canonicalize_bus_type(get_string(bus.get("type")), library)
        if match is not None and is_memory_mapped_consumer(match["contract"], get_string(bus.get("mode"))):
            return True
    return False


def expand_bus_interfaces(ip_core: dict) -> List[dict]:
    expanded: List[dict] = []

    def base(iface: dict, name: str, prefix: str, mode: str) -> dict:
        # JavaScript `undefined` properties are absent from the serialized context.
        return {k: v for k, v in {
            "name": name,
            "type": get_string(iface.get("type")),
            "busTypeVlnv": iface.get("busTypeVlnv"),
            "rawPortMaps": iface.get("rawPortMaps"),
            "mode": mode,
            "physicalPrefix": prefix,
            "useOptionalPorts": iface.get("useOptionalPorts") or [],
            "portWidthOverrides": iface.get("portWidthOverrides") or {},
            "interfaceProperties": iface.get("interfaceProperties"),
            "portNameOverrides": iface.get("portNameOverrides"),
            "portPolarityOverrides": iface.get("portPolarityOverrides"),
            "absentPorts": iface.get("absentPorts"),
            "conduitPorts": iface.get("conduitPorts") or [],
            "associatedClock": iface.get("associatedClock"),
            "associatedReset": iface.get("associatedReset"),
            "memoryMapRef": iface.get("memoryMapRef"),
            "endianness": iface.get("endianness"),
        }.items() if v is not None}

    for iface in ip_core.get("busInterfaces") or []:
        mode = get_string(iface.get("mode")).lower()
        arr = iface.get("array")
        if arr:
            count = int(_n(arr.get("count"), 1))
            start = int(_n(arr.get("indexStart"), 0))
            for i in range(count):
                idx = start + i
                pattern = arr["namingPattern"] if arr.get("namingPattern") is not None else f"{iface.get('name')}_{{index}}"
                prefix_pattern = arr["physicalPrefixPattern"] if arr.get("physicalPrefixPattern") is not None \
                    else f"{iface.get('physicalPrefix') or ''}{{index}}_"
                expanded.append(base(iface, str(pattern).replace("{index}", str(idx), 1),
                                     str(prefix_pattern).replace("{index}", str(idx), 1), mode))
            continue
        expanded.append(base(iface, iface.get("name"), iface.get("physicalPrefix") or "", mode))
    return expanded


def _n(v: Any, fb: float) -> float:
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else fb


def get_active_bus_ports_from_definition(
    ports: Sequence[dict], use_optional_ports: Sequence[str], physical_prefix: str, mode: str,
    port_width_overrides: dict, parameters: Optional[Sequence[dict]] = None,
    port_name_overrides: Optional[dict] = None, absent_ports: Optional[Sequence[str]] = None,
    effective_directions: Optional[dict] = None,
) -> List[dict]:
    optional_set = set(use_optional_ports or [])
    absent_set = {n.upper() for n in (absent_ports or [])}
    active: List[dict] = []
    param_defaults: Dict[str, float] = {}
    for p in parameters or []:
        if p.get("name") and isinstance(p.get("value"), (int, float)) and not isinstance(p.get("value"), bool):
            param_defaults[p["name"]] = p["value"]

    for port in ports:
        logical = port["name"]
        if logical in ("ACLK", "ARESETn", "clk", "reset"):
            continue
        if logical.upper() in absent_set:
            continue
        presence = port.get("presence") or "required"
        if presence != "required" and logical not in optional_set:
            continue
        direction = (effective_directions or {}).get(logical) or port.get("direction") or "in"
        if not (effective_directions or {}).get(logical) and mode in ("slave", "sink"):
            direction = "in" if direction == "out" else "out" if direction == "in" else direction

        width: Any = port.get("width") if port.get("width") is not None else 1
        width_expr: Optional[str] = None
        if port_width_overrides and port_width_overrides.get(logical) is not None:
            override = port_width_overrides[logical]
            if isinstance(override, str):
                r = resolve_string_width(override, param_defaults)
                width, width_expr = r["numeric"], r["expr"]
            else:
                width = override
        elif isinstance(width, str):
            r = resolve_string_width(width, param_defaults)
            width, width_expr = r["numeric"], r["expr"]

        num_width = _int_if_whole(float(width))
        if width_expr is not None:
            types = build_parameterized_port_types(width_expr)
            vhdl, sv = types["type"], types["sv_type"]
        else:
            vhdl, sv = get_vhdl_port_type(num_width), get_sv_port_type(num_width)
        suffix = (port_name_overrides or {}).get(logical) or logical.lower()
        active.append({
            "logical_name": logical,
            "name": f"{physical_prefix}{suffix}",
            "direction": direction,
            "sv_direction": "input" if direction == "in" else "output" if direction == "out" else "inout",
            "width": num_width,
            "width_expr": width_expr,
            "is_parameterized": width_expr is not None,
            "default_width": num_width - 1 if width_expr is not None else None,
            "type": vhdl,
            "sv_type": sv,
            **({"role": port["role"]} if port.get("role") is not None else {}),
        })
    return active


def project_resolved_bus_ports(ports: Sequence[dict], physical_prefix: str, parameters: Sequence[dict],
                               metadata: Optional[dict] = None) -> List[dict]:
    metadata = metadata or {"endianness": "little", "laneWidth": BYTE_LANE_WIDTH, "laneKind": "byte"}
    names = [p["name"] for p in parameters]
    defaults = resolve_parameter_defaults(parameters)
    out: List[dict] = []
    for port in ports:
        if port["role"] in ("clock", "reset"):
            continue
        direction = port.get("effectiveDirection") or port.get("direction")
        if direction not in ("in", "out"):
            continue
        ew = port["effectiveWidth"]
        width_expr = None
        if ew.get("expression") and wx.contains_param_ref(ew["expression"]):
            width_expr = wx.serialize(ew["expression"], "canonical")[0]
        evaluated = ew.get("value")
        if evaluated is None and width_expr:
            evaluated = wx.eval_width_expr(width_expr, defaults)
        if evaluated is None:
            evaluated = port["width"] if isinstance(port.get("width"), (int, float)) else 1
        types = build_parameterized_port_types(width_expr) if width_expr else {
            "type": get_vhdl_port_type(evaluated), "sv_type": get_sv_port_type(evaluated)}
        proj = build_port_swap_projection(port["role"], direction, evaluated, width_expr is not None, metadata)
        p = {
            "canonicalName": port["name"],
            "name": f"{physical_prefix}{port['physicalSuffix']}",
            "interfaceRole": port["interfaceRole"],
            "physicalSuffix": port["physicalSuffix"],
            "direction": direction,
            "svDirection": "input" if direction == "in" else "output",
            "type": types["type"],
            "svType": types["sv_type"],
            "width": evaluated,
            "widthExpr": width_expr,
            "isParameterized": width_expr is not None,
            "tclWidth": to_tcl_width_expression(width_expr, names) if width_expr else str(evaluated),
            "endianness": metadata["endianness"],
            "needsPolarityInversion": port["needsPolarityInversion"],
        }
        if port.get("effectivePolarity"):
            p["effectivePolarity"] = port["effectivePolarity"]
        p.update(proj)
        out.append(p)
    return out


def _conduit_port_name_set(iface: dict) -> set:
    ports = get_active_bus_ports_from_definition(
        iface.get("conduitPorts") or [], iface.get("useOptionalPorts") or [], iface.get("physicalPrefix") or "",
        iface.get("mode") or "", iface.get("portWidthOverrides") or {}, None, iface.get("portNameOverrides"),
        iface.get("absentPorts"))
    return {str(p["name"]).lower() for p in ports}


def check_duplicate_physical_prefixes(ip_core: dict, library: dict) -> Optional[str]:
    expanded = expand_bus_interfaces(ip_core)
    name_sets = [
        _conduit_port_name_set(i) if i.get("conduitPorts") else reconstruct_bus_port_name_set(i, library)
        for i in expanded
    ]
    dups: List[str] = []
    for i in range(len(expanded)):
        for j in range(i + 1, len(expanded)):
            si, sj = name_sets[i], name_sets[j]
            if si is not None and sj is not None:
                collides = any(n in sj for n in si)
            else:
                collides = bool(expanded[i].get("physicalPrefix")) and \
                    (expanded[i].get("physicalPrefix") or "").lower() == (expanded[j].get("physicalPrefix") or "").lower()
            if collides:
                dups.append(f"'{expanded[i].get('physicalPrefix') or ''}' (shared by '{expanded[i].get('name') or ''}' "
                            f"and '{expanded[j].get('name') or ''}')")
    if dups:
        return "Duplicate physicalPrefix values would produce conflicting port names: " + ", ".join(dups)
    return None


# ---------------------------------------------------------------------------
# Registers
# ---------------------------------------------------------------------------

SW_WRITE = {"read-write", "write-only", "rw", "wo", "read-write-1-to-clear", "write-1-to-clear",
            "read-write-self-clearing", "write-self-clearing"}
HW_READ_ONLY = {"read-only", "ro"}
SW_READ = {"read-write", "rw", "read-only", "ro", "read-write-1-to-clear", "read-write-self-clearing"}


def derive_register_access(field_accesses: Sequence[str], explicit: Optional[str] = None) -> str:
    if explicit:
        return explicit
    if not field_accesses:
        return "read-write"
    if all(a in HW_READ_ONLY for a in field_accesses):
        return "read-only"
    if all(a == "write-self-clearing" for a in field_accesses):
        return "write-self-clearing"
    if all(a == "read-write-self-clearing" for a in field_accesses):
        return "read-write-self-clearing"
    sw_write = any(a in SW_WRITE for a in field_accesses)
    sw_read = any(a in SW_READ for a in field_accesses)
    if sw_write and sw_read:
        return "read-write"
    if sw_write:
        return "write-only"
    return "read-only"


def resolve_memory_maps(ip_core: dict, input_path: str) -> List[dict]:
    import os
    import warnings

    resolved, errors = resolve_memory_map_imports(ip_core.get("memoryMaps"), os.path.dirname(os.path.abspath(input_path)))
    if errors:
        warnings.warn(f"Memory map import errors (continuing with {len(resolved)} resolved): {'; '.join(errors)}")
    return [normalize_memory_map(m) for m in resolved]


def prepare_registers(ip_core: dict, input_path: str, memory_maps: Optional[List[dict]] = None) -> List[dict]:
    maps = memory_maps if memory_maps is not None else resolve_memory_maps(ip_core, input_path)
    registers: List[dict] = []

    def process(reg: dict, base_offset: int, prefix: str) -> None:
        current = base_offset + reg["offset"]
        reg_name = reg.get("name") or "REG"
        if reg.get("registers"):
            count = reg.get("count") if reg.get("count") is not None else 1
            stride = reg.get("stride") if reg.get("stride") is not None else 0
            for i in range(count):
                inst_offset = current + i * stride
                inst_prefix = f"{prefix}{reg_name}_{i}_" if count > 1 else f"{prefix}{reg_name}_"
                for child in reg["registers"]:
                    process(child, inst_offset, inst_prefix)
            return
        flat = reg.get("count") if reg.get("count") is not None else 1
        if flat > 1 and not reg.get("__expanded_array_instance"):
            stride = reg.get("stride") if reg.get("stride") is not None else 4
            for i in range(flat):
                process({**reg, "name": f"{reg_name}_{i}", "offset": reg["offset"] + i * stride, "count": 1,
                         "__expanded_array_instance": True}, base_offset, prefix)
            return
        fields = []
        for field in reg.get("fields") or []:
            access = get_string(field.get("access") if field.get("access") is not None else "read-write")
            if reg["resetValue"] != 0:
                reset = int(math.floor(reg["resetValue"] / 2 ** field["offset"])) % (2 ** field["width"])
            else:
                reset = field["resetValue"]
            fields.append({
                "name": field["name"], "offset": field["offset"], "width": field["width"],
                "access": access.lower(), "reset_value": reset, "description": field.get("description") or "",
                "monitorChangeOf": field.get("monitorChangeOf"),
            })
        access = derive_register_access([f["access"] for f in fields], reg.get("access"))
        registers.append({
            "name": f"{prefix}{reg_name}", "offset": current, "access": access,
            "description": reg.get("description") or "", "reset_value": reg["resetValue"], "fields": fields,
        })

    for m in maps:
        for block in m.get("addressBlocks") or []:
            for reg in block.get("registers") or []:
                process(reg, block["baseAddress"], "")
    return sorted(registers, key=lambda r: r["offset"])


def project_memory_maps_for_template(maps: Sequence[dict]) -> List[dict]:
    def project_reg(r: dict) -> dict:
        fields = []
        for f in r.get("fields") or []:
            fields.append({
                "name": f["name"], "bits": f["bits"], "offset": f["offset"], "bit_offset": f["offset"],
                "bitOffset": f["offset"], "width": f["width"], "bit_width": f["width"], "bitWidth": f["width"],
                **({"access": f["access"]} if f.get("access") is not None else {}),  # JS `undefined` is omitted
                "resetValue": f["resetValue"], "reset_value": f["resetValue"],
                "description": f["description"], "monitorChangeOf": f.get("monitorChangeOf"),
            })
        base = {
            "name": r["name"], "offset": r["offset"], "address_offset": r["offset"], "addressOffset": r["offset"],
            "size": r["size"],
            "access": derive_register_access([get_string(f.get("access")) or "read-write" for f in fields], r.get("access")),
            "resetValue": r["resetValue"], "reset_value": r["resetValue"], "description": r["description"],
            "fields": fields,
        }
        if r.get("__kind") == "array":
            return {**base, "count": r.get("count"), "stride": r.get("stride"),
                    "registers": [project_reg(x) for x in r.get("registers") or []]}
        return base

    return [{
        "name": m["name"], "description": m["description"],
        "address_blocks": [{
            "name": b["name"], "base_address": b["baseAddress"], "baseAddress": b["baseAddress"],
            "range": b.get("range"), "usage": b["usage"],
            "registers": [project_reg(r) for r in b.get("registers") or []],
        } for b in m.get("addressBlocks") or []],
    } for m in maps]


# ---------------------------------------------------------------------------
# Shadow registers
# ---------------------------------------------------------------------------

W1C_ACCESS = {"write-1-to-clear", "read-write-1-to-clear"}
NON_READABLE_ACCESS = {"write-only", "wo", "write-1-to-clear", "write-self-clearing"}


def build_shadow_registers(registers: Sequence[dict]) -> dict:
    sw_access = {"read-write", "write-only", "rw", "wo", "read-write-1-to-clear", "write-1-to-clear",
                 "read-write-self-clearing", "write-self-clearing"}
    hw_access = {"read-only", "ro"}
    sc_access = {"write-self-clearing", "read-write-self-clearing"}

    def acc(f: dict) -> str:
        return get_string(f.get("access")) or "read-write"

    def fields_of(reg: dict) -> List[dict]:
        return reg.get("fields") or []

    sw = []
    for reg in registers:
        fs = fields_of(reg)
        if not fs:
            if (get_string(reg.get("access")) or "read-write") not in hw_access:
                sw.append(reg)
        elif any(acc(f) in sw_access for f in fs):
            sw.append(reg)
    hw = []
    for reg in registers:
        fs = fields_of(reg)
        if not fs:
            if (get_string(reg.get("access")) or "read-write") in hw_access:
                hw.append(reg)
        elif all(acc(f) in hw_access for f in fs):
            hw.append(reg)
    w1c = [r for r in registers if any(get_string(f.get("access")) in W1C_ACCESS for f in fields_of(r))]
    sc = [r for r in registers if any(get_string(f.get("access")) in sc_access for f in fields_of(r))]

    cos: List[dict] = []
    for reg in registers:
        fs = fields_of(reg)
        cos_fields = []
        for field in fs:
            target = get_string(field.get("monitorChangeOf"))
            if target == "":
                continue
            if get_string(field.get("access")) not in W1C_ACCESS:
                raise ValueError(f'Field "{get_string(field.get("name"))}" in register "{get_string(reg.get("name"))}" uses '
                                 f'monitorChangeOf but access type "{get_string(field.get("access"))}" is not '
                                 f'write-1-to-clear or read-write-1-to-clear.')
            monitored = next((f for f in fs if get_string(f.get("name")) == target), None)
            if monitored is None:
                raise ValueError(f'Field "{get_string(field.get("name"))}" in register "{get_string(reg.get("name"))}" '
                                 f'references monitorChangeOf: "{target}" but no such field exists in the same register.')
            cos_fields.append({**field, "monitored_field": monitored})
        if not cos_fields:
            continue
        seen = set()
        val_fields = []
        for cf in cos_fields:
            mf = cf["monitored_field"]
            n = get_string(mf.get("name"))
            if n in seen:
                continue
            seen.add(n)
            val_fields.append(mf)
        cos.append({**reg, "cos_fields": cos_fields, "val_fields": val_fields})

    cos_names = {get_string(r.get("name")) for r in cos}
    mixed_names: set = set()
    for reg in sw:
        if any(acc(f) in hw_access for f in fields_of(reg)):
            mixed_names.add(get_string(reg.get("name")))
    mixed_names |= cos_names
    read_composed = set(mixed_names)
    for reg in sw:
        if any(acc(f) in NON_READABLE_ACCESS for f in fields_of(reg)):
            read_composed.add(get_string(reg.get("name")))

    cos_val_by_name = {get_string(r.get("name")): r.get("val_fields") or [] for r in cos}
    mixed = []
    for reg in registers:
        if get_string(reg.get("name")) not in mixed_names:
            continue
        ro_fields = [f for f in fields_of(reg) if acc(f) in hw_access]
        cos_vals = cos_val_by_name.get(get_string(reg.get("name")), [])
        seen = set()
        val_fields = []
        for f in ro_fields + cos_vals:
            n = get_string(f.get("name"))
            if n not in seen:
                seen.add(n)
                val_fields.append(f)
        mixed.append({
            "name": reg.get("name"), "offset": reg.get("offset"), "access": reg.get("access"),
            "description": reg.get("description"), "reset_value": reg.get("reset_value"),
            "fields": reg.get("fields"), "val_fields": val_fields,
        })

    annotated_w1c = [{**reg, "fields": [{**f, "is_cos": get_string(f.get("monitorChangeOf")) != ""} for f in fields_of(reg)]}
                     for reg in w1c]
    annotated = [{**reg, "has_cos_fields": get_string(reg.get("name")) in cos_names,
                  "has_mixed_fields": get_string(reg.get("name")) in read_composed} for reg in registers]
    return {
        "registers": annotated, "sw_registers": sw, "hw_registers": hw, "w1c_registers": annotated_w1c,
        "sc_registers": sc, "cos_registers": cos, "mixed_registers": mixed,
    }

