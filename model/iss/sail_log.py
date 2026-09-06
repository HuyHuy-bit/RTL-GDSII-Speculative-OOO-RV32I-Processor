"""Normalize observed Sail 0.10 state changes into architectural events."""
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
CSRS = {int(c['address'],0): c for c in json.loads((ROOT/'config/platform.yaml').read_text())['csrs']}
HEADER = re.compile(r'^\[(\d+)\] \[M\]: 0x([\da-fA-F]+) \(0x([\da-fA-F]+)\) ')
GPR = re.compile(r'^x(\d+) <- 0x([\da-fA-F]+)$')
CSR = re.compile(r'^CSR \w+ \(0x([\da-fA-F]+)\) (<-|->) 0x([\da-fA-F]+)$')
MEM = re.compile(r'^mem\[([RW]),0x([\da-fA-F]+)\] (<-|->) 0x([\da-fA-F]+)$')


class SailLogError(ValueError):
    pass


def require(condition, message):
    if not condition: raise SailLogError(message)


def sources(ins):
    op, f3, f7 = ins & 127, (ins >> 12) & 7, ins >> 25
    if op == 0x33 and not (f7 == 0 or (f7 == 32 and f3 in (0,5))): return 0,0
    if op == 0x13 and ((f3 == 1 and f7 != 0) or (f3 == 5 and f7 not in (0,32))): return 0,0
    if op == 0x03 and f3 not in (0,1,2,4,5): return 0,0
    if op == 0x23 and f3 not in (0,1,2): return 0,0
    if op == 0x63 and f3 not in (0,1,4,5,6,7): return 0,0
    if op == 0x67 and f3 != 0: return 0,0
    a = (ins >> 15) & 31 if op in (0x13,0x33,0x03,0x23,0x63,0x67) or (op == 0x73 and f3 in (1,2,3)) else 0
    b = (ins >> 20) & 31 if op in (0x33,0x23,0x63) else 0
    return a,b


def frames(trace):
    result = []
    for block in re.split(r'\n\s*\n', trace):
        lines = block.splitlines()
        headers = [(n,HEADER.match(line)) for n,line in enumerate(lines) if HEADER.match(line)]
        require(len(headers) <= 1, 'missing Sail step delimiter')
        if headers:
            pos, match = headers[0]
            order, pc, ins = match.groups()
            frame = {'order':int(order), 'pc':int(pc,16), 'ins':int(ins,16), 'lines':lines[pos+1:]}
        elif any('trapping from' in line for line in lines):
            writes = {int(m[1],16):int(m[3],16) for line in lines if (m := CSR.match(line)) and m[2] == '<-'}
            require(result and writes.get(0x342) == 1 and 0x341 in writes, 'unframed exception is not an instruction access fault')
            frame = {'order':result[-1]['order']+1, 'pc':writes[0x341], 'ins':0, 'lines':lines}
        else:
            require(not block.strip(), 'unrecognized Sail trace block')
            continue
        require(frame['order'] == len(result), 'missing or reordered Sail instruction')
        result.append(frame)
    require(len(result) >= 2, 'Sail trace needs a successor instruction')
    return result


