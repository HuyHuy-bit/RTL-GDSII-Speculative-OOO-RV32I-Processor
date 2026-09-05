`default_nettype none
module prf_4r2w (
  input  wire         clk_i,
  input  wire         rst_i,
  input  wire [23:0]  raddr_i,
  output wire [127:0] rdata_o,
  input  wire [1:0]   wb_accept_i,
  input  wire [11:0]  waddr_i,
  input  wire [63:0]  wdata_i
);
  // Lane zero occupies the low slice; accepted writebacks are already filtered for kills.
  wire [1:0] write_en = wb_accept_i & {2{!rst_i}};
  logic [31:0] payload_q [1:63];

  // Payloads have no reset value; p0 has no storage.
  for (genvar entry = 1; entry < 64; entry++) begin : g_entry
    always_ff @(posedge clk_i) begin
      if (write_en[0] && waddr_i[0 +: 6] == 6'(entry))
        payload_q[entry] <= wdata_i[0 +: 32];
      else if (write_en[1] && waddr_i[6 +: 6] == 6'(entry))
        payload_q[entry] <= wdata_i[32 +: 32];
    end
  end

  for (genvar port = 0; port < 4; port++) begin : g_read
    wire [5:0] address = raddr_i[port*6 +: 6];
    logic [31:0] value;
    always_comb begin
      if (address == 6'd0)
        value = 32'd0;
      else if (write_en[0] && waddr_i[0 +: 6] == address)
        value = wdata_i[0 +: 32];
      else if (write_en[1] && waddr_i[6 +: 6] == address)
        value = wdata_i[32 +: 32];
      else
        value = payload_q[address];
    end
    assign rdata_o[port*32 +: 32] = value;
  end

`ifndef SYNTHESIS
  // Concurrent writes to one live physical destination violate backend ownership.
  always_ff @(posedge clk_i) begin
    assert (!(write_en == 2'b11 && waddr_i[0 +: 6] != 6'd0
              && waddr_i[0 +: 6] == waddr_i[6 +: 6]))
      else $fatal(1, "PRF_DUPLICATE_WRITE");
  end
`endif
endmodule
`default_nettype wire
