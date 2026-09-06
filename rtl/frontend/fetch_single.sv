`default_nettype none
module fetch_single (
  input wire clk_i, rst_i, start_i,
  input wire [31:0] pc_i,
  output wire start_ready_o,
  output wire request_valid_o,
  input wire request_ready_i,
  output memory_protocol_pkg::mem_request_t request_o,
  input wire response_valid_i,
  output wire response_ready_o,
  input memory_protocol_pkg::mem_response_t response_i,
  output wire valid_o,
  input wire ready_i,
  output logic [31:0] instruction_o,
  output logic fault_o,
  output logic fatal_o
);
  import single_lane_pkg::*;
  import memory_protocol_pkg::*;
  typedef enum logic [1:0] {IDLE, REQUEST, RESPONSE, RESULT} state_e;
  state_e state_q;
  logic [31:0] pc_q;
  logic [3:0] id_q;
  assign start_ready_o = state_q == IDLE && !rst_i && !fatal_o;
  assign request_valid_o = state_q == REQUEST && !rst_i && !fatal_o;
  assign response_ready_o = state_q == RESPONSE && !rst_i && !fatal_o;
  assign valid_o = state_q == RESULT && !rst_i && !fatal_o;
  always_comb begin
    request_o = '0;
    request_o.transaction_id = id_q;
    request_o.address = {pc_q[31:5], 5'd0};
  end
  always_ff @(posedge clk_i) begin
    if (rst_i) begin
      state_q <= IDLE;
      pc_q <= 0;
      id_q <= 0;
      instruction_o <= 0;
      fault_o <= 0;
      fatal_o <= 0;
    end else if (!fatal_o) begin
      if (response_valid_i && (state_q != RESPONSE || response_i.transaction_id != id_q
          || !(response_i.status inside {MEM_STATUS_OK, MEM_STATUS_ACCESS_FAULT})
          || response_i.uncached_read_data != 0
          || (response_i.status != MEM_STATUS_OK && response_i.line_read_data != 0))) fatal_o <= 1;
      case (state_q)
        IDLE: if (start_i) begin
          pc_q <= pc_i;
          fault_o <= !executable(pc_i) || pc_i[1:0] != 0;
          instruction_o <= 0;
          state_q <= executable(pc_i) && pc_i[1:0] == 0 ? REQUEST : RESULT;
        end
        REQUEST: if (request_ready_i) state_q <= RESPONSE;
        RESPONSE: if (response_valid_i) begin
          instruction_o <= response_i.status == MEM_STATUS_OK ? response_i.line_read_data[pc_q[4:2]*32 +: 32] : 0;
          fault_o <= response_i.status == MEM_STATUS_ACCESS_FAULT;
          id_q <= id_q + 1'b1;
          state_q <= RESULT;
        end
        RESULT: if (ready_i) state_q <= IDLE;
        default: state_q <= IDLE;
      endcase
    end
  end
endmodule
`default_nettype wire