def parse_sail_log(trace):
    stream = frames(trace)
    regs = [None]*32; regs[0] = 0
    state = {addr:int(c['reset'],0) for addr,c in CSRS.items()}
    state[0x300] = state[0x305] = 0
    events = []
    for frame, successor in zip(stream, stream[1:]):
        ins = frame['ins']; op = ins & 127; f3 = (ins >> 12) & 7
        a,b = sources(ins)
        require(regs[a] is not None and regs[b] is not None, 'uninitialized source in Sail program')
        event = dict(valid=1, order=frame['order'], instruction=ins, privilege=3,
                     pc_before=frame['pc'], pc_after=successor['pc'], rs1_addr=a, rs1_value=regs[a],
                     rs2_addr=b, rs2_value=regs[b], retired=1, csr_effects=[])
        writes = {}; reads = {}; destinations = []; memory = []; trap = False
        for line in frame['lines']:
            if m := GPR.match(line): destinations.append((int(m[1]),int(m[2],16)))
            elif m := CSR.match(line):
                address, direction, value = int(m[1],16),m[2],int(m[3],16)
                target = writes if direction == '<-' else reads
                require(address not in target, 'duplicate Sail CSR access')
                target[address] = value
            elif m := MEM.match(line): memory.append(m.groups())
            elif line.startswith('trapping from M to M '): trap = True
            elif line.startswith(('handling exc#','ret-ing from M to M')): pass
            elif line.strip(): raise SailLogError(f'unrecognized Sail effect: {line}')
        require(len(destinations) <= 1, 'multiple Sail GPR writes')
        if destinations:
            rd,value = destinations[0]
            require(not trap and 0 < rd < 32 and rd == (ins >> 7) & 31, 'invalid Sail destination')
            event.update(rd_addr=rd, rd_value=value, rd_write_mask=0xffffffff)
        expected_csrs = []
        reason = 1
        if trap:
            require(not memory, 'faulting instruction has a memory effect')
            require(all(addr in writes for addr in (0x300,0x341,0x342,0x343)), 'incomplete Sail trap metadata')
            require(writes[0x341] == frame['pc'], 'Sail trap mepc does not match instruction')
            event.update(trap=1, retired=0, trap_cause=writes[0x342], trap_value=writes[0x343])
            expected_csrs = [0x300,0x341,0x342,0x343]; reason = 2
        elif ins == 0x30200073:
            expected_csrs = [0x300]; reason = 3
        elif op == 0x73 and f3 in (1,2,3,5,6,7):
            expected_csrs = [ins >> 20]
        for addr in expected_csrs:
            require(addr in state and addr not in (0xb00,0xb02,0xb80,0xb82), 'CSR outside shared differential profile')
            old = state[addr]
            if addr in reads: require(reads[addr] == old, 'Sail CSR read contradicts recorded state')
            if reason == 1 and destinations: require(destinations[0][1] == old, 'Sail CSR result contradicts recorded state')
            write = reason != 1 or f3 & 3 == 1 or (ins >> 15) & 31 != 0
            require(addr in writes if write else addr in reads, 'missing Sail CSR observation')
            new = writes.get(addr, old)
            c = CSRS[addr]
            event['csr_effects'].append(dict(valid=1,address=addr,old_value=old,new_value=new,
                read_mask=int(c['write_mask'],0)|int(c['fixed_mask'],0),
                write_mask=int(c['write_mask'],0) if write else 0,mask_reason=reason))
        for addr,value in writes.items():
            if addr not in expected_csrs:
                require(reason in (2,3) and addr == 0x310 and value == state[addr], 'unexpected Sail CSR write')
        require(set(reads) <= set(expected_csrs), 'unexpected Sail CSR read')
        if not trap and op in (0x03,0x23):
            require(len(memory) == 1, 'missing or multiple Sail data accesses')
            kind, address, direction, value = memory[0]
            size = 1 << (f3 & 3); address = int(address,16)
            require(len(value) == size*2 and address % size == 0, 'Sail access size/alignment differs from instruction')
            is_store = op == 0x23
            require((kind,direction) == (('W','<-') if is_store else ('R','->')), 'Sail memory direction differs')
            lane = address & 3; prefix = 'write' if is_store else 'read'
            event.update(mem_valid=1, mem_address=address)
            event['mem_'+prefix+'_mask'] = ((1 << size)-1) << lane
            event['mem_'+prefix+'_data'] = int(value,16) << (8*lane)
        else: require(not memory, 'unexpected Sail data access')
        if destinations: regs[destinations[0][0]] = destinations[0][1]
        state.update(writes)
        events.append(event)
    return events
