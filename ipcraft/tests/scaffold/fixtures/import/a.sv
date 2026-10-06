// top
module fancy #(
  parameter int DATA_W = 32,
  parameter string NAME = "hello \"x\"",
  parameter logic [7:0] INIT = 8'hAB,
  localparam DEPTH = 16
) (
  input  wire clk, rst_n,
  input  logic        i_en,
  output logic [DATA_W-1:0] o_data,
  output logic [$clog2(DEPTH)-1:0] cnt,
  inout  wire  [7:0] io_pad,
  input  [3:0] narrow,
  output reg [DATA_W*2-1:0] wide,
  input  wire [15:0] s_axis_tdata,
  input  wire s_axis_tvalid,
  output wire s_axis_tready,
  output wire [15:0] m_axis_tdata,
  output wire m_axis_tvalid,
  input  wire m_axis_tready
);
endmodule
