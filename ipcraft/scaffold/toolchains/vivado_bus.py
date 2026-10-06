"""Vivado bus catalog and bundled custom bus definitions (port of ``vivadoBusCatalog.ts`` and
``VivadoCustomBusDefinitions.ts``)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..buscontracts import canonicalize_bus_type, resolve_bus_interface
from ..registers import BUS_VLNV, registry_normalize

AXIMM_RTL_PORTS = set((
    "AWID AWADDR AWLEN AWSIZE AWBURST AWLOCK AWCACHE AWPROT AWREGION AWQOS AWUSER AWVALID "
    "AWREADY WID WDATA WSTRB WLAST WUSER WVALID WREADY BID BRESP BUSER BVALID BREADY ARID "
    "ARADDR ARLEN ARSIZE ARBURST ARLOCK ARCACHE ARPROT ARREGION ARQOS ARUSER ARVALID ARREADY "
    "RID RDATA RRESP RLAST RUSER RVALID RREADY").split(" "))
AXIS_RTL_PORTS = set("TID TDEST TDATA TSTRB TKEEP TLAST TUSER TVALID TREADY".split(" "))
AVALON_RTL_PORTS = set((
    "ADDRESS READDATA READDATAVALID WAITREQUEST BYTEENABLE READ RESPONSE WRITE WRITEDATA "
    "LOCK WRITERESPONSEVALID BURSTCOUNT BEGINBURSTTRANSFER").split(" "))

IPCRAFT_TO_VIVADO: Dict[str, dict] = {
    BUS_VLNV["AXI4_LITE"]: {"vendor": "xilinx.com", "library": "interface", "name": "aximm", "abstraction": "aximm_rtl",
                            "protocol": "AXI4LITE", "libraryKey": "AXI4_LITE", "logicalPorts": AXIMM_RTL_PORTS},
    BUS_VLNV["AXI4_FULL"]: {"vendor": "xilinx.com", "library": "interface", "name": "aximm", "abstraction": "aximm_rtl",
                            "protocol": "AXI4", "libraryKey": "AXI4_FULL", "logicalPorts": AXIMM_RTL_PORTS},
    BUS_VLNV["AXI_STREAM"]: {"vendor": "xilinx.com", "library": "interface", "name": "axis", "abstraction": "axis_rtl",
                             "libraryKey": "AXI_STREAM", "logicalPorts": AXIS_RTL_PORTS},
    BUS_VLNV["AVALON_MM"]: {"vendor": "xilinx.com", "library": "interface", "name": "avalon", "abstraction": "avalon_rtl",
                            "libraryKey": "AVALON_MEMORY_MAPPED", "logicalPorts": AVALON_RTL_PORTS},
}


def uses_alternate_polarity_role(resolution: dict) -> bool:
    return any(p["interfaceRole"] != p["name"] for p in resolution["activePorts"])


def resolve_vivado_bus_type(iface_type: str, library: dict) -> Optional[dict]:
    match = canonicalize_bus_type(iface_type, library)
    canonical = match["canonicalVlnv"] if match else iface_type
    direct = IPCRAFT_TO_VIVADO.get(canonical)
    if direct:
        return direct
    key = registry_normalize(iface_type, library)["libraryKey"]
    if not key:
        return None
    return next((e for e in IPCRAFT_TO_VIVADO.values() if e["libraryKey"] == key), None)


def resolve_vivado_bus_type_for_interface(iface_type: str, library: dict, resolution: dict) -> Optional[dict]:
    return None if uses_alternate_polarity_role(resolution) else resolve_vivado_bus_type(iface_type, library)


def custom_bus_info_from_contract(contract: dict) -> dict:
    vendor, library, name, version = contract["canonicalVlnv"].split(":")
    ports = []
    for port in contract["ports"]:
        entry: Dict[str, Any] = {
            "name": port["name"], "width": port.get("width"), "widthPolicy": port["widthPolicy"],
            "direction": port.get("direction"), "presence": port["presence"],
            "interfaceRoles": [port["polarity"]["roles"]["activeHigh"], port["polarity"]["roles"]["activeLow"]]
            if port.get("polarity") else [port["name"]],
        }
        if port["role"] in ("data", "byteQualifier"):
            entry["role"] = port["role"]
        ports.append(entry)
    return {"vendor": vendor, "library": library, "name": name, "version": version,
            "description": f"{contract['displayName']} interface", "ports": ports,
            "isAddressable": contract["interfaceKind"] == "memoryMapped", "source": contract.get("artifactSource")}


def find_custom_bus_def(iface_type: str, library: dict) -> Optional[dict]:
    if resolve_vivado_bus_type(iface_type, library):
        return None
    canonical = canonicalize_bus_type(iface_type, library)
    return custom_bus_info_from_contract(canonical["contract"]) if canonical else None


def escape_xml(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def render_bus_definition_xml(info: dict) -> str:
    e = escape_xml
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<spirit:busDefinition",
        '  xmlns:spirit="http://www.spiritconsortium.org/XMLSchema/SPIRIT/1685-2009"',
        '  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">',
        f"  <spirit:vendor>{e(info['vendor'])}</spirit:vendor>",
        f"  <spirit:library>{e(info['library'])}</spirit:library>",
        f"  <spirit:name>{e(info['name'])}</spirit:name>",
        f"  <spirit:version>{e(info['version'])}</spirit:version>",
        "  <spirit:directConnection>false</spirit:directConnection>",
        f"  <spirit:isAddressable>{'true' if info['isAddressable'] else 'false'}</spirit:isAddressable>",
    ]
    if info.get("description"):
        lines.append(f"  <spirit:description>{e(info['description'])}</spirit:description>")
    lines.append("</spirit:busDefinition>")
    return "\n".join(lines)


def render_abstraction_definition_xml(info: dict) -> str:
    e = escape_xml
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<spirit:abstractionDefinition",
        '  xmlns:spirit="http://www.spiritconsortium.org/XMLSchema/SPIRIT/1685-2009"',
        '  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">',
        f"  <spirit:vendor>{e(info['vendor'])}</spirit:vendor>",
        f"  <spirit:library>{e(info['library'])}</spirit:library>",
        f"  <spirit:name>{e(info['name'])}_rtl</spirit:name>",
        f"  <spirit:version>{e(info['version'])}</spirit:version>",
        f'  <spirit:busType spirit:vendor="{e(info["vendor"])}" spirit:library="{e(info["library"])}" '
        f'spirit:name="{e(info["name"])}" spirit:version="{e(info["version"])}"/>',
        "  <spirit:ports>",
    ]
    for port in info["ports"]:
        canonical_name = str(port["name"])
        if canonical_name in ("ACLK", "ARESETn", "clk", "reset"):
            continue
        roles = port.get("interfaceRoles") or [canonical_name]
        presence = "optional" if len(roles) > 1 else (port.get("presence") or "required")
        master_dir = port.get("direction") or "out"
        slave_dir = "in" if master_dir == "out" else "out"
        width_line = [f"          <spirit:width>{port['width']}</spirit:width>"] \
            if port.get("widthPolicy") == "fixed" and isinstance(port.get("width"), (int, float)) else []
        for logical in roles:
            lines.append("    <spirit:port>")
            lines.append(f"      <spirit:logicalName>{e(logical)}</spirit:logicalName>")
            lines.append("      <spirit:wire>")
            lines.append("        <spirit:onMaster>")
            lines.append(f"          <spirit:presence>{e(presence)}</spirit:presence>")
            lines.extend(width_line)
            lines.append(f"          <spirit:direction>{e(master_dir)}</spirit:direction>")
            lines.append("        </spirit:onMaster>")
            lines.append("        <spirit:onSlave>")
            lines.append(f"          <spirit:presence>{e(presence)}</spirit:presence>")
            lines.extend(width_line)
            lines.append(f"          <spirit:direction>{e(slave_dir)}</spirit:direction>")
            lines.append("        </spirit:onSlave>")
            lines.append("      </spirit:wire>")
            lines.append("    </spirit:port>")
    lines.append("  </spirit:ports>")
    lines.append("</spirit:abstractionDefinition>")
    return "\n".join(lines)


def generate_custom_bus_defs(ip_core: dict, library: dict) -> Dict[str, str]:
    files: Dict[str, str] = {}
    seen: set = set()
    for iface in ip_core.get("busInterfaces") or []:
        iface_type = str(iface.get("type") or "")
        resolution = resolve_bus_interface(iface, 0, ip_core.get("parameters") or [], library)
        contract = resolution["match"]["contract"] if resolution["match"] else None
        if (not contract or contract["canonicalVlnv"] in seen
                or resolve_vivado_bus_type_for_interface(iface_type, library, resolution)):
            continue
        seen.add(contract["canonicalVlnv"])
        custom = custom_bus_info_from_contract(contract)
        if custom.get("source") == "vivado":
            continue
        files[f"busdef/{custom['name']}.xml"] = render_bus_definition_xml(custom)
        files[f"busdef/{custom['name']}_rtl.xml"] = render_abstraction_definition_xml(custom)
    return files
