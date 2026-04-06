# Simple UART _hw.tcl fixture for unit tests

set_module_info -name "simple_uart"
set_module_info -version "1.0"
set_module_info -display_name "Simple UART Core"

# Avalon-MM slave interface
add_interface s0 avalon end
set_interface_property s0 associatedClock clk
set_interface_property s0 associatedReset rst

add_interface_port s0 avs_s0_address    address    Input  4
add_interface_port s0 avs_s0_write      write      Input  1
add_interface_port s0 avs_s0_writedata  writedata  Input  32
add_interface_port s0 avs_s0_read       read       Input  1
add_interface_port s0 avs_s0_readdata   readdata   Output 32

# Clock interface
add_interface clk clock end
add_interface_port clk clk clk Input 1

# Reset interface
add_interface rst reset end
add_interface_port rst rst reset Input 1

# Standalone ports
add_interface_port "" txd "" Output 1
add_interface_port "" rxd "" Input  1

# Parameter
add_parameter BAUD_RATE INTEGER 115200
set_parameter_property BAUD_RATE DISPLAY_NAME "Baud Rate"
