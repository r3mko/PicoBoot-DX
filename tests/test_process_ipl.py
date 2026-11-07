"""Tests for tools/process_ipl.py (DOL -> scrambled ipl.h for the built-in IPL)."""

import hashlib
import os
import random
import re
import shutil
import tempfile
import unittest

from helpers import IPL_DOL, REPO, header_array_words, load_tool, make_dol, read_ipl_dol, run_tool

pi = load_tool("process_ipl")

# Keystream bytes 0x700-0x760: the 0x20 pipeline flush bytes and the start of the image.
# Recorded from process_ipl.scramble() on 2026-11-07. The built-in IPL scrambled with this
# keystream booted on a GameCube that day, so the vector is hardware-verified.
KEYSTREAM_700_760 = bytes.fromhex(
    "c8a75af9c348c36840eae22483a12be0d9b936e23b216f0d6176d5a35f355e7a"
    "a5dfc82a4652f9c6e01e82fb59d081708b0ade7091c6ed947d1bee1c5ff76492"
    "849a482bb94744790935f9b46eb1c37ee883b745d458ed167a2d207c13d3950f"
)

# SHA-256 of the ipl.h that `python3 tools/process_ipl.py assets/ipl/iplboot.dol <out>`
# produces (the same command CI uses). Update this on purpose when the bundled DOL or
# the output format changes.
GOLDEN_IPL_H_SHA256 = "2ec542391fb6bb22adfa49c756cfe94953989a49a36e01e0de89a718b2542bcc"


class ScrambleTest(unittest.TestCase):
    def test_keystream_matches_reference(self):
        self.assertEqual(bytes(pi.scramble(bytearray(0x760))[0x700:]), KEYSTREAM_700_760)

    def test_scrambling_twice_restores_the_data(self):
        data = bytearray(random.Random(1).randbytes(5000))
        self.assertEqual(pi.scramble(pi.scramble(bytearray(data))), data)


class FlattenDolTest(unittest.TestCase):
    def test_sections_are_placed_at_their_address_and_gaps_zero_filled(self):
        dol = make_dol([(0x81300000, b"\x11" * 16), (0x81300040, b"\x22" * 8)], entry=0x81300004)
        base, entry, img = pi.flatten_dol(bytearray(dol))
        self.assertEqual((base, entry), (0x81300000, 0x81300004))
        self.assertEqual(bytes(img), b"\x11" * 16 + bytes(0x30) + b"\x22" * 8)

    def test_section_order_in_the_file_does_not_matter(self):
        sections = [(0x81300000, b"\x11" * 16), (0x81300040, b"\x22" * 8)]
        _, _, forward = pi.flatten_dol(bytearray(make_dol(sections)))
        _, _, backward = pi.flatten_dol(bytearray(make_dol(sections[::-1])))
        self.assertEqual(forward, backward)

    def test_bss_and_empty_sections_are_ignored(self):
        dol = make_dol([(0x81300000, b"\x11" * 16), (0, b"")], bss=(0x81310000, 0x1000))
        _, _, img = pi.flatten_dol(bytearray(dol))
        self.assertEqual(bytes(img), b"\x11" * 16)

    def test_bundled_ipl_flattens_to_the_known_size(self):
        base, entry, img = pi.flatten_dol(read_ipl_dol())
        self.assertEqual((base, entry, len(img)), (0x81300000, 0x81300000, 60512))

    def test_malformed_dols_raise_a_clear_error(self):
        good = make_dol([(0x81300000, b"\x11" * 64)])
        cases = [
            ("short file", b"\0" * 100, "smaller than a DOL header"),
            ("no sections", make_dol([]), "no sections"),
            ("no load address", make_dol([(0, b"\x11" * 16)]), "no load address"),
            ("truncated", good[:len(good) - 1], "past the end of the file"),
            ("24 MB", make_dol([(0x80000000, b"\x11"), (0xFFFFFF00, b"\x22")]), "more than the 24 MB"),
        ]
        for name, dol, message in cases:
            with self.subTest(name), self.assertRaisesRegex(ValueError, message):
                pi.flatten_dol(bytearray(dol))


class HeaderOutputTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        out = os.path.join(cls.tmp, "ipl.h")
        cls.result = run_tool("process_ipl", IPL_DOL, out)
        with open(out) as f:
            cls.text = f.read()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_cli_succeeds(self):
        self.assertEqual(self.result.returncode, 0, self.result.stderr)

    def test_header_is_self_contained(self):
        self.assertTrue(self.text.startswith('#include <stdint.h>\n#include "pico.h"\n'))

    def test_comment_reports_image_and_array_size(self):
        words = header_array_words(self.text)
        sizes = re.search(r"image size: (\d+) bytes, scrambled size: (\d+) bytes", self.text)
        self.assertIsNotNone(sizes)
        self.assertEqual(int(sizes.group(1)), 60512)
        self.assertEqual(int(sizes.group(2)), len(words) * 4)

    def test_array_is_a_whole_number_of_1k_transfers(self):
        self.assertEqual(len(header_array_words(self.text)) % 256, 0)

    def test_matches_the_golden_header(self):
        self.assertEqual(hashlib.sha256(self.text.encode()).hexdigest(), GOLDEN_IPL_H_SHA256)


class CommandLineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.out = os.path.join(self.tmp, "ipl.h")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def write(self, name, data):
        path = os.path.join(self.tmp, name)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def assert_fails(self, result, message):
        self.assertEqual(result.returncode, 255)
        self.assertTrue(result.stderr.startswith("Error: "), result.stderr)
        self.assertIn(message, result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse(os.path.exists(self.out), "no output file on error")

    def test_wrong_entry_point_reports_actual_and_expected_values(self):
        dol = self.write("bad.dol", make_dol([(0x81300000, b"\x11" * 64)], entry=0x81300100))
        self.assert_fails(run_tool("process_ipl", dol, self.out), "0x81300100 / 0x01300000, expected 0x81300000 / 0x01300000")

    def test_truncated_dol_is_rejected(self):
        dol = self.write("cut.dol", bytes(read_ipl_dol()[:2000]))
        self.assert_fails(run_tool("process_ipl", dol, self.out), "file truncated?")

    def test_unknown_extension_is_rejected(self):
        path = self.write("iplboot.bin", bytes(read_ipl_dol()))
        self.assert_fails(run_tool("process_ipl", path, self.out), "Unknown input format")

    def test_missing_file_is_rejected(self):
        self.assert_fails(run_tool("process_ipl", os.path.join(self.tmp, "missing.dol"), self.out), "No such file")


if __name__ == "__main__":
    unittest.main()
