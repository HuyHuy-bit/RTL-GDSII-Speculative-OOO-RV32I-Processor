`default_nettype none
module csr_single (
  input wire clk_i, rst_i, commit_i,
  input commit_event_pkg::commit_event_t commit_event_i,
  input single_lane_pkg::decoded_t decoded_i,
  input wire [31:0] source_i, pc_i,
  input wire trap_i,
  input wire [31:0] cause_i, trap_value_i,
  output logic legal_o,
  output logic [31:0] value_o,
  output wire [31:0] mtvec_o, mepc_o,
  output commit_event_pkg::commit_csr_effect_t [3:0] effects_o
);
  import platform_pkg::*;
  import single_lane_pkg::*;
  import commit_event_pkg::*;
  localparam int COUNT = 20;
  localparam logic [COUNT-1:0][11:0] ADDRESS = {
    CSR_MCONFIGPTR, CSR_MHARTID, CSR_MIMPID, CSR_MARCHID, CSR_MVENDORID, CSR_MINSTRETH, CSR_MCYCLEH, CSR_MINSTRET, CSR_MCYCLE, CSR_MIP, CSR_MTVAL, CSR_MCAUSE, CSR_MEPC, CSR_MSCRATCH, CSR_MCOUNTINHIBIT, CSR_MSTATUSH, CSR_MTVEC, CSR_MIE, CSR_MISA, CSR_MSTATUS};
  localparam logic [COUNT-1:0][31:0] RESET = {
    CSR_MCONFIGPTR_RESET, CSR_MHARTID_RESET, CSR_MIMPID_RESET, CSR_MARCHID_RESET, CSR_MVENDORID_RESET, CSR_MINSTRETH_RESET, CSR_MCYCLEH_RESET, CSR_MINSTRET_RESET, CSR_MCYCLE_RESET, CSR_MIP_RESET, CSR_MTVAL_RESET, CSR_MCAUSE_RESET, CSR_MEPC_RESET, CSR_MSCRATCH_RESET, CSR_MCOUNTINHIBIT_RESET, CSR_MSTATUSH_RESET, CSR_MTVEC_RESET, CSR_MIE_RESET, CSR_MISA_RESET, CSR_MSTATUS_RESET};
  localparam logic [COUNT-1:0][31:0] WRITE_MASK = {
    CSR_MCONFIGPTR_WRITE_MASK, CSR_MHARTID_WRITE_MASK, CSR_MIMPID_WRITE_MASK, CSR_MARCHID_WRITE_MASK, CSR_MVENDORID_WRITE_MASK, CSR_MINSTRETH_WRITE_MASK, CSR_MCYCLEH_WRITE_MASK, CSR_MINSTRET_WRITE_MASK, CSR_MCYCLE_WRITE_MASK, CSR_MIP_WRITE_MASK, CSR_MTVAL_WRITE_MASK, CSR_MCAUSE_WRITE_MASK, CSR_MEPC_WRITE_MASK, CSR_MSCRATCH_WRITE_MASK, CSR_MCOUNTINHIBIT_WRITE_MASK, CSR_MSTATUSH_WRITE_MASK, CSR_MTVEC_WRITE_MASK, CSR_MIE_WRITE_MASK, CSR_MISA_WRITE_MASK, CSR_MSTATUS_WRITE_MASK};
  localparam logic [COUNT-1:0][31:0] FIXED_MASK = {
    CSR_MCONFIGPTR_FIXED_MASK, CSR_MHARTID_FIXED_MASK, CSR_MIMPID_FIXED_MASK, CSR_MARCHID_FIXED_MASK, CSR_MVENDORID_FIXED_MASK, CSR_MINSTRETH_FIXED_MASK, CSR_MCYCLEH_FIXED_MASK, CSR_MINSTRET_FIXED_MASK, CSR_MCYCLE_FIXED_MASK, CSR_MIP_FIXED_MASK, CSR_MTVAL_FIXED_MASK, CSR_MCAUSE_FIXED_MASK, CSR_MEPC_FIXED_MASK, CSR_MSCRATCH_FIXED_MASK, CSR_MCOUNTINHIBIT_FIXED_MASK, CSR_MSTATUSH_FIXED_MASK, CSR_MTVEC_FIXED_MASK, CSR_MIE_FIXED_MASK, CSR_MISA_FIXED_MASK, CSR_MSTATUS_FIXED_MASK};
  localparam logic [COUNT-1:0][31:0] FIXED_VALUE = {
    CSR_MCONFIGPTR_FIXED_VALUE, CSR_MHARTID_FIXED_VALUE, CSR_MIMPID_FIXED_VALUE, CSR_MARCHID_FIXED_VALUE, CSR_MVENDORID_FIXED_VALUE, CSR_MINSTRETH_FIXED_VALUE, CSR_MCYCLEH_FIXED_VALUE, CSR_MINSTRET_FIXED_VALUE, CSR_MCYCLE_FIXED_VALUE, CSR_MIP_FIXED_VALUE, CSR_MTVAL_FIXED_VALUE, CSR_MCAUSE_FIXED_VALUE, CSR_MEPC_FIXED_VALUE, CSR_MSCRATCH_FIXED_VALUE, CSR_MCOUNTINHIBIT_FIXED_VALUE, CSR_MSTATUSH_FIXED_VALUE, CSR_MTVEC_FIXED_VALUE, CSR_MIE_FIXED_VALUE, CSR_MISA_FIXED_VALUE, CSR_MSTATUS_FIXED_VALUE};
  localparam logic [COUNT-1:0] READ_ONLY = {1'b1, 1'b1, 1'b1, 1'b1, 1'b1, 1'b0, 1'b0, 1'b0, 1'b0, 1'b0, 1'b0, 1'b0, 1'b0, 1'b0, 1'b0, 1'b0, 1'b0, 1'b0, 1'b1, 1'b0};
  localparam int I_MSTATUS = 0;
  localparam int I_MTVEC = 3;
  localparam int I_MEPC = 7;
  localparam int I_MCOUNTINHIBIT = 5;
  localparam int I_MCYCLE = 11;
  localparam int I_MCYCLEH = 13;
  localparam int I_MINSTRET = 12;
  localparam int I_MINSTRETH = 14;
  logic [31:0] csr_q [0:COUNT-1];
  logic write_query, found, cycle_write, instret_write;
  logic [31:0] operand, new_value;
  integer query_index;
  assign mtvec_o = csr_q[I_MTVEC];
  assign mepc_o = csr_q[I_MEPC];
  function automatic commit_csr_effect_t effect(input logic [11:0] address,
      input logic [31:0] new_data, mask, input csr_mask_reason_e reason);
    commit_csr_effect_t result;
    result = '0;
    for (int i = 0; i < COUNT; i++) if (ADDRESS[i] == address) begin
      result.valid = 1;
      result.address = address;
      result.old_value = csr_q[i];
      result.new_value = new_data;
      result.read_mask = WRITE_MASK[i] | FIXED_MASK[i];
      result.write_mask = mask;
      result.mask_reason = reason;
    end
    return result;
  endfunction
  always_comb begin
    found = 0;
    query_index = 0;
    for (int i = 0; i < COUNT; i++) if (ADDRESS[i] == decoded_i.csr) begin
      found = 1;
      query_index = i;
    end
    operand = decoded_i.funct3[2] ? {27'd0, decoded_i.zimm} : source_i;
    write_query = decoded_i.funct3[1:0] == 1 || decoded_i.zimm != 0;
    legal_o = found && !(write_query && READ_ONLY[query_index]);
    value_o = csr_q[query_index];
    case (decoded_i.funct3[1:0])
      1: new_value = operand;
      2: new_value = value_o | operand;
      3: new_value = value_o & ~operand;
      default: new_value = value_o;
    endcase
    new_value = ((new_value & WRITE_MASK[query_index]) | (value_o & ~WRITE_MASK[query_index]));
    new_value = (new_value & ~FIXED_MASK[query_index]) | FIXED_VALUE[query_index];
  end
  always_comb begin
    effects_o = '0;
    if (trap_i) begin
      effects_o[0] = effect(CSR_MSTATUS,
        (csr_q[I_MSTATUS] & ~32'h88) | {24'd0, csr_q[I_MSTATUS][3], 7'd0}, CSR_MSTATUS_WRITE_MASK, CSR_MASK_TRAP_ENTRY);
      effects_o[1] = effect(CSR_MEPC, pc_i & 32'hfffffffc, CSR_MEPC_WRITE_MASK, CSR_MASK_TRAP_ENTRY);
      effects_o[2] = effect(CSR_MCAUSE, cause_i, CSR_MCAUSE_WRITE_MASK, CSR_MASK_TRAP_ENTRY);
      effects_o[3] = effect(CSR_MTVAL, trap_value_i, CSR_MTVAL_WRITE_MASK, CSR_MASK_TRAP_ENTRY);
    end else if (decoded_i.op == OP_MRET) begin
      effects_o[0] = effect(CSR_MSTATUS,
        (csr_q[I_MSTATUS] & ~32'h88) | 32'h80 | {28'd0, csr_q[I_MSTATUS][7], 3'd0}, CSR_MSTATUS_WRITE_MASK, CSR_MASK_MRET);
    end else if (decoded_i.op == OP_CSR && legal_o) begin
      effects_o[0] = effect(decoded_i.csr, write_query ? new_value : value_o,
                           write_query ? WRITE_MASK[query_index] : 32'd0, CSR_MASK_INSTRUCTION);
    end
  end
  always_comb begin
    cycle_write = 0;
    instret_write = 0;
    for (int i = 0; i < 4; i++) if (commit_i && commit_event_i.csr_effects[i].valid
        && commit_event_i.csr_effects[i].write_mask != 0) begin
      if (commit_event_i.csr_effects[i].address inside {CSR_MCYCLE, CSR_MCYCLEH}) cycle_write = 1;
      if (commit_event_i.csr_effects[i].address inside {CSR_MINSTRET, CSR_MINSTRETH}) instret_write = 1;
    end
  end
  always_ff @(posedge clk_i) begin
    if (rst_i) begin
      for (int i = 0; i < COUNT; i++) csr_q[i] <= RESET[i];
    end else begin
      if (!csr_q[I_MCOUNTINHIBIT][0] && !cycle_write)
        {csr_q[I_MCYCLEH], csr_q[I_MCYCLE]} <= {csr_q[I_MCYCLEH], csr_q[I_MCYCLE]} + 64'd1;
      if (commit_i && commit_event_i.retired && !csr_q[I_MCOUNTINHIBIT][2] && !instret_write)
        {csr_q[I_MINSTRETH], csr_q[I_MINSTRET]} <= {csr_q[I_MINSTRETH], csr_q[I_MINSTRET]} + 64'd1;
      for (int e = 0; e < 4; e++) begin
        for (int i = 0; i < COUNT; i++) begin
          if (commit_i && commit_event_i.csr_effects[e].valid && commit_event_i.csr_effects[e].write_mask != 0
              && commit_event_i.csr_effects[e].address == ADDRESS[i])
            csr_q[i] <= (csr_q[i] & ~commit_event_i.csr_effects[e].write_mask)
              | (commit_event_i.csr_effects[e].new_value & commit_event_i.csr_effects[e].write_mask);
        end
      end
    end
  end
endmodule
`default_nettype wire
