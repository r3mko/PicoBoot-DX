#!/usr/bin/env python3

"""
Check the payload memory layout of a built picoboot-dx.elf (run by CI after each board build):

    python3 tests/check_layout.py build-pico/picoboot-dx.elf

Payload .uf2 files built by upstream (gekkoboot, Swiss) are written to 0x10080000, so the
payload region must start exactly there, and the firmware must end below it. Uses
arm-none-eabi-nm, or the nm given in the NM environment variable.
"""

import os
import subprocess
import sys

PAYLOAD_START = 0x10080000
PAYLOAD_END = 0x10200000
SYMBOLS = ("flash_payload", "flash_payload_end", "__flash_binary_end")


def parse_nm(text):
    """Values of the layout symbols in `nm` output ("<hex value> <type> <name>" per line)."""
    values = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[2] in SYMBOLS:
            values[parts[2]] = int(parts[0], 16)
    return values


def check(values):
    """List of problems with the layout; empty if it is correct."""
    missing = [name for name in SYMBOLS if name not in values]
    if missing:
        return [f"symbol not found: {name}" for name in missing]
    problems = []
    if values["flash_payload"] != PAYLOAD_START:
        problems.append(f"flash_payload is 0x{values['flash_payload']:08X}, expected 0x{PAYLOAD_START:08X}")
    if values["flash_payload_end"] != PAYLOAD_END:
        problems.append(f"flash_payload_end is 0x{values['flash_payload_end']:08X}, expected 0x{PAYLOAD_END:08X}")
    if values["__flash_binary_end"] > PAYLOAD_START:
        problems.append(f"firmware ends at 0x{values['__flash_binary_end']:08X}, past the payload region at 0x{PAYLOAD_START:08X}")
    return problems


def main(argv):
    if len(argv) != 2:
        print(f"Usage: {argv[0]} <picoboot-dx.elf>", file=sys.stderr)
        return 2
    nm = os.environ.get("NM", "arm-none-eabi-nm")
    result = subprocess.run([nm, argv[1]], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error: {nm} failed: {result.stderr.strip()}", file=sys.stderr)
        return 1
    values = parse_nm(result.stdout)
    problems = check(values)
    for problem in problems:
        print(f"Error: {argv[1]}: {problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"{argv[1]}: payload 0x{PAYLOAD_START:08X}-0x{PAYLOAD_END:08X}, "
          f"firmware ends at 0x{values['__flash_binary_end']:08X}: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
