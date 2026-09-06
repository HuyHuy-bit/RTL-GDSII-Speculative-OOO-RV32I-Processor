"""Directed and seeded instruction streams for core bring-up."""
import random
import struct


def i(rd, rs, value, f3=0, op=0x13):
    return ((value & 4095) << 20) | (rs << 15) | (f3 << 12) | (rd << 7) | op


def r(rd, a, b, f3=0, alternate=0):
    return (alternate << 25) | (b << 20) | (a << 15) | (f3 << 12) | (rd << 7) | 0x33


def store(a, b, value, f3):
    value &= 4095
    return ((value >> 5) << 25) | (b << 20) | (a << 15) | (f3 << 12) | ((value & 31) << 7) | 0x23


def branch(a, b, offset, f3=0):
    v = offset & 8191
    return ((v >> 12) << 31) | (((v >> 5) & 63) << 25) | (b << 20) | (a << 15) | (f3 << 12) | (((v >> 1) & 15) << 8) | (((v >> 11) & 1) << 7) | 0x63


def jal(rd, offset):
    v = offset & 0x1fffff
    return ((v >> 20) << 31) | (((v >> 1) & 1023) << 21) | (((v >> 11) & 1) << 20) | (((v >> 12) & 255) << 12) | (rd << 7) | 0x6f


def csr(rd, src, addr, f3):
    return (addr << 20) | (src << 15) | (f3 << 12) | (rd << 7) | 0x73


def constant(rd, value):
    return [((value+0x800) & 0xfffff000) | (rd << 7) | 0x37, i(rd, rd, value)]


def random_alu(seed, count):
    rng = random.Random(seed)
    words = []
    for _ in range(count):
        rd, a, b, f3 = (rng.randrange(32), rng.randrange(32), rng.randrange(32), rng.randrange(8))
        if rng.randrange(2):
            alternate = 32 if f3 in (0, 5) and rng.randrange(2) else 0
            words.append(r(rd, a, b, f3, alternate))
        else:
            imm = rng.randrange(4096)
            if f3 in (1, 5): imm = rng.randrange(32) | (1024 if f3 == 5 and rng.randrange(2) else 0)
            words.append(i(rd, a, imm, f3))
    return words


def program(seed, mode='normal'):
    words = [i(reg, 0, reg*13-512) for reg in range(1,32)]
    if mode in ('load_fault', 'protocol_error', 'reserved_status', 'wrong_id', 'reset_data', 'payload_error'):
        words += constant(1, 0x900) + [i(2, 1, 0, 2, 3)]
    elif mode == 'store_fault':
        words += constant(1, 0x8000) + [store(1, 0, 0, 2)]
    elif mode == 'fetch_fault':
        words += constant(1, 0x300) + [i(0, 1, 0, 0, 0x67)]
    else:
        words += [i(1, 0, -1), i(2, 0, 1), i(3, 0, 0)]
        for f3 in (0,1,4,5,6,7):
            for a,b in ((1,2),(2,1),(1,1)):
                words += [branch(a,b,8,f3), i(4,4,1)]
        words += [jal(5,8), i(6,6,1), 0x00000397]
        target = 0x400 + (len(words)+3)*4
        words += constant(5, target) + [i(5,5,1,0,0x67)]
        words += constant(28,0x8000) + constant(27,0x89abcdef)
        for size, offsets in ((0,range(4)),(1,(0,2)),(2,(0,))):
            for offset in offsets:
                words += [store(28,27,offset,size), i(9,28,offset,size,3)]
                if size < 2: words += [i(10,28,offset,size+4,3)]
        words += [i(0,28,0,2,3)]
        for base in (0x10000000,0x10001000):
            words += constant(28,base) + [store(28,27,1,0), i(11,28,1,4,3)]
        words += constant(28,0x8000)
        words += [i(7,28,1,2,3), store(28,27,1,1)]
        words += constant(28,0x20000000) + [i(7,28,0,2,3),store(28,27,0,2)]
        words += [jal(5,2), branch(1,1,2), branch(1,2,2), i(5,0,2), i(5,5,1,0,0x67)]
        words += [0, 0x02001013, 0x02000033, 0x73, 0x100073, 0x10500073, 0x0000000f, 0x0000100f]
        words += constant(16,0x12345678)
        for f3 in (1,2,3,5,6,7):
            words += [csr(17,16,0x340,f3), csr(18,0,0x340,f3), csr(0,16,0x340,f3)]
        for addr in (0x301,0x304,0x310,0x344,0xf11,0xf12,0xf13,0xf14,0xf15):
            words += [csr(19,0,addr,2), csr(20,16,addr,1)]
        words += [csr(20,0,0xfff,2), csr(0,8,0x300,5), 0x73]
        words += [csr(20,0,0xb02,2), csr(0,0,0xb02,5), csr(20,0,0xb02,2), csr(0,4,0x320,5),csr(20,0,0xb02,2),csr(0,0,0x320,5)]
        words += constant(28,0x200) + constant(27,i(10,0,77))
        words += [store(28,27,0,2),0x100f,i(1,28,0,0,0x67)]
        words += random_alu(seed,1000)
    words += [branch(0,0,0)]
    image = bytearray(0x400+len(words)*4)
    struct.pack_into('<I',image,0,jal(0,0x400))
    handler = [csr(30,0,0x341,2),i(30,30,4),csr(0,30,0x341,1),0x30200073]
    for n, word in enumerate(handler): struct.pack_into('<I',image,0x100+4*n,word)
    struct.pack_into('<II',image,0x200,i(10,0,0),i(0,1,0,0,0x67))
    for n, word in enumerate(words): struct.pack_into('<I',image,0x400+4*n,word)
    return bytes(image)
