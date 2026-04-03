import os

buses = {
    "axi4_lite": {
        "type": "ipcraft.busif.axi4_lite.1.0",
        "prefix": "s_axi_test_",
        "mode": "slave",
        "ports": ["AWADDR:12", "ARADDR:12", "WDATA:32", "RDATA:32", "WSTRB:4"]
    },
    "axi4_full": {
        "type": "ipcraft.busif.axi4_full.1.0",
        "prefix": "s_axi4_",
        "mode": "slave",
        "ports": ["AWADDR:32", "ARADDR:32", "WDATA:32", "RDATA:32", "WSTRB:4", "AWLEN:8", "ARLEN:8"]
    },
    "axi_stream": {
        "type": "ipcraft.busif.axi_stream.1.0",
        "prefix": "s_axis_",
        "mode": "sink",
        "ports": ["TDATA:32"]
    },
    "avalon_mm": {
        "type": "ipcraft.busif.avalon_mm.1.0",
        "prefix": "avs_",
        "mode": "slave",
        "ports": ["ADDRESS:12", "WRITEDATA:32", "READDATA:32"]
    },
    "avalon_st": {
        "type": "ipcraft.busif.avalon_st.1.0",
        "prefix": "asi_",
        "mode": "sink",
        "ports": ["DATA:32"]
    }
}

template_ip = """vlnv:
  vendor: test
  library: buses
  name: {name}
  version: 1.0.0
description: Auto-generated test IP for {name}
clocks:
- name: clk
  logicalName: CLK
  direction: in
  frequency: 100MHz
resets:
- name: rst_n
  logicalName: RESET_N
  direction: in
  polarity: activeLow
busInterfaces:
- name: S_AXI_LITE
  type: ipcraft.busif.axi4_lite.1.0
  mode: slave
  physicalPrefix: s_axi_
  associatedClock: clk
  associatedReset: rst_n
  memoryMapRef: CSR_MAP
  portWidthOverrides:
    AWADDR: 12
    ARADDR: 12
    WDATA: 32
    RDATA: 32
    WSTRB: 4
- name: TEST_BUS
  type: {bus_type}
  mode: {mode}
  physicalPrefix: {prefix}
  associatedClock: clk
  associatedReset: rst_n
  portWidthOverrides:
{port_overrides}
memoryMaps:
  import: {name}.mm.yml
fileSets:
- name: RTL
  files:
  - path: rtl/{name}_pkg.vhd
    type: vhdl
  - path: rtl/{name}_core.vhd
    type: vhdl
    managed: false
  - path: rtl/{name}_axil.vhd
    type: vhdl
  - path: rtl/{name}.vhd
    type: vhdl
- name: Integration
  files:
  - path: intel/{name}_hw.tcl
    type: tcl
"""

template_mm = """- name: CSR_MAP
  addressBlocks:
    - name: REGS
      baseAddress: 0x0
      range: 4096
      usage: register
      defaultRegWidth: 32
      registers:
        - name: TEST_REG
          offset: 0x0
          access: read-write
"""

for name, details in buses.items():
    port_overrides_str = ""
    for p in details["ports"]:
        k, v = p.split(":")
        port_overrides_str += f"    {k}: {v}\n"
    
    with open(f"{name}.mm.yml", "w") as f:
        f.write(template_mm)

    ip_content = template_ip.format(
        name=name,
        bus_type=details["type"],
        mode=details["mode"],
        prefix=details["prefix"],
        port_overrides=port_overrides_str
    )

    with open(f"{name}.ip.yml", "w") as f:
        f.write(ip_content)

print("Generated YAML configurations successfully.")
