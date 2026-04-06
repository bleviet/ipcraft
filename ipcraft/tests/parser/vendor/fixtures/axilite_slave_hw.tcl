# AXI4-Lite slave _hw.tcl fixture for unit tests

set_module_info -name "axilite_slave"
set_module_info -version "2.0"
set_module_info -display_name "AXI4-Lite Slave"

# AXI4-Lite slave interface
add_interface s_axi axi4lite end
set_interface_property s_axi associatedClock aclk
set_interface_property s_axi associatedReset aresetn

add_interface_port s_axi s_axi_awaddr  AWADDR  Input  12
add_interface_port s_axi s_axi_awprot  AWPROT  Input  3
add_interface_port s_axi s_axi_awvalid AWVALID Input  1
add_interface_port s_axi s_axi_awready AWREADY Output 1
add_interface_port s_axi s_axi_wdata   WDATA   Input  32
add_interface_port s_axi s_axi_wstrb   WSTRB   Input  4
add_interface_port s_axi s_axi_wvalid  WVALID  Input  1
add_interface_port s_axi s_axi_wready  WREADY  Output 1
add_interface_port s_axi s_axi_bresp   BRESP   Output 2
add_interface_port s_axi s_axi_bvalid  BVALID  Output 1
add_interface_port s_axi s_axi_bready  BREADY  Input  1
add_interface_port s_axi s_axi_araddr  ARADDR  Input  12
add_interface_port s_axi s_axi_arprot  ARPROT  Input  3
add_interface_port s_axi s_axi_arvalid ARVALID Input  1
add_interface_port s_axi s_axi_arready ARREADY Output 1
add_interface_port s_axi s_axi_rdata   RDATA   Output 32
add_interface_port s_axi s_axi_rresp   RRESP   Output 2
add_interface_port s_axi s_axi_rvalid  RVALID  Output 1
add_interface_port s_axi s_axi_rready  RREADY  Input  1

# Clock
add_interface aclk clock end
add_interface_port aclk aclk clk Input 1

# Reset (active-low)
add_interface aresetn reset end
add_interface_port aresetn aresetn reset Input 1

# Parameter
add_parameter C_S_AXI_DATA_WIDTH INTEGER 32
set_parameter_property C_S_AXI_DATA_WIDTH DISPLAY_NAME "AXI Data Width"

add_parameter C_S_AXI_ADDR_WIDTH INTEGER 12
set_parameter_property C_S_AXI_ADDR_WIDTH DISPLAY_NAME "AXI Address Width"
