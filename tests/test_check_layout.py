"""Tests for tests/check_layout.py, using sample nm output (no firmware build needed)."""

import unittest

import check_layout

# nm output of a correct pico build with SDK 2.3.1 (2026-11-07)
GOOD = """\
10011864 N __flash_binary_end
10080000 T flash_payload
10200000 T flash_payload_end
10000100 T __logical_binary_start
"""

# nm output with SDK 2.3.1 and the old flash.ld: ORIGIN(FLASH) evaluated to 0
SDK_2_3_ORIGIN_BUG = """\
10011864 N __flash_binary_end
00080000 T flash_payload
00200000 T flash_payload_end
"""


class CheckLayoutTest(unittest.TestCase):
    def test_correct_layout_passes(self):
        self.assertEqual(check_layout.check(check_layout.parse_nm(GOOD)), [])

    def test_payload_region_at_the_wrong_address_fails(self):
        problems = check_layout.check(check_layout.parse_nm(SDK_2_3_ORIGIN_BUG))
        self.assertEqual(len(problems), 2)
        self.assertIn("flash_payload is 0x00080000, expected 0x10080000", problems[0])

    def test_firmware_overlapping_the_payload_fails(self):
        values = check_layout.parse_nm(GOOD)
        values["__flash_binary_end"] = 0x10090000
        self.assertIn("past the payload region", check_layout.check(values)[0])

    def test_missing_symbol_fails(self):
        values = check_layout.parse_nm(GOOD)
        del values["flash_payload"]
        self.assertEqual(check_layout.check(values), ["symbol not found: flash_payload"])


if __name__ == "__main__":
    unittest.main()
