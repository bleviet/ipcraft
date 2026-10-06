// Waveform dump module for Icarus Verilog simulation.
// Included automatically when WAVES=1; produces led_controller_avmm.vcd
// in the tb/ directory.  Open with:  make view_waves
`timescale 1ns / 1ps

module dump;
  initial begin
    $dumpfile("led_controller_avmm.vcd");
    $dumpvars(0, led_controller_avmm);
    #1;
  end
endmodule
