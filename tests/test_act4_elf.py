import struct
import unittest

from verif.arch.elf_image import load_elf


def fixture():
    data = bytearray(0x400)
    ident = b'\x7fELF\x01\x01\x01'+bytes(9)
    struct.pack_into('<16sHHIIIIIHHHHHH', data, 0, ident, 2, 243, 1, 0, 52, 0x200, 0, 52, 32, 1, 40, 3, 0)
    struct.pack_into('<8I', data, 52, 1, 0x100, 0, 0, 64, 128, 7, 4)
    struct.pack_into('<I', data, 0x100, 0x13)
    names = b'\0tohost\0rvtest_sig_begin\0'
    data[0x300:0x300+len(names)] = names
    struct.pack_into('<10I', data, 0x228, 0, 3, 0, 0, 0x300, len(names), 0, 0, 1, 0)
    struct.pack_into('<10I', data, 0x250, 0, 2, 0, 0, 0x340, 48, 1, 0, 4, 16)
    struct.pack_into('<IIIBBH', data, 0x350, 1, 32, 8, 0x11, 0, 1)
    struct.pack_into('<IIIBBH', data, 0x360, 8, 48, 4, 0x11, 0, 1)
    return data


class Act4ElfTest(unittest.TestCase):
    def test_load_and_zero_fill(self):
        image, symbols = load_elf(fixture())
        self.assertEqual(len(image), 65536)
        self.assertEqual(image[:4], b'\x13\0\0\0')
        self.assertFalse(any(image[64:128]))
        self.assertEqual(symbols, {'tohost': 32, 'rvtest_sig_begin': 48})

    def test_reject_wrong_isa_and_entry(self):
        for offset, value in ((18, 62), (24, 4)):
            data = fixture()
            struct.pack_into('<H' if offset == 18 else '<I', data, offset, value)
            with self.assertRaises(ValueError): load_elf(data)

    def test_reject_truncated_structures(self):
        for length in (0, 51, 80, 0x270, 0x36f):
            with self.assertRaises(ValueError): load_elf(fixture()[:length])

    def test_reject_invalid_segment_sizes(self):
        for offset, value in ((52+16, 129), (52+20, 65537), (52+12, 4)):
            data = fixture()
            struct.pack_into('<I', data, offset, value)
            with self.assertRaises(ValueError): load_elf(data)

    def test_reject_overlapping_segments(self):
        data = fixture()
        struct.pack_into('<H', data, 44, 2)
        data[84:116] = data[52:84]
        with self.assertRaisesRegex(ValueError, 'overlapping'): load_elf(data)

    def test_reject_missing_or_invalid_tohost(self):
        for value in (33, 128):
            data = fixture()
            struct.pack_into('<I', data, 0x354, value)
            with self.assertRaisesRegex(ValueError, 'tohost'): load_elf(data)
        data = fixture()
        struct.pack_into('<H', data, 0x35e, 0)
        with self.assertRaisesRegex(ValueError, 'tohost'): load_elf(data)

    def test_reject_preinitialized_pass(self):
        data = fixture()
        data[0x120] = 1
        with self.assertRaisesRegex(ValueError, 'start at zero'): load_elf(data)

    def test_reject_nonexecutable_reset_or_readonly_tohost(self):
        for flags in (6, 5):
            data = fixture()
            struct.pack_into('<I', data, 52+24, flags)
            with self.assertRaises(ValueError): load_elf(data)


if __name__ == '__main__':
    unittest.main()
