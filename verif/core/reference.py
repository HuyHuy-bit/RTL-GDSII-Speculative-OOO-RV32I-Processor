"""Architectural RV32 interpreter for the serialized core tests."""

import json
from pathlib import Path

MASK = 0xffffffff
ROOT = Path(__file__).resolve().parents[2]
PLATFORM = json.loads((ROOT / 'config/platform.yaml').read_text())
CSRS = {int(c['address'], 0): c for c in PLATFORM['csrs']}


def signed(value, bits=32):
    return (value ^ (1 << (bits-1))) - (1 << (bits-1))


def unpack_event(words):
    layout = json.loads((ROOT / 'config/commit_event.yaml').read_text())
    packed = sum(int(word, 16) << (32*i) for i, word in enumerate(words))
    csr_bits = sum(f['width'] for f in layout['csr_fields'])
    scalar_bits = sum(f['width'] for f in layout['slot_fields'])
    event_bits = scalar_bits + 4*csr_bits
    assert packed >> event_bits == 0, 'inactive slot is not zero'
    def fields(value, definitions):
        result = {}
        for field in reversed(definitions):
            result[field['name']] = value & ((1 << field['width']) - 1)
            value >>= field['width']
        return result
    event = fields(packed >> (4*csr_bits), layout['slot_fields'])
    event['csr_effects'] = []
    for i in range(4):
        effect = fields(packed >> (i*csr_bits), layout['csr_fields'])
        if effect['valid']:
            event['csr_effects'].append(effect)
        else:
            assert not any(effect.values()), 'inactive CSR effect is not zero'
    return event


