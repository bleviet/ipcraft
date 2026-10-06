module oldstyle (clk, rst, d, q);
  parameter W = 8;
  parameter [3:0] NIBBLE = 4'd3;
  input clk;
  input rst;
  input [W-1:0] d;
  output [W-1:0] q;
endmodule
