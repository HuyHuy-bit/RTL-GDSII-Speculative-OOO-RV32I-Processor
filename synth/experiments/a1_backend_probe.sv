`default_nettype none
module a1_backend_probe (
  input  wire         clk_i,
  input  wire         rst_i,
  input  wire         flush_i,
  input  wire [63:0]  free_i,
  output wire [1:0]   alloc_valid_o,
  output wire [11:0]  alloc_addr_o,
  input  wire [15:0]  valid_i,
  input  wire [31:0]  ready_i,
  input  wire [191:0] source_i,
  input  wire [31:0]  eligible_i,
  input  wire [1:0]   port_ready_i,
  input  wire [1:0]   wb_accept_i,
  input  wire [11:0]  wb_addr_i,
  input  wire [63:0]  wb_data_i,
  output wire [31:0]  grant_o,
  output wire [23:0]  read_addr_o,
  output wire [127:0] read_data_o
);
  wire stop = rst_i || flush_i;
  wire [1:0] accepted = wb_accept_i & {2{!stop}};
  a1_select_probe select_probe (
    .stop_i(stop), .free_i(free_i), .alloc_valid_o(alloc_valid_o),
    .alloc_addr_o(alloc_addr_o), .valid_i(valid_i), .ready_i(ready_i),
    .source_i(source_i), .eligible_i(eligible_i), .port_ready_i(port_ready_i),
    .wb_accept_i(accepted), .wb_addr_i(wb_addr_i), .grant_o(grant_o),
    .read_addr_o(read_addr_o)
  );
  prf_4r2w prf (
    .clk_i(clk_i), .rst_i(rst_i), .raddr_i(read_addr_o), .rdata_o(read_data_o),
    .wb_accept_i(accepted), .waddr_i(wb_addr_i), .wdata_i(wb_data_i)
  );
endmodule
`default_nettype wire
