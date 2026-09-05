`default_nettype none
module lockstep_smoke;
  import commit_event_pkg::*;

  commit_packet_t packet;

  function automatic commit_event_t base_event(
    input logic [63:0] order,
    input logic [31:0] instruction,
    input logic [31:0] pc_before
  );
    base_event = '0;
    base_event.valid = 1'b1;
    base_event.order = order;
    base_event.instruction = instruction;
    base_event.privilege = 2'd3;
    base_event.pc_before = pc_before;
    base_event.pc_after = pc_before + 32'd4;
    base_event.retired = 1'b1;
  endfunction

  task automatic emit_event(input commit_event_t event_i);
    $display(
      "EVENT|%016x|%08x|%x|%08x|%08x|%x|%08x|%x|%08x|%x|%08x|%08x|%x|%08x|%08x|%x|%x|%08x|%x|%x|%08x|%08x",
      event_i.order, event_i.instruction, event_i.privilege,
      event_i.pc_before, event_i.pc_after,
      event_i.rs1_addr, event_i.rs1_value,
      event_i.rs2_addr, event_i.rs2_value,
      event_i.rd_addr, event_i.rd_value, event_i.rd_write_mask,
      event_i.trap, event_i.trap_cause, event_i.trap_value,
      event_i.retired, event_i.mem_valid, event_i.mem_address,
      event_i.mem_read_mask, event_i.mem_write_mask,
      event_i.mem_read_data, event_i.mem_write_data
    );
  endtask

  task automatic emit_packet(input commit_packet_t packet_i);
    $display("PACKET|%x|%x", packet_i.slots[0].valid, packet_i.slots[1].valid);
    if (packet_i.slots[0].valid) emit_event(packet_i.slots[0]);
    if (packet_i.slots[1].valid) emit_event(packet_i.slots[1]);
  endtask

  initial begin
    packet = '0;
    packet.slots[0] = base_event(64'd0, 32'h00700293, 32'h00000000);
    packet.slots[0].rd_addr = 5'd5;
    packet.slots[0].rd_value = 32'd7;
    packet.slots[0].rd_write_mask = 32'hffffffff;
    packet.slots[1] = base_event(64'd1, 32'h00528313, 32'h00000004);
    packet.slots[1].rs1_addr = 5'd5;
    packet.slots[1].rs1_value = 32'd7;
    packet.slots[1].rd_addr = 5'd6;
    packet.slots[1].rd_value = 32'd12;
    packet.slots[1].rd_write_mask = 32'hffffffff;
    emit_packet(packet);

    packet = '0;
    packet.slots[0] = base_event(64'd2, 32'h006283b3, 32'h00000008);
    packet.slots[0].rs1_addr = 5'd5;
    packet.slots[0].rs1_value = 32'd7;
    packet.slots[0].rs2_addr = 5'd6;
    packet.slots[0].rs2_value = 32'd12;
    packet.slots[0].rd_addr = 5'd7;
    packet.slots[0].rd_value = 32'd19;
    packet.slots[0].rd_write_mask = 32'hffffffff;
    packet.slots[1] = base_event(64'd3, 32'h00638463, 32'h0000000c);
    packet.slots[1].rs1_addr = 5'd7;
    packet.slots[1].rs1_value = 32'd19;
    packet.slots[1].rs2_addr = 5'd6;
    packet.slots[1].rs2_value = 32'd12;
    emit_packet(packet);

    packet = '0;
    packet.slots[0] = base_event(64'd4, 32'h00138413, 32'h00000010);
    packet.slots[0].rs1_addr = 5'd7;
    packet.slots[0].rs1_value = 32'd19;
    packet.slots[0].rd_addr = 5'd8;
    packet.slots[0].rd_value = 32'd20;
    packet.slots[0].rd_write_mask = 32'hffffffff;
    emit_packet(packet);
    $finish;
  end
endmodule
`default_nettype wire
