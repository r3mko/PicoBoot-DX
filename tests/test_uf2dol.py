"""Tests for tools/uf2dol.py (PicoBoot payload .uf2 -> DOL), and for both tools together."""

import os
import random
import shutil
import struct
import tempfile
import unittest

from helpers import (IPL_DOL, PAYLOAD_BASE, header_array_words, load_tool, make_payload,
                     read_ipl_dol, run_tool, uf2_block, uf2_blocks)

pi = load_tool("process_ipl")
ud = load_tool("uf2dol")

IMG = bytes(pi.flatten_dol(read_ipl_dol())[2])     # the bundled IPL's image, 60512 bytes


class Uf2DolTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.out = os.path.join(self.tmp, "out.dol")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def convert(self, blocks):
        path = os.path.join(self.tmp, "in.uf2")
        with open(path, "wb") as f:
            f.write(b"".join(blocks))
        return run_tool("uf2dol", path, self.out)

    def dol_image(self):
        with open(self.out, "rb") as f:
            dol = f.read()
        header = struct.unpack(">64I", dol[:256])
        self.assertEqual((header[0], header[18], header[36], header[56]),
                         (0x100, 0x81300000, len(dol) - 0x100, 0x81300000))
        return dol[0x100:]

    def assert_fails(self, result, message):
        self.assertEqual(result.returncode, 255)
        self.assertTrue(result.stderr.startswith("Error: "), result.stderr)
        self.assertIn(message, result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse(os.path.exists(self.out), "no output file on error")

    def test_descramble_matches_scramble(self):
        data = bytearray(random.Random(2).randbytes(3000))
        self.assertEqual(ud.descramble(bytearray(data)), pi.scramble(bytearray(data)))

    def test_round_trip_gives_back_the_exact_image(self):
        result = self.convert(uf2_blocks(make_payload(IMG, pi.scramble)))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.dol_image(), IMG)

    def test_round_trip_of_an_odd_length_image(self):
        img = IMG + b"\x11\x22\x33"
        result = self.convert(uf2_blocks(make_payload(img, pi.scramble)))
        self.assertEqual(result.returncode, 0, result.stderr)
        data = self.dol_image()
        self.assertEqual(data[:len(img)], img)
        self.assertEqual(len(data), len(img) + 1, "padded to 4 bytes")

    def test_extra_block_after_the_payload_is_ignored(self):
        blocks = uf2_blocks(make_payload(IMG, pi.scramble))
        blocks.append(uf2_block(0x10FFFF00, bytes(256), family=0xE48BFF57))
        self.assertEqual(self.convert(blocks).returncode, 0)
        self.assertEqual(self.dol_image(), IMG)

    def test_block_order_in_the_file_does_not_matter(self):
        blocks = uf2_blocks(make_payload(IMG, pi.scramble))
        random.Random(3).shuffle(blocks)
        self.assertEqual(self.convert(blocks).returncode, 0)
        self.assertEqual(self.dol_image(), IMG)

    def test_address_range_uses_the_highest_block(self):
        payload = make_payload(IMG, pi.scramble)
        blocks = uf2_blocks(payload)
        last = len(blocks) - 1
        short = len(payload) - 256 * last                 # real bytes in the highest block
        blocks[last] = uf2_block(PAYLOAD_BASE + 256 * last, payload[256 * last:], last, len(blocks))
        blocks.insert(0, blocks.pop())                    # ...and not last in the file
        result = self.convert(blocks)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"0x{PAYLOAD_BASE:08X} - 0x{PAYLOAD_BASE + 256 * last + short:08X}", result.stdout)

    def test_broken_payloads_are_rejected(self):
        payload = make_payload(IMG, pi.scramble)

        def patched(offset, value):
            data = bytearray(payload)
            data[offset:offset + len(value)] = value
            return uf2_blocks(data)

        missing = uf2_blocks(payload)
        del missing[100]
        cases = [
            ("block missing", missing, f"UF2 contains {100 * 256} contiguous bytes"),   # stops at the gap
            ("size too large", patched(8, struct.pack(">I", len(payload) * 2)), "Invalid payload size"),
            ("size too small", patched(8, struct.pack(">I", 8)), "Invalid payload size"),
            ("size not a multiple of 4", patched(8, struct.pack(">I", len(payload) + 2)), "Invalid payload size"),
            ("footer missing", patched(len(payload) - 4, b"XXXX"), "PICO footer"),
            ("no UF2 blocks", [bytes(1024)], "valid IPLBOOT header"),
        ]
        for name, blocks, message in cases:
            with self.subTest(name):
                self.assert_fails(self.convert(blocks), message)


class ToolsAgreeTest(unittest.TestCase):
    def test_payload_round_trip_through_both_tools_gives_the_same_ipl(self):
        """DOL -> payload .uf2 -> uf2dol.py -> DOL -> process_ipl.py == process_ipl.py on the DOL."""
        tmp = tempfile.mkdtemp()
        try:
            uf2, dol, direct, via_uf2 = (os.path.join(tmp, n) for n in ("p.uf2", "p.dol", "a.h", "b.h"))
            with open(uf2, "wb") as f:
                f.write(b"".join(uf2_blocks(make_payload(IMG, pi.scramble))))
            for result in (run_tool("uf2dol", uf2, dol),
                           run_tool("process_ipl", IPL_DOL, direct),
                           run_tool("process_ipl", dol, via_uf2)):
                self.assertEqual(result.returncode, 0, result.stderr)
            with open(direct) as a, open(via_uf2) as b:
                self.assertEqual(header_array_words(b.read()), header_array_words(a.read()))
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
