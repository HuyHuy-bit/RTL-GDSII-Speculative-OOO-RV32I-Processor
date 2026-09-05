#!/usr/bin/env python3
"""Normalize the pinned Spike commit log for the lockstep smoke program."""

from __future__ import annotations

import re


COMMIT = re.compile(
    r"^core\s+\d+:\s+([0-3])\s+(0x[0-9a-f]+)\s+\((0x[0-9a-f]+)\)(.*)$"
)
DESTINATION = re.compile(r"\bx(\d+)\s+(0x[0-9a-f]+)")


class SpikeLogError(ValueError):
    pass


def _sign_extend(value: int, bits: int) -> int:
    sign = 1 << (bits - 1)
    return (value ^ sign) - sign


def _branch_offset(instruction: int) -> int:
    immediate = (
        ((instruction >> 31) & 1) << 12
        | ((instruction >> 7) & 1) << 11
        | ((instruction >> 25) & 0x3f) << 5
        | ((instruction >> 8) & 0xf) << 1
    )
    return _sign_extend(immediate, 13)


def _decode_sources(instruction: int) -> tuple[int, int]:
    opcode = instruction & 0x7f
    if opcode == 0x13:
        return (instruction >> 15) & 0x1f, 0
    if opcode in (0x33, 0x63):
        return (instruction >> 15) & 0x1f, (instruction >> 20) & 0x1f
    raise SpikeLogError(f"smoke adapter does not support opcode 0x{opcode:02x}")


def _next_pc(pc: int, instruction: int, rs1_value: int, rs2_value: int) -> int:
    opcode = instruction & 0x7f
    if opcode != 0x63:
        return pc + 4
    funct3 = (instruction >> 12) & 7
    if funct3 != 0:
        raise SpikeLogError("smoke adapter supports BEQ only")
    return pc + (_branch_offset(instruction) if rs1_value == rs2_value else 4)


def parse_spike_log(output: str, address_bias: int, region_size: int) -> list[dict]:
    registers = [0] * 32
    events = []
    for line in output.splitlines():
        match = COMMIT.match(line)
        if match is None:
            continue
        privilege, pc_text, instruction_text, tail = match.groups()
        pc = int(pc_text, 16)
        if not address_bias <= pc < address_bias + region_size:
            continue
        instruction = int(instruction_text, 16)
        rs1_addr, rs2_addr = _decode_sources(instruction)
        rs1_value = registers[rs1_addr]
        rs2_value = registers[rs2_addr]
        destination = DESTINATION.search(tail)
        rd_addr = 0
        rd_value = 0
        rd_mask = 0
        if destination is not None:
            rd_addr = int(destination.group(1))
            rd_value = int(destination.group(2), 16)
            encoded_rd = (instruction >> 7) & 0x1f
            if rd_addr != encoded_rd or rd_addr == 0:
                raise SpikeLogError("Spike destination disagrees with the instruction encoding")
            rd_mask = 0xffffffff
        event = {
            "valid": 1,
            "order": len(events),
            "instruction": instruction,
            "privilege": int(privilege),
            "pc_before": pc - address_bias,
            "pc_after": _next_pc(pc, instruction, rs1_value, rs2_value) - address_bias,
            "rs1_addr": rs1_addr,
            "rs1_value": rs1_value,
            "rs2_addr": rs2_addr,
            "rs2_value": rs2_value,
            "rd_addr": rd_addr,
            "rd_value": rd_value,
            "rd_write_mask": rd_mask,
            "retired": 1,
        }
        events.append(event)
        if rd_addr:
            registers[rd_addr] = rd_value
    return [{"slots": [*events[index:index + 2], *({} for _ in range(2 - len(events[index:index + 2])))]}
            for index in range(0, len(events), 2)]
