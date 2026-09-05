`default_nettype none
module a1_select_probe (
  input  wire         stop_i,
  input  wire [63:0]  free_i,
  output wire [1:0]   alloc_valid_o,
  output logic [11:0] alloc_addr_o,
  input  wire [15:0]  valid_i,
  input  wire [31:0]  ready_i,
  input  wire [191:0] source_i,
  input  wire [31:0]  eligible_i,
  input  wire [1:0]   port_ready_i,
  input  wire [1:0]   wb_accept_i,
  input  wire [11:0]  wb_addr_i,
  output wire [31:0]  grant_o,
  output logic [23:0] read_addr_o
);
  // Candidates only: ownership, commit/free forwarding, and recovery live outside this probe.
  wire [63:0] available = free_i & 64'hfffffffffffffffe & {64{!stop_i}};
  wire [63:0] alloc0 = available & (~available + 64'd1);
  wire [63:0] remaining = available & ~alloc0;
  wire [63:0] alloc1 = remaining & (~remaining + 64'd1);
  assign alloc_valid_o = {|alloc1, |alloc0};
  always_comb begin
    alloc_addr_o = '0;
    for (int entry = 1; entry < 64; entry++) begin
      alloc_addr_o[0 +: 6] |= {6{alloc0[entry]}} & 6'(entry);
      alloc_addr_o[6 +: 6] |= {6{alloc1[entry]}} & 6'(entry);
    end
  end

  // Input slots are already age ordered: slot zero is oldest. No age-sort cost is modeled.
  wire [15:0] runnable;
  for (genvar entry = 0; entry < 16; entry++) begin : g_ready
    wire [1:0] operand_ready;
    for (genvar operand = 0; operand < 2; operand++) begin : g_operand
      wire [5:0] tag = source_i[(entry*2+operand)*6 +: 6];
      assign operand_ready[operand] = ready_i[entry*2+operand] || tag == 6'd0
        || (wb_accept_i[0] && wb_addr_i[0 +: 6] == tag)
        || (wb_accept_i[1] && wb_addr_i[6 +: 6] == tag);
    end
    assign runnable[entry] = valid_i[entry] && (&operand_ready) && !stop_i;
  end

  wire [15:0] candidates0 = runnable & eligible_i[0 +: 16] & {16{port_ready_i[0]}};
  wire [15:0] chosen0 = candidates0 & (~candidates0 + 16'd1);
  wire [15:0] candidates1 = runnable & eligible_i[16 +: 16]
    & {16{port_ready_i[1]}} & ~chosen0;
  wire [15:0] chosen1 = candidates1 & (~candidates1 + 16'd1);
  assign grant_o = {chosen1, chosen0};
  always_comb begin
    read_addr_o = '0;
    for (int entry = 0; entry < 16; entry++) begin
      read_addr_o[0 +: 12] |= {12{chosen0[entry]}} & source_i[entry*12 +: 12];
      read_addr_o[12 +: 12] |= {12{chosen1[entry]}} & source_i[entry*12 +: 12];
    end
  end
endmodule
`default_nettype wire
