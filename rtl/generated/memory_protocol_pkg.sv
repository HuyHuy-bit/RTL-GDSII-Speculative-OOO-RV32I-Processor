`default_nettype none
package memory_protocol_pkg;
  localparam string MEMORY_PROTOCOL_SHA256 = "b1cb55f0c881293b4df6077f263f8907a347201090777647158e4c2a8b77de1e";
  localparam int unsigned MEM_LINE_BYTES = 32;
  localparam int unsigned MEM_TRANSACTION_ID_BITS = 4;
  typedef enum logic [1:0] {
    MEM_STATUS_OK = 2'd0,
    MEM_STATUS_ACCESS_FAULT = 2'd1,
    MEM_STATUS_PROTOCOL_ERROR = 2'd2
  } mem_response_status_e;
  typedef enum logic [1:0] {
    MEM_SIZE_BYTE = 2'd0,
    MEM_SIZE_HALFWORD = 2'd1,
    MEM_SIZE_WORD = 2'd2
  } mem_uncached_size_e;
  typedef struct packed {
    logic [3:0] transaction_id;
    logic write;
    logic uncached;
    logic [31:0] address;
    mem_uncached_size_e uncached_size;
    logic [255:0] line_write_data;
    logic [31:0] line_write_mask;
    logic [31:0] uncached_write_data;
    logic [3:0] uncached_write_strobe;
  } mem_request_t;
  typedef struct packed {
    logic [3:0] transaction_id;
    mem_response_status_e status;
    logic [255:0] line_read_data;
    logic [31:0] uncached_read_data;
  } mem_response_t;
endpackage
`default_nettype wire
