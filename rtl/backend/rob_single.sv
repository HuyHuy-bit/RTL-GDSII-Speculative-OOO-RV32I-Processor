`default_nettype none
module rob_single (
  input wire clk_i, rst_i, flush_i,
  input wire allocate_i,
  output wire allocate_ready_o,
  output wire [4:0] allocate_index_o,
  input single_lane_pkg::rename_entry_t allocate_entry_i,
  input wire complete_i,
  input wire [4:0] complete_index_i,
  input commit_event_pkg::commit_event_t complete_event_i,
  output wire complete_ready_o,
  output wire head_valid_o,
  input wire retire_i,
  output single_lane_pkg::rename_entry_t head_entry_o,
  output commit_event_pkg::commit_event_t head_event_o
);
  single_lane_pkg::rename_entry_t entries_q [0:31];
  commit_event_pkg::commit_event_t events_q [0:31];
  logic [31:0] valid_q, done_q;
  logic [4:0] head_q, tail_q;
  logic [5:0] count_q;
  wire push = allocate_i && allocate_ready_o;
  wire pop = retire_i && head_valid_o;
  assign allocate_ready_o = count_q < 32 && !rst_i && !flush_i;
  assign allocate_index_o = tail_q;
  assign complete_ready_o = valid_q[complete_index_i] && !done_q[complete_index_i] && !rst_i && !flush_i;
  assign head_valid_o = valid_q[head_q] && done_q[head_q] && !rst_i && !flush_i;
  assign head_entry_o = entries_q[head_q];
  assign head_event_o = events_q[head_q];
  always_ff @(posedge clk_i) begin
    if (rst_i || flush_i) begin
      valid_q <= 0;
      done_q <= 0;
      head_q <= 0;
      tail_q <= 0;
      count_q <= 0;
    end else begin
      count_q <= count_q + 6'(push) - 6'(pop);
      if (push) begin
        entries_q[tail_q] <= allocate_entry_i;
        valid_q[tail_q] <= 1;
        done_q[tail_q] <= 0;
        tail_q <= tail_q + 1'b1;
      end
      if (complete_i && complete_ready_o) begin
        events_q[complete_index_i] <= complete_event_i;
        done_q[complete_index_i] <= 1;
      end
      if (pop) begin
        valid_q[head_q] <= 0;
        done_q[head_q] <= 0;
        head_q <= head_q + 1'b1;
      end
`ifndef SYNTHESIS
      assert (count_q <= 32 && $countones(valid_q) == int'(count_q)) else $fatal(1, "ROB_COUNT");
      assert (!allocate_i || allocate_ready_o) else $fatal(1, "ROB_FULL");
      assert (!complete_i || complete_ready_o) else $fatal(1, "ROB_STALE_COMPLETION");
      assert (!retire_i || head_valid_o) else $fatal(1, "ROB_RETIRE_NOT_READY");
`endif
    end
  end
endmodule
`default_nettype wire
