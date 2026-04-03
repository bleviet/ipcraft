# Xilinx Vivado validation script for generated IP
# Usage: vivado -mode batch -source validate_xilinx.tcl -tclargs <ip_dir> <top_entity>

if { $argc != 2 } {
    puts "Error: Expected 2 arguments: <ip_dir> <top_entity>"
    exit 1
}

set ip_dir [lindex $argv 0]
set top_entity [lindex $argv 1]

puts "================================================="
puts " Validating IP in Vivado: $top_entity"
puts " Directory: $ip_dir"
puts "================================================="

# Create an in-memory project
create_project -in_memory ip_val_proj
# Using a generic Zynq-7000 part commonly used
set_property part xc7z020clg400-1 [current_project]

# Read VHDL files
set vhdl_files [glob -nocomplain $ip_dir/rtl/*.vhd]
if { [llength $vhdl_files] == 0 } {
    puts "Error: No VHDL files found in $ip_dir/rtl/"
    exit 1
}
read_vhdl $vhdl_files

# Check if IP-XACT component.xml exists and load it
set xml_file "$ip_dir/xilinx/component.xml"
if { [file exists $xml_file] } {
    puts "Reading IP-XACT component XML: $xml_file"
    read_ipxact $xml_file
    ipxact::load_core $xml_file
} else {
    puts "Warning: No xilinx/component.xml found."
}

# Suppress expected warnings about unconnected inputs and tied-off outputs since the core logic is a blank templated stub
set_msg_config -id {Synth 8-7129} -new_severity info
set_msg_config -id {Synth 8-7080} -new_severity info
set_msg_config -id {Synth 8-3917} -new_severity info

# Run Out-Of-Context synthesis to verify elaboration and syntax
puts "Running Out-Of-Context synthesis..."
catch { synth_design -top $top_entity -mode out_of_context } result

# Optional: check if there are severe warnings or if it completely failed
# synth_design throws an error on failure, which catch absorbs into $result
if { [string match "*ERROR:*" $result] || [string match "*aborted*" $result] } {
    puts "Synthesis failed."
    puts $result
    exit 1
}

puts "================================================="
puts " Vivado validation completed successfully."
puts "================================================="
exit 0
