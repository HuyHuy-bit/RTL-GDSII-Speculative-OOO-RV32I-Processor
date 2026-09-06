`default_nettype none
module csr_single_tb;
  import platform_pkg::*;
  import single_lane_pkg::*;
  import commit_event_pkg::*;
  logic clk = 0, rst = 1, commit = 0;
  decoded_t decoded;
  commit_event_t event_in;
  commit_csr_effect_t [3:0] effects;
  wire legal;
  wire [31:0] value, mtvec, mepc;
  logic [31:0] source = 0;
  csr_single csr (.clk_i(clk), .rst_i(rst), .commit_i(commit), .commit_event_i(event_in),
    .decoded_i(decoded), .source_i(source), .pc_i(32'd0), .trap_i(1'b0), .cause_i(32'd0), .trap_value_i(32'd0),
    .legal_o(legal), .value_o(value), .mtvec_o(mtvec), .mepc_o(mepc), .effects_o(effects));
  task automatic tick;
    #1; clk = 1; #1; clk = 0; #1;
  endtask
  task automatic write_csr(input logic [11:0] address, input logic [31:0] data);
    decoded.csr = address; decoded.funct3 = 1; decoded.zimm = 1; source = data; #1;
    assert(legal) else $fatal(1, "legal CSR write rejected");
    event_in = '0; event_in.retired = 1; event_in.csr_effects = effects;
    commit = 1; tick(); commit = 0;
  endtask
  task automatic check_csr(input logic [11:0] address, input logic [31:0] expected);
    decoded.csr = address; decoded.funct3 = 2; decoded.zimm = 0; source = 0; #1;
    assert(legal && value == expected) else $fatal(1, "CSR %h got %h expected %h", address, value, expected);
  endtask
  initial begin
    decoded = '0; decoded.op = OP_CSR; event_in = '0;
    tick(); rst = 0;
    check_csr(CSR_MCYCLE, 0);
    repeat (5) tick();
    check_csr(CSR_MCYCLE, 5);
    write_csr(CSR_MCOUNTINHIBIT, 5);
    check_csr(CSR_MCYCLE, 6);
    repeat (5) tick();
    check_csr(CSR_MCYCLE, 6);
    write_csr(CSR_MCYCLEH, 7); write_csr(CSR_MCYCLE, 32'hffffffff);
    write_csr(CSR_MINSTRETH, 3); write_csr(CSR_MINSTRET, 32'hffffffff);
    write_csr(CSR_MCOUNTINHIBIT, 0); tick();
    check_csr(CSR_MCYCLEH, 8); check_csr(CSR_MCYCLE, 0);
    event_in = '0; event_in.retired = 1; commit = 1; tick(); commit = 0;
    check_csr(CSR_MINSTRETH, 4); check_csr(CSR_MINSTRET, 0);
    write_csr(CSR_MCYCLE, 32'hffffffff);
    check_csr(CSR_MCYCLEH, 8);
    write_csr(CSR_MCYCLEH, 2);
    check_csr(CSR_MCYCLE, 32'hffffffff);
    tick(); check_csr(CSR_MCYCLEH, 3); check_csr(CSR_MCYCLE, 0);
    write_csr(CSR_MSTATUS, 32'hffffffff); check_csr(CSR_MSTATUS, 32'h1888);
    write_csr(CSR_MTVEC, 32'h107); check_csr(CSR_MTVEC, 32'h104);
    write_csr(CSR_MEPC, 32'h207); check_csr(CSR_MEPC, 32'h204);
    write_csr(CSR_MIE, 32'hffffffff); check_csr(CSR_MIE, 0);
    decoded.csr = CSR_MISA; decoded.funct3 = 1; #1;
    assert(!legal) else $fatal(1, "read-only CSR write accepted");
    decoded.csr = 12'hfff; #1;
    assert(!legal) else $fatal(1, "unknown CSR accepted");
    $display("CSR PASS counters, overflow, inhibit, write priority, WARL, legality");
    $finish;
  end
endmodule
`default_nettype wire
