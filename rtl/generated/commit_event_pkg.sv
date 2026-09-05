`default_nettype none
package commit_event_pkg;
  localparam string COMMIT_EVENT_SHA256 = "773da171de8caad77c354b70d8a03af949548307a71203bc8ada37530e8d0fe9";
  localparam int unsigned COMMIT_SLOTS = 2;
  localparam int unsigned COMMIT_CSR_EFFECTS = 4;
  typedef enum logic [2:0] {
    CSR_MASK_NONE = 3'd0,
    CSR_MASK_INSTRUCTION = 3'd1,
    CSR_MASK_TRAP_ENTRY = 3'd2,
    CSR_MASK_MRET = 3'd3
  } csr_mask_reason_e;
  typedef struct packed {
    logic valid;
    logic [11:0] address;
    logic [31:0] old_value;
    logic [31:0] new_value;
    logic [31:0] read_mask;
    logic [31:0] write_mask;
    csr_mask_reason_e mask_reason;
  } commit_csr_effect_t;
  typedef struct packed {
    logic valid;
    logic [63:0] order;
    logic [31:0] instruction;
    logic [1:0] privilege;
    logic [31:0] pc_before;
    logic [31:0] pc_after;
    logic [4:0] rs1_addr;
    logic [31:0] rs1_value;
    logic [4:0] rs2_addr;
    logic [31:0] rs2_value;
    logic [4:0] rd_addr;
    logic [31:0] rd_value;
    logic [31:0] rd_write_mask;
    logic trap;
    logic [31:0] trap_cause;
    logic [31:0] trap_value;
    logic retired;
    logic mem_valid;
    logic [31:0] mem_address;
    logic [3:0] mem_read_mask;
    logic [3:0] mem_write_mask;
    logic [31:0] mem_read_data;
    logic [31:0] mem_write_data;
    commit_csr_effect_t [COMMIT_CSR_EFFECTS-1:0] csr_effects;
  } commit_event_t;
  typedef struct packed {
    commit_event_t [COMMIT_SLOTS-1:0] slots;
  } commit_packet_t;
endpackage
`default_nettype wire