class Reference:
    def __init__(self, image, mode='normal'):
        self.memory = bytearray(image) + bytearray(65536-len(image))
        self.mmio = {}
        self.registers = [None]*32
        self.registers[0] = 0
        self.pc = 0
        self.order = 0
        self.csrs = {a: int(c['reset'], 0) for a, c in CSRS.items()}
        self.mode = mode

    def read(self, address, size):
        return sum((self.memory[a] if a < len(self.memory) else self.mmio.get(a, 0)) << (8*i)
                   for i, a in enumerate(range(address, address+size)))

    def effect(self, address, value, mask, reason):
        definition = CSRS[address]
        return dict(valid=1, address=address, old_value=self.csrs[address], new_value=value & MASK,
                    read_mask=int(definition['write_mask'], 0) | int(definition['fixed_mask'], 0),
                    write_mask=mask, mask_reason=reason)

    def step(self):
        fetch_fault = not 0 <= self.pc < 65536 or (self.mode == 'fetch_fault' and self.pc & ~31 == 0x300)
        ins = 0 if fetch_fault else self.read(self.pc, 4)
        opcode, f3, f7 = ins & 127, (ins >> 12) & 7, ins >> 25
        rd, r1, r2 = (ins >> 7) & 31, (ins >> 15) & 31, (ins >> 20) & 31
        imm = signed(ins >> 20, 12)
        source1 = r1 if opcode in (0x13, 0x33, 0x63, 0x67, 0x03, 0x23) or (opcode == 0x73 and f3 in (1, 2, 3)) else 0
        source2 = r2 if opcode in (0x33, 0x63, 0x23) else 0
        legal = (opcode in (0x37, 0x17, 0x6f)
                 or (opcode == 0x13 and (f3 not in (1, 5) or (f3 == 1 and f7 == 0) or (f3 == 5 and f7 in (0, 32))))
                 or (opcode == 0x33 and (f7 == 0 or (f7 == 32 and f3 in (0, 5))))
                 or (opcode == 0x63 and f3 in (0, 1, 4, 5, 6, 7))
                 or (opcode == 0x67 and f3 == 0)
                 or (opcode == 0x03 and f3 in (0, 1, 2, 4, 5))
                 or (opcode == 0x23 and f3 in (0, 1, 2))
                 or (opcode == 0x0f and f3 in (0, 1))
                 or (opcode == 0x73 and (f3 in (1, 2, 3, 5, 6, 7) or ins in (0x73, 0x100073, 0x30200073, 0x10500073))))
        if not legal: source1 = source2 = 0
        a, b = self.registers[source1], self.registers[source2]
        assert a is not None and b is not None, f'reference read of uninitialized register at {self.pc:x}'
        event = dict(valid=1, order=self.order, instruction=ins, privilege=3, pc_before=self.pc,
                     pc_after=(self.pc+4)&MASK, rs1_addr=source1, rs1_value=a, rs2_addr=source2, rs2_value=b,
                     retired=1, csr_effects=[])
        value = None
        trap = None
        if fetch_fault: trap = (1, self.pc)
        elif not legal: trap = (2, ins)
        elif opcode in (0x13, 0x33):
            v = imm & MASK if opcode == 0x13 else b
            if f3 == 0: value = a-v if opcode == 0x33 and f7 == 32 else a+v
            elif f3 == 1: value = a << (v & 31)
            elif f3 == 2: value = int(signed(a) < signed(v))
            elif f3 == 3: value = int(a < v)
            elif f3 == 4: value = a ^ v
            elif f3 == 5: value = (signed(a) if f7 == 32 else a) >> (v & 31)
            elif f3 == 6: value = a | v
            else: value = a & v
        elif opcode in (0x37, 0x17): value = (ins & 0xfffff000) + (self.pc if opcode == 0x17 else 0)
        elif opcode in (0x6f, 0x67, 0x63):
            if opcode == 0x6f:
                offset = signed(((ins >> 31) << 20) | (((ins >> 12) & 255) << 12) | (((ins >> 20) & 1) << 11) | (((ins >> 21) & 1023) << 1), 21)
                event['pc_after'] = (self.pc + offset) & MASK
                value = self.pc+4
            elif opcode == 0x67:
                event['pc_after'] = (a+imm) & 0xfffffffe
                value = self.pc+4
            else:
                offset = signed(((ins >> 31) << 12) | (((ins >> 7) & 1) << 11) | (((ins >> 25) & 63) << 5) | (((ins >> 8) & 15) << 1), 13)
                take = {0: a == b, 1: a != b, 4: signed(a) < signed(b), 5: signed(a) >= signed(b), 6: a < b, 7: a >= b}[f3]
                if take: event['pc_after'] = (self.pc+offset)&MASK
            if event['pc_after'] & 3: trap = (0, event['pc_after'])
        elif opcode in (0x03, 0x23):
            store = opcode == 0x23
            if store: imm = signed(((ins >> 25) << 5) | rd, 12)
            address = (a+imm)&MASK
            size = 1 << (f3 & 3)
            region = next((r for r in PLATFORM['memory']['regions'] if int(r['base'], 0) <= address < int(r['base'], 0)+int(r['size'], 0)), None)
            if address % size: trap = (6 if store else 4, address)
            elif region is None or not region['write' if store else 'read']: trap = (7 if store else 5, address)
            elif not store and self.mode == 'load_fault' and address & ~31 == 0x900: trap = (5, address)
            else:
                mask = ((1 << size)-1) << (address & 3)
                event.update(mem_valid=1, mem_address=address)
                if store:
                    event.update(mem_write_mask=mask, mem_write_data=(b & ((1 << (8*size))-1)) << (8*(address & 3)))
                    for i in range(size):
                        if address+i < len(self.memory): self.memory[address+i] = (b >> (8*i)) & 255
                        else: self.mmio[address+i] = (b >> (8*i)) & 255
                else:
                    raw = self.read(address, size)
                    event.update(mem_read_mask=mask, mem_read_data=raw << (8*(address & 3)))
                    value = signed(raw, size*8) if f3 < 4 else raw
        elif opcode == 0x73:
            if f3:
                address = ins >> 20
                if address in (0xb00, 0xb80):
                    raise ValueError('Cycle-counter timing is checked by csr_single_tb, not this interpreter')
                write = f3 & 3 == 1 or r1 != 0
                definition = CSRS.get(address)
                if definition is None or (write and definition['access'] == 'ro'): trap = (2, ins)
                else:
                    value = self.csrs[address]
                    operand = r1 if f3 & 4 else a
                    new = operand if f3 & 3 == 1 else value | operand if f3 & 3 == 2 else value & ~operand
                    mask = int(definition['write_mask'], 0) if write else 0
                    new = (value & ~mask) | (new & mask)
                    event['csr_effects'] = [self.effect(address, new, mask, 1)]
            elif ins == 0x73: trap = (11, 0)
            elif ins == 0x100073: trap = (3, self.pc)
            elif ins == 0x30200073:
                event['pc_after'] = self.csrs[0x341]
                status = (self.csrs[0x300] & ~0x88) | 0x80 | ((self.csrs[0x300] >> 4) & 8)
                event['csr_effects'] = [self.effect(0x300, status, 0x88, 3)]
        if trap:
            cause, tval = trap
            event.update(trap=1, retired=0, trap_cause=cause, trap_value=tval, pc_after=self.csrs[0x305])
            status = (self.csrs[0x300] & ~0x88) | ((self.csrs[0x300] & 8) << 4)
            event['csr_effects'] = [self.effect(addr, val, mask, 2) for addr, val, mask in
                                    [(0x300, status, 0x88), (0x341, self.pc, 0xfffffffc), (0x342, cause, MASK), (0x343, tval, MASK)]]
        elif value is not None and rd:
            self.registers[rd] = value & MASK
            event.update(rd_addr=rd, rd_value=value & MASK, rd_write_mask=MASK)
        inhibit = self.csrs[0x320] & 4
        explicit_instret = any(e['address'] in (0xb02, 0xb82) and e['write_mask'] for e in event['csr_effects'])
        if event['retired'] and not inhibit and not explicit_instret:
            count = ((self.csrs[0xb82] << 32) | self.csrs[0xb02]) + 1
            self.csrs[0xb02], self.csrs[0xb82] = count & MASK, (count >> 32) & MASK
        for e in event['csr_effects']:
            if e['write_mask']: self.csrs[e['address']] = e['new_value']
        self.pc = event['pc_after']
        self.order += 1
        return event
