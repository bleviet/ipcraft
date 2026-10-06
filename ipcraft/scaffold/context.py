"""Template-context resolvers (port of ``generator/resolvers/*`` and the
``IpCoreScaffolder.buildTemplateContext`` method).

The context is the public contract for scaffold packs: keys are snake_case, exactly as
produced by the TypeScript implementation (contract version ``1.4.0``).
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional

from . import widthexpr as wx
from .buscontracts import (
    BYTE_LANE_WIDTH,
    canonicalize_bus_type,
    is_memory_mapped_consumer,
    parameter_expression,
    resolve_bus_interface,
    resolve_data_lane,
)
from .domain import title_case_identifier
from .registers import (
    build_boundary_transforms,
    build_parameterized_port_types,
    build_shadow_registers,
    check_duplicate_physical_prefixes,
    expand_bus_interfaces,
    get_active_bus_ports_from_definition,
    get_bus_type_for_template,
    get_string,
    has_memory_mapped_consumer_interface,
    needs_bit_reverse,
    needs_lane_swap,
    prepare_registers,
    project_memory_maps_for_template,
    project_resolved_bus_ports,
    resolve_memory_maps,
    resolve_string_width,
    to_tcl_width_expression,
)

CONTRACT_VERSION = "1.4.0"


# ---------------------------------------------------------------------------
# Tcl string helpers
# ---------------------------------------------------------------------------


def to_tcl_quoted_string(text: str) -> str:
    return re.sub(r'[\\"$\[]', lambda m: "\\" + m.group(0), text)


def to_tcl_braced_list_quoted_string(text: str) -> str:
    return re.sub(r'[\\"{}]', lambda m: "\\" + m.group(0), text)


def to_tcl_brace_text(text: str) -> str:
    t = re.sub(r"\s+", " ", text)
    t = t.replace("\\", "").replace("{", "(").replace("}", ")")
    return t.strip()


# ---------------------------------------------------------------------------
# Clock / reset
# ---------------------------------------------------------------------------


def parse_clock_period_ns(frequency: Any) -> Optional[str]:
    if not frequency:
        return None
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(GHz|MHz|kHz|Hz)$", str(frequency).strip(), re.IGNORECASE)
    if not m:
        return None
    value = float(m.group(1))
    unit = m.group(2).lower()
    hz = value * {"ghz": 1e9, "mhz": 1e6, "khz": 1e3, "hz": 1}[unit]
    return _to_fixed(1e9 / hz, 3)


def _to_fixed(x: float, digits: int) -> str:
    # JS Number.prototype.toFixed rounds half away from zero on the decimal expansion.
    from decimal import ROUND_HALF_UP, Decimal

    return str(Decimal(repr(x)).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP))


def resolve_clock_reset(ip_core: dict) -> dict:
    clocks = ip_core.get("clocks") or []
    resets = ip_core.get("resets") or []
    clock_port = clocks[0].get("name") if clocks and clocks[0].get("name") is not None else "clk"
    reset_port = resets[0].get("name") if resets and resets[0].get("name") is not None else "rst"
    polarity = str(resets[0].get("polarity")) if resets and resets[0].get("polarity") is not None else "activeHigh"
    reset_active_high = "high" in polarity.lower()
    clocks_with_period = [{
        "name": c.get("name") or "", "frequency": c.get("frequency"),
        "period_ns": parse_clock_period_ns(c.get("frequency")),
    } for c in clocks]
    secondary_clocks = [{"name": c.get("name") or ""} for c in clocks[1:]]
    secondary_resets = [{
        "name": r.get("name") or "",
        "active_high": "high" in str(r.get("polarity") if r.get("polarity") is not None else "activeHigh").lower(),
        "associated_clock": r["associatedClock"] if r.get("associatedClock") and r["associatedClock"].strip() != "" else clock_port,
    } for r in resets[1:]]
    first_assoc = resets[0].get("associatedClock") if resets else None
    return {
        "clock_port": clock_port,
        "reset_port": reset_port,
        "reset_active_high": reset_active_high,
        "reset_associated_clock": first_assoc if first_assoc and first_assoc.strip() != "" else clock_port,
        "clocks_with_period": clocks_with_period,
        "secondary_clocks": secondary_clocks,
        "secondary_resets": secondary_resets,
    }


# ---------------------------------------------------------------------------
# Generics / layout / display items
# ---------------------------------------------------------------------------


def _generic_default(value: Any, type_: str) -> Any:
    t = type_.lower().strip()
    if t == "string":
        raw = str(value) if value is not None else ""
        inner = raw[1:-1] if len(raw) >= 2 and raw.startswith('"') and raw.endswith('"') else raw
        return f'"{inner}"'
    if value is not None:
        return value
    if t == "integer":
        return 0
    if t == "boolean":
        return "false"
    return 0


def _tcl_generic_default(value: Any, type_: str) -> Any:
    resolved = _generic_default(value, type_)
    if type_.lower().strip() != "string" or not isinstance(resolved, str):
        return resolved
    inner = resolved[1:-1] if len(resolved) >= 2 and resolved.startswith('"') and resolved.endswith('"') else resolved
    return f'"{to_tcl_quoted_string(inner)}"'


def _sv_generic_type(vhdl_type: str) -> str:
    t = vhdl_type.lower().strip()
    return {"integer": "int", "boolean": "bit", "string": ""}.get(t, "int")


def _sv_generic_default(value: Any, type_: str) -> Any:
    t = type_.lower().strip()
    if t == "string":
        raw = str(value) if value is not None else ""
        inner = raw[1:-1] if len(raw) >= 2 and raw.startswith('"') and raw.endswith('"') else raw
        return f'"{inner}"'
    if value is not None:
        if t == "boolean":
            v = str(value).lower().strip()
            return "1'b1" if v in ("true", "1") else "1'b0"
        return value
    if t == "integer":
        return 0
    if t == "boolean":
        return "1'b0"
    return 0


def _allowed_ranges_tcl(type_: str, allowed: Optional[list]) -> Optional[str]:
    if not allowed:
        return None
    is_string = type_.lower().strip() == "string"
    items = [f'"{to_tcl_braced_list_quoted_string(str(v))}"' if is_string else _js_str(v) for v in allowed]
    return f"{{ {' '.join(items)} }}"


def _js_str(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return str(v)


def build_generics(ip_core: dict) -> List[dict]:
    out = []
    for p in ip_core.get("parameters") or []:
        type_ = str(p.get("dataType") or "")
        name = str(p.get("name") or "")
        description = str(p["description"]) if p.get("description") else ""
        display_name = str(p["displayName"]) if p.get("displayName") else title_case_identifier(name)
        allowed = p.get("allowedValues")
        out.append({
            "name": p.get("name"),
            "display_name": display_name,
            "display_name_tcl": to_tcl_quoted_string(display_name),
            "type": type_,
            "sv_type": _sv_generic_type(type_),
            "default_value": _generic_default(p.get("value"), type_),
            "default_value_tcl": _tcl_generic_default(p.get("value"), type_),
            "sv_default": _sv_generic_default(p.get("value"), type_),
            "description": description,
            "description_tcl": to_tcl_quoted_string(description),
            "min": p.get("min") if p.get("min") is not None else None,
            "max": p.get("max") if p.get("max") is not None else None,
            "allowed_values": allowed if allowed is not None else None,
            "allowed_values_tcl": _allowed_ranges_tcl(type_, allowed),
            "ui_page": p.get("uiPage") or "",
            "ui_group": p.get("uiGroup") or "",
        })
    return out


DEFAULT_PAGE_NAME = "Page 0"
_DEFAULT_PAGE_KEY = "__ipcraft_default_page__"


def _tcl_var(s: str) -> str:
    return re.sub(r"[\s\-.]", "_", s)


def build_parameter_layout(generics: List[dict]) -> List[dict]:
    page_order: List[str] = []
    page_name: Dict[str, str] = {}
    group_order: Dict[str, List[str]] = {}
    group_params: Dict[str, Dict[str, List[dict]]] = {}
    ungrouped: Dict[str, List[dict]] = {}
    for g in generics:
        has_page = bool(g.get("ui_page"))
        key = str(g["ui_page"]) if has_page else _DEFAULT_PAGE_KEY
        pname = str(g["ui_page"]) if has_page else DEFAULT_PAGE_NAME
        group = str(g["ui_group"]) if g.get("ui_group") else ""
        param = {"name": str(g.get("name") or ""),
                 "tooltip": to_tcl_brace_text(str(g["description"]) if g.get("description") else "")}
        if key not in page_order:
            page_order.append(key)
            page_name[key] = pname
            group_order[key] = []
            group_params[key] = {}
            ungrouped[key] = []
        if group:
            if group not in group_order[key]:
                group_order[key].append(group)
                group_params[key][group] = []
            group_params[key][group].append(param)
        else:
            ungrouped[key].append(param)
    pages = []
    for key in page_order:
        name = page_name[key]
        pages.append({
            "name": name,
            "tcl_var": f"Page_{_tcl_var(name)}",
            "isDefault": key == _DEFAULT_PAGE_KEY,
            "groups": [{"name": grp, "tcl_var": f"Group_{_tcl_var(name)}_{_tcl_var(grp)}",
                        "params": group_params[key].get(grp, [])} for grp in group_order.get(key, [])],
            "ungrouped_params": ungrouped.get(key, []),
        })
    return pages


def build_display_items(pages: List[dict]) -> List[dict]:
    reserved: set = set()
    for page in pages:
        for p in page["ungrouped_params"]:
            reserved.add(p["name"].upper())
        for g in page["groups"]:
            for p in g["params"]:
                reserved.add(p["name"].upper())

    def claim(label: str) -> str:
        if label.upper() not in reserved:
            reserved.add(label.upper())
            return label
        n = 2
        cand = f"{label} ({n})"
        while cand.upper() in reserved:
            n += 1
            cand = f"{label} ({n})"
        reserved.add(cand.upper())
        return cand

    def item(id_: str, parent: str, kind: str) -> dict:
        return {"id": id_, "id_tcl": to_tcl_quoted_string(id_), "parent": parent,
                "parent_tcl": to_tcl_quoted_string(parent), "kind": kind}

    items: List[dict] = []
    for page in pages:
        page_id = "" if page["isDefault"] else claim(page["name"])
        if page_id:
            items.append(item(page_id, "", "GROUP"))
        for p in page["ungrouped_params"]:
            items.append(item(p["name"].upper(), page_id, "PARAMETER"))
        for g in page["groups"]:
            gid = claim(g["name"])
            items.append(item(gid, page_id, "GROUP"))
            for p in g["params"]:
                items.append(item(p["name"].upper(), gid, "PARAMETER"))
    return items


def resolve_generics(ip_core: dict) -> dict:
    generics = build_generics(ip_core)
    layout = build_parameter_layout(generics)
    return {
        "generics": generics,
        "xgui_pages": [{"name": p["name"], "tcl_var": p["tcl_var"], "groups": p["groups"],
                        "ungrouped_params": p["ungrouped_params"]} for p in layout],
        "display_items": build_display_items(layout),
    }


# ---------------------------------------------------------------------------
# Addressing
# ---------------------------------------------------------------------------


def _derive_data_width(ip_core: dict, library: dict) -> int:
    for bus_index, bus in enumerate(ip_core.get("busInterfaces") or []):
        resolution = resolve_bus_interface(bus, bus_index, ip_core.get("parameters") or [], library)
        match = resolution["match"]
        contract = match["contract"] if match else None
        if (not contract or contract["interfaceKind"] != "memoryMapped"
                or resolution["normalizedMode"] != contract["modePolicy"]["consumer"]):
            continue
        wdata = next((p for p in contract["ports"] if re.match(r"^(WDATA|writedata)$", p["name"])), None)
        width = resolution["portWidths"].get(wdata["name"], {}).get("value") if wdata else None
        if isinstance(width, (int, float)) and not isinstance(width, bool) and math.isfinite(width) and width > 0:
            return width
        break
    return 32


def resolve_addressing(ip_core: dict, registers: List[dict], library: dict) -> dict:
    data_width = _derive_data_width(ip_core, library)
    reg_width = data_width / 8
    reg_width = int(reg_width) if reg_width == int(reg_width) else reg_width
    last = registers[-1] if registers else None
    last_end = (last.get("offset") or 0) + reg_width if last else reg_width
    max_byte = max(last_end, len(registers) * reg_width)
    computed = max(3, math.ceil(math.log2(max(max_byte, 2))))
    raw = ip_core.get("addrWidth")
    addr_width = raw if isinstance(raw, (int, float)) and not isinstance(raw, bool) else computed
    return {"data_width": data_width, "reg_width": reg_width, "addr_width": addr_width, "addr_map_size": last_end}


# ---------------------------------------------------------------------------
# Interrupts
# ---------------------------------------------------------------------------


def build_interrupt_ports(ip_core: dict, library: dict, expanded: List[dict], primary_mm_index: int) -> List[dict]:
    clocks = ip_core.get("clocks") or []
    primary_clock = clocks[0].get("name") if clocks and clocks[0].get("name") is not None else "clk"
    primary_bus = expanded[primary_mm_index] if primary_mm_index >= 0 else None

    def is_mm_consumer(iface: dict) -> bool:
        match = canonicalize_bus_type(str(iface.get("type") or ""), library)
        count = (iface.get("array") or {}).get("count")
        return match is not None and is_memory_mapped_consumer(match["contract"], str(iface.get("mode") or "")) \
            and (count is None or count <= 1)

    def require_known_clock(name: str, source: str) -> str:
        if not any(c.get("name") == name for c in clocks):
            raise ValueError(f"{source} references unknown clock '{name}'")
        return name

    out = []
    for interrupt in ip_core.get("interrupts") or []:
        iname = str(interrupt.get("name") or "")
        has_explicit = isinstance(interrupt.get("associatedBusInterface"), str)
        explicit_bus = (interrupt.get("associatedBusInterface") or "").strip()
        associated = None if has_explicit else primary_bus
        if explicit_bus:
            configured = next((i for i in ip_core.get("busInterfaces") or [] if i.get("name") == explicit_bus), None)
            is_array = ((configured or {}).get("array") or {}).get("count", 0) > 1
            if not configured or is_array or not is_mm_consumer(configured):
                raise ValueError(f"Interrupt '{iname}' references missing or ineligible memory-mapped slave interface '{explicit_bus}'")
            associated = expand_bus_interfaces({"busInterfaces": [configured]})[0] if configured.get("array") else configured
        explicit_clock = (interrupt.get("associatedClock") or "").strip()
        bus_clock = ((associated or {}).get("associatedClock") or "").strip()
        if explicit_clock:
            assoc_clock = require_known_clock(explicit_clock, f"Interrupt '{iname}'")
        elif bus_clock:
            assoc_clock = require_known_clock(bus_clock, f"Bus interface '{(associated or {}).get('name') or ''}'")
        else:
            assoc_clock = primary_clock
        out.append({
            "name": iname,
            "direction": str(interrupt.get("direction") or "out").lower(),
            "sensitivity": str(interrupt.get("sensitivity") or "LEVEL_HIGH"),
            "associated_bus_interface": str((associated or {}).get("name") or ""),
            "associated_clock": assoc_clock,
        })
    return out


# ---------------------------------------------------------------------------
# Bus resolver
# ---------------------------------------------------------------------------


def _normalize_prefix(prefix: str) -> str:
    return prefix[:-1] if prefix.endswith("_") else prefix


def _to_tcl_width(width: Any, width_expr: Optional[str], names: List[str]) -> str:
    if width_expr:
        return to_tcl_width_expression(width_expr, names)
    if isinstance(width, str):
        return to_tcl_width_expression(width, names)
    return str(width if width is not None else 1)


def _to_template_bus_port(port: dict) -> dict:
    w = port["width"]
    numeric = w if isinstance(w, (int, float)) else float(w if w is not None else 1)
    out = {
        "logical_name": port["canonicalName"],
        "name": port["name"],
        "interface_role": port["interfaceRole"],
    }
    if port.get("effectivePolarity"):
        out["effective_polarity"] = port["effectivePolarity"]
    out.update({
        "physical_suffix": port["physicalSuffix"],
        "direction": port["direction"],
        "sv_direction": port["svDirection"],
        "width": port["width"],
        "width_expr": port["widthExpr"],
        "is_parameterized": port["isParameterized"],
        "default_width": (numeric - 1) if port["isParameterized"] else None,
        "type": port["type"],
        "sv_type": port["svType"],
        "tcl_width": port["tclWidth"],
        "endianness": port["endianness"],
        "needs_swap": port["needsSwap"],
    })
    if port.get("role"):
        out["role"] = port["role"]
    if port.get("swapKind"):
        out["swap_kind"] = port["swapKind"]
    if port.get("laneWidth") is not None:
        out["lane_width"] = port["laneWidth"]
    if port.get("laneKind"):
        out["lane_kind"] = port["laneKind"]
    out["needs_polarity_inversion"] = port["needsPolarityInversion"]
    return out


def build_user_ports(ip_core: dict, param_names: List[str]) -> List[dict]:
    defaults: Dict[str, float] = {}
    for p in ip_core.get("parameters") or []:
        if p.get("name") and p.get("value") is not None:
            try:
                defaults[str(p["name"])] = float(p["value"])
            except (TypeError, ValueError):
                defaults[str(p["name"])] = math.nan
    out = []
    for port in ip_core.get("ports") or []:
        direction = get_string(port.get("direction")).lower()
        sv_dir = "input" if direction == "in" else "output" if direction == "out" else "inout"
        width_value = port.get("width") if port.get("width") is not None else 1
        endianness = "big" if port.get("endianness") == "big" else "little"
        if isinstance(width_value, str):
            resolved = resolve_string_width(width_value, {k: v for k, v in defaults.items() if not math.isnan(v)})
        else:
            resolved = {"numeric": width_value, "expr": None}
        if resolved["expr"] is not None:
            numeric_default = resolved["numeric"] or 32
            types = build_parameterized_port_types(resolved["expr"])
            out.append({
                "name": str(port.get("name")), "direction": direction, "sv_direction": sv_dir,
                "type": types["type"], "sv_type": types["sv_type"], "width": numeric_default,
                "width_expr": resolved["expr"], "is_parameterized": True, "default_width": numeric_default - 1,
                "tcl_width": _to_tcl_width(numeric_default, resolved["expr"], param_names),
                "endianness": endianness,
                "needs_swap": needs_lane_swap(endianness, numeric_default, BYTE_LANE_WIDTH, direction, True),
                "swap_kind": "lane", "lane_width": BYTE_LANE_WIDTH, "lane_kind": "byte",
            })
            continue
        width = resolved["numeric"]
        out.append({
            "name": str(port.get("name")), "direction": direction, "sv_direction": sv_dir,
            "type": "std_logic" if width == 1 else f"std_logic_vector({width - 1} downto 0)",
            "sv_type": "logic" if width == 1 else f"logic [{width - 1}:0]",
            "width": width, "width_expr": None, "is_parameterized": False, "default_width": None,
            "tcl_width": _to_tcl_width(width, None, param_names), "endianness": endianness,
            "needs_swap": needs_lane_swap(endianness, width, BYTE_LANE_WIDTH, direction),
            "swap_kind": "lane", "lane_width": BYTE_LANE_WIDTH, "lane_kind": "byte",
        })
    return out


def resolve_bus(ip_core: dict, library: dict) -> dict:
    prefix_error = check_duplicate_physical_prefixes(ip_core, library)
    if prefix_error:
        raise ValueError(prefix_error)
    expanded = expand_bus_interfaces(ip_core)
    parameters = ip_core.get("parameters") or []
    parameter_names = [str(p.get("name")) for p in parameters]

    bus_ports: List[dict] = []
    secondary_bus_ports: List[dict] = []
    secondary_bus_interfaces: List[dict] = []
    projected_bus_ports: List[dict] = []
    explicit_conduit_ports: List[dict] = []
    bus_prefix = "s_axi"
    primary_mm_index = -1
    elaborate: List[dict] = []

    if expanded:
        def supports_mm(iface: dict) -> bool:
            m = canonicalize_bus_type(get_string(iface.get("type")), library)
            return m is not None and is_memory_mapped_consumer(m["contract"], get_string(iface.get("mode")))

        primary_mm_index = next((i for i, x in enumerate(expanded) if supports_mm(x)), -1)
        primary_index = primary_mm_index if primary_mm_index >= 0 else 0
        bus_prefix = _normalize_prefix(expanded[primary_index].get("physicalPrefix") or "")

        for index, iface in enumerate(expanded):
            resolution = resolve_bus_interface(iface, index, parameters, library)
            contract = resolution["match"]["contract"] if resolution["match"] else None
            interface_properties = []
            if contract:
                for name in sorted(contract["interfaceProperties"]):
                    prop = resolution["properties"].get(name)
                    if not prop or prop.get("value") is None:
                        continue
                    pexpr = parameter_expression(prop)
                    tcl_elab = to_tcl_width_expression(wx.serialize(pexpr, "canonical")[0], parameter_names) if pexpr else None
                    v = prop["value"]
                    entry = {"name": name, "value": v}
                    if tcl_elab:
                        entry["tcl_elaborate_value"] = tcl_elab
                    entry["tcl_value"] = ("true" if v else "false") if isinstance(v, bool) else _js_str(v)
                    interface_properties.append(entry)
            iface["interface_properties"] = interface_properties
            if contract:
                is_consumer = resolution["normalizedMode"] == contract["modePolicy"]["consumer"]
            else:
                is_consumer = iface.get("mode") in ("slave", "sink", "conduit")
            iface["normalized_mode"] = resolution["normalizedMode"] if resolution["normalizedMode"] is not None else iface.get("mode")
            iface["is_consumer"] = is_consumer
            iface["altera_end_type"] = "end" if ((contract and contract["interfaceKind"] == "conduit") or is_consumer) else "start"
            conduit_ports = iface.get("conduitPorts")
            iface_endianness = "big" if iface.get("endianness") == "big" else "little"
            data_lane = resolve_data_lane(resolution, iface)
            if conduit_ports:
                active = get_active_bus_ports_from_definition(
                    conduit_ports, iface.get("useOptionalPorts") or [], iface.get("physicalPrefix") or "",
                    iface.get("mode") or "", iface.get("portWidthOverrides") or {}, parameters,
                    iface.get("portNameOverrides"), iface.get("absentPorts"))
                pfx = iface.get("physicalPrefix") or ""
                for port in active:
                    port["interface_role"] = port["logical_name"]
                    port["physical_suffix"] = str(port["name"])[len(pfx):]
                    port["tcl_width"] = _to_tcl_width(port["width"], port["width_expr"], parameter_names)
                    port["needs_polarity_inversion"] = False
                    role = port.get("role")
                    if role == "data":
                        port["endianness"] = iface_endianness
                        port["needs_swap"] = needs_lane_swap(iface_endianness, port["width"], data_lane["width"],
                                                             port["direction"], port["is_parameterized"])
                        port["swap_kind"] = "lane"
                        port["lane_width"] = data_lane["width"]
                        port["lane_kind"] = data_lane["kind"]
                    elif role == "byteQualifier":
                        port["endianness"] = iface_endianness
                        port["needs_swap"] = needs_bit_reverse(iface_endianness, port["width"], port["direction"],
                                                               port["is_parameterized"])
                        port["swap_kind"] = "bit"
                        port["lane_width"] = 1
                        port["lane_kind"] = data_lane["kind"]
                    else:
                        port["needs_swap"] = False
                explicit_conduit_ports.extend(active)
            else:
                projected = project_resolved_bus_ports(
                    resolution["activePorts"], iface.get("physicalPrefix") or "", parameters,
                    {"endianness": iface_endianness, "laneWidth": data_lane["width"], "laneKind": data_lane["kind"]})
                projected_bus_ports.extend(projected)
                active = [_to_template_bus_port(p) for p in projected]
            iface["ports"] = active
            if index == primary_index:
                bus_ports.extend(active)
            else:
                secondary_bus_ports.extend(active)
                secondary_bus_interfaces.append({"name": iface.get("name") or "", "mode": iface.get("mode") or "", "ports": active})

    for iface in expanded:
        for port in iface.get("ports") or []:
            if port.get("is_parameterized") and port.get("tcl_width"):
                elaborate.append({
                    "iface_name": str(iface.get("name") or ""), "port_name": port["name"],
                    "logical_name": str(port.get("logical_name") or port["name"]),
                    "interface_role": str(port.get("interface_role") or port.get("logical_name") or port["name"]),
                    "direction": port["direction"], "tcl_width": port["tcl_width"],
                })

    user_ports = build_user_ports(ip_core, parameter_names)
    for port in user_ports:
        if port["is_parameterized"] and port["tcl_width"]:
            elaborate.append({"iface_name": port["name"], "port_name": port["name"], "logical_name": port["name"],
                              "interface_role": port["name"], "direction": port["direction"], "tcl_width": port["tcl_width"]})

    uses_math_real = any(
        p.get("is_parameterized") is True and isinstance(p.get("width_expr"), str) and wx.width_expr_uses_math_real(p["width_expr"])
        for p in bus_ports + secondary_bus_ports + user_ports)

    interrupt_ports = build_interrupt_ports(ip_core, library, expanded, primary_mm_index)
    all_template_ports = bus_ports + secondary_bus_ports + user_ports
    clocks, resets = ip_core.get("clocks") or [], ip_core.get("resets") or []
    reserved = {str(n).lower() for n in (
        [p["name"] for p in all_template_ports] + [p["name"] for p in interrupt_ports]
        + [c.get("name") or "" for c in clocks] + [r.get("name") or "" for r in resets] + parameter_names
        + ["clk" if not clocks else "", "rst" if not resets else ""]) if n}
    legacy_swap = []
    for port in explicit_conduit_ports + user_ports:
        if port.get("needs_swap") is True and port["direction"] != "inout":
            legacy_swap.append({
                "canonicalName": str(port["name"]), "name": str(port["name"]), "interfaceRole": str(port["name"]),
                "physicalSuffix": str(port["name"]), "direction": port["direction"], "svDirection": port["sv_direction"],
                "type": str(port["type"]), "svType": str(port["sv_type"]), "width": port["width"],
                "widthExpr": port["width_expr"], "isParameterized": port.get("is_parameterized") is True,
                "tclWidth": str(port["tcl_width"]), "endianness": port["endianness"], "needsSwap": True,
                "swapKind": port.get("swap_kind") or "lane",
                "laneWidth": port.get("lane_width") if port.get("lane_width") is not None else BYTE_LANE_WIDTH,
                "laneKind": port.get("lane_kind") or "byte", "needsPolarityInversion": False,
            })
    transforms = build_boundary_transforms(projected_bus_ports + legacy_swap, reserved)
    by_name = {p["name"]: p for p in transforms["ports"]}
    for port in all_template_ports:
        t = by_name.get(str(port["name"]))
        if t:
            port["internal_name"] = t["internalName"]

    boundary_ports = []
    for p in transforms["ports"]:
        b = {"name": p["name"], "internal_name": p["internalName"], "direction": p["direction"], "type": p["type"],
             "sv_type": p["svType"], "width": p["width"], "width_expr": p["widthExpr"],
             "is_parameterized": p["isParameterized"], "invert": p["invert"]}
        if p.get("swapKind"):
            b["swap_kind"] = p["swapKind"]
        if p.get("laneWidth") is not None:
            b["lane_width"] = p["laneWidth"]
        if p.get("laneKind"):
            b["lane_kind"] = p["laneKind"]
        boundary_ports.append(b)
    swappable = [p for p in transforms["ports"] if p.get("swapKind") is not None]
    widths = sorted({p["width"] for p in swappable
                     if p["swapKind"] == "lane" and _num_eq(p.get("laneWidth"), BYTE_LANE_WIDTH) and p["isParameterized"] is not True})
    swap_ports = [{
        "name": p["name"], "internal_name": p["internalName"], "type": p["type"], "sv_type": p["svType"],
        "direction": p["direction"], "width": p["width"], "is_parameterized": p["isParameterized"],
        "swap_kind": p["swapKind"],
        "lane_width": p["laneWidth"] if p.get("laneWidth") is not None else BYTE_LANE_WIDTH,
    } for p in swappable]
    return {
        "bus_prefix": bus_prefix if expanded else "s_axi",
        "bus_ports": bus_ports,
        "secondary_bus_ports": secondary_bus_ports,
        "secondary_bus_interfaces": secondary_bus_interfaces,
        "expanded_bus_interfaces": expanded,
        "elaborate_port_widths": elaborate,
        "user_ports": user_ports,
        "interrupt_ports": interrupt_ports,
        "uses_math_real": uses_math_real,
        "endian_swap_ports": swap_ports,
        "endian_swap_widths": widths,
        "has_endian_swap": len(swap_ports) > 0,
        "boundary_transform_ports": boundary_ports,
        "has_boundary_transform": len(boundary_ports) > 0,
    }


def _num_eq(a: Any, b: float) -> bool:
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Context assembly
# ---------------------------------------------------------------------------


def build_template_context(ip_core: dict, bus_type: str, input_path: str, library: dict,
                           resolved_memory_maps: Optional[List[dict]] = None) -> dict:
    name = str((ip_core.get("vlnv") or {}).get("name") or "ip_core").lower()
    maps = resolved_memory_maps if resolved_memory_maps is not None else resolve_memory_maps(ip_core, input_path)
    registers = prepare_registers(ip_core, input_path, maps)
    shadow = build_shadow_registers(registers)
    clock_reset = resolve_clock_reset(ip_core)
    bus = resolve_bus(ip_core, library)
    generics = resolve_generics(ip_core)
    addressing = resolve_addressing(ip_core, registers, library)
    vlnv = ip_core.get("vlnv") or {}
    display = re.sub(r"\b\w", lambda m: m.group(0).upper(), str(vlnv.get("name") or "ip_core").replace("_", " "))
    ctx: Dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "name": name,
        "entity_name": name,
        "bus_type": bus_type,
    }
    for part in (shadow, clock_reset, bus, generics, addressing):
        ctx.update(part)
    ctx.update({
        "memory_maps": project_memory_maps_for_template(maps),
        "memmap_relpath": f"../{name}.mm.yml",
        "vendor": vlnv.get("vendor"),
        "library": vlnv.get("library"),
        "version": vlnv.get("version"),
        "description": ip_core.get("description") or "",
        "author": ip_core.get("author") or "",
        "display_name": display,
    })
    return ctx
