`default_nettype none
module rename_single (
  input wire clk_i, rst_i, recover_i,
  input wire [4:0] rs1_i, rs2_i, rd_i,
  output wire [5:0] source1_o, source2_o,
  output wire sources_ready_o,
  input wire allocate_i,
  output wire can_allocate_o,
  output single_lane_pkg::rename_entry_t entry_o,
  input wire wb_accept_i,
  input wire [5:0] wb_destination_i,
  input wire commit_i,
  input single_lane_pkg::rename_entry_t commit_entry_i
);
  logic [5:0] rat_q [0:31], committed_q [0:31];
  logic [63:0] free_q, ready_q, recovered_free;
  logic [5:0] candidate;
  always_comb begin
    candidate = 0;
    for (int i = 63; i >= 1; i--) if (free_q[i]) candidate = 6'(i);
    recovered_free = 64'hfffffffffffffffe;
    for (int i = 1; i < 32; i++) recovered_free[committed_q[i]] = 0;
    entry_o.rd = rd_i;
    entry_o.destination = rd_i == 0 ? 6'd0 : candidate;
    entry_o.stale = rd_i == 0 ? 6'd0 : rat_q[rd_i];
  end
  assign source1_o = rat_q[rs1_i];
  assign source2_o = rat_q[rs2_i];
  assign sources_ready_o = ready_q[source1_o] && ready_q[source2_o];
  assign can_allocate_o = !rst_i && !recover_i && (rd_i == 0 || candidate != 0);
  always_ff @(posedge clk_i) begin
    if (rst_i) begin
      free_q <= 64'hffffffff00000000;
      ready_q <= 64'h00000000ffffffff;
      for (int i = 0; i < 32; i++) begin
        rat_q[i] <= 6'(i);
        committed_q[i] <= 6'(i);
      end
    end else if (recover_i) begin
      free_q <= recovered_free;
      ready_q <= ~recovered_free;
      for (int i = 0; i < 32; i++) rat_q[i] <= committed_q[i];
    end else begin
      if (wb_accept_i && wb_destination_i != 0) ready_q[wb_destination_i] <= 1;
      if (commit_i && commit_entry_i.rd != 0) begin
        committed_q[commit_entry_i.rd] <= commit_entry_i.destination;
        free_q[commit_entry_i.stale] <= 1;
      end
      if (allocate_i && can_allocate_o && rd_i != 0) begin
        rat_q[rd_i] <= candidate;
        free_q[candidate] <= 0;
        ready_q[candidate] <= 0;
      end
    end
`ifndef SYNTHESIS
    if (!rst_i && !recover_i) begin
      assert (!allocate_i || can_allocate_o) else $fatal(1, "RENAME_FULL");
      assert (!free_q[0] && rat_q[0] == 0 && committed_q[0] == 0) else $fatal(1, "RENAME_ZERO");
      if (wb_accept_i && wb_destination_i != 0)
        assert (!free_q[wb_destination_i] && !ready_q[wb_destination_i]) else $fatal(1, "RENAME_WRITEBACK_OWNER");
      if (commit_i && commit_entry_i.rd != 0)
        assert (commit_entry_i.destination != 0 && commit_entry_i.stale != 0
                && commit_entry_i.destination != commit_entry_i.stale
                && committed_q[commit_entry_i.rd] == commit_entry_i.stale
                && !free_q[commit_entry_i.destination] && ready_q[commit_entry_i.destination])
          else $fatal(1, "RENAME_COMMIT_OWNER");
    end
`endif
  end
endmodule
`default_nettype wire
