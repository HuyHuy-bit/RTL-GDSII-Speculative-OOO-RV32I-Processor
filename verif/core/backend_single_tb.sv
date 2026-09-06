`default_nettype none
module backend_single_tb;
  import single_lane_pkg::*;
  import commit_event_pkg::*;
  logic clk = 0, rst = 1, recover = 0, allocate = 0, complete = 0, retire = 0;
  logic [4:0] rd = 1, index = 0;
  wire [5:0] source1, source2;
  wire ready, can_allocate, rob_ready, complete_ready, head_valid;
  wire [4:0] tail;
  rename_entry_t entry, head_entry;
  commit_event_t completion, head_event;
  rename_entry_t saved [0:31];
  logic [5:0] wb_tag;
  rename_single rename_stage (.clk_i(clk), .rst_i(rst), .recover_i(recover), .rs1_i(5'd1), .rs2_i(5'd0), .rd_i(rd),
    .source1_o(source1), .source2_o(source2), .sources_ready_o(ready), .allocate_i(allocate),
    .can_allocate_o(can_allocate), .entry_o(entry), .wb_accept_i(complete), .wb_destination_i(wb_tag),
    .commit_i(retire), .commit_entry_i(head_entry));
  rob_single rob (.clk_i(clk), .rst_i(rst), .flush_i(recover), .allocate_i(allocate), .allocate_ready_o(rob_ready),
    .allocate_index_o(tail), .allocate_entry_i(entry), .complete_i(complete), .complete_index_i(index),
    .complete_event_i(completion), .complete_ready_o(complete_ready), .head_valid_o(head_valid),
    .retire_i(retire), .head_entry_o(head_entry), .head_event_o(head_event));
  task automatic tick;
    #1; clk = 1; #1; clk = 0; #1;
  endtask
  initial begin
    completion = '0;
    completion.valid = 1;
    wb_tag = 0;
    tick(); rst = 0; #1;
    assert(source1 == 1 && source2 == 0 && ready) else $fatal(1, "reset maps");
    for (int round = 0; round < 3; round++) begin
      for (int n = 0; n < 32; n++) begin
        assert(can_allocate && rob_ready && tail == 5'(n)) else $fatal(1, "capacity or wrap");
        saved[n] = entry;
        allocate = 1; tick(); allocate = 0;
      end
      #1;
      assert(!can_allocate && !rob_ready && !head_valid && !ready) else $fatal(1, "full queue");
      for (int n = 31; n >= 0; n--) begin
        index = 5'(n); wb_tag = saved[n].destination; #1;
        assert(complete_ready) else $fatal(1, "completion ownership");
        completion.order = 64'(round*32+n);
        complete = 1; tick(); complete = 0;
        if (n != 0) assert(!head_valid) else $fatal(1, "out of order retirement");
      end
      for (int n = 0; n < 32; n++) begin
        #1;
        assert(head_valid && head_entry == saved[n] && head_event.order == 64'(round*32+n)) else $fatal(1, "retirement order");
        tick();
        assert(head_valid && head_entry == saved[n]) else $fatal(1, "head changed without retirement");
        retire = 1; tick(); retire = 0;
      end
    end
    begin
      logic [5:0] committed_tag;
      committed_tag = source1;
      for (int n = 0; n < 8; n++) begin allocate = 1; tick(); allocate = 0; end
      recover = 1; tick(); recover = 0; #1;
      assert(source1 == committed_tag && ready && can_allocate && rob_ready && !head_valid && !complete_ready)
        else $fatal(1, "recovery ownership");
    end
    $display("BACKEND PASS allocations=104 retirements=96 recoveries=1");
    $finish;
  end
endmodule
`default_nettype wire
