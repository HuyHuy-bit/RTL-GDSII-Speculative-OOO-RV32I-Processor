"""Load a little-endian RV32 executable into the core's BRAM image."""
import struct


def load_elf(data, memory_bytes=65536):
    def unpack(fmt, offset):
        if offset < 0 or offset + struct.calcsize(fmt) > len(data):
            raise ValueError('truncated ELF structure')
        return struct.unpack_from(fmt, data, offset)

    header = unpack('<16sHHIIIIIHHHHHH', 0)
    ident, kind, machine, version, entry, phoff, shoff, _, ehsize, phsize, phnum, shsize, shnum, _ = header
    if ident[:7] != b'\x7fELF\x01\x01\x01' or (kind, machine, version, entry, ehsize) != (2, 243, 1, 0, 52):
        raise ValueError('expected RV32 little-endian executable with entry at reset PC 0')
    if phsize != 32 or not phnum or shsize != 40 or not shnum:
        raise ValueError('ELF load segments and symbol sections required')
    image = bytearray(memory_bytes)
    segments = []
    for i in range(phnum):
        kind, offset, virtual, physical, filesz, memsz, flags, _ = unpack('<8I', phoff+i*phsize)
        if kind != 1: continue
        if virtual != physical or filesz > memsz or offset+filesz > len(data) or physical+memsz > memory_bytes:
            raise ValueError('invalid or out-of-BRAM ELF segment')
        if any(physical < end and start < physical+memsz for start, end, _ in segments):
            raise ValueError('overlapping ELF load segments')
        image[physical:physical+filesz] = data[offset:offset+filesz]
        segments.append((physical, physical+memsz, flags))
    if not any(start == 0 and end >= 4 and flags & 1 for start, end, flags in segments):
        raise ValueError('reset instruction is not executable')
    sections = [unpack('<10I', shoff+i*shsize) for i in range(shnum)]
    symbols = {}
    for section in sections:
        _, kind, _, _, offset, size, link, _, _, entsize = section
        if kind != 2: continue
        if entsize != 16 or size % 16 or link >= shnum:
            raise ValueError('invalid ELF symbol table')
        strings = sections[link]
        if strings[1] != 3 or strings[4]+strings[5] > len(data):
            raise ValueError('invalid ELF string table')
        names = data[strings[4]:strings[4]+strings[5]]
        for pos in range(offset, offset+size, 16):
            name, value, _, _, _, index = unpack('<IIIBBH', pos)
            if not index: continue
            end = names.find(b'\0', name)
            if end < 0: raise ValueError('invalid ELF symbol name')
            symbols[names[name:end].decode('ascii')] = value
    tohost = symbols.get('tohost')
    if tohost is None or tohost % 8 or not any(start <= tohost and tohost+8 <= end and flags & 2 for start, end, flags in segments):
        raise ValueError('aligned writable tohost symbol required')
    if any(image[tohost:tohost+8]): raise ValueError('tohost must start at zero')
    return image, symbols
