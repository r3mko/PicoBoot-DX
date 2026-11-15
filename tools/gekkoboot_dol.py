#!/usr/bin/env python3

"""
Rebuilds gekkoboot's IPL .dol from a gekkoboot release, whose zip has no .dol, for the built-in IPL
(assets/ipl/; from PicoBoot-WiFi, see its docs/research/gekkoboot-dol.md:
https://github.com/r3mko/PicoBoot-WiFi/blob/main/docs/research/gekkoboot-dol.md):

    python3 tools/gekkoboot_dol.py gekkoboot-r9.4/swiss_igr/swiss/patches/apploader.img \\
        assets/ipl/gekkoboot_r9_4.dol

The release's Swiss IGR apploader.img is gekkoboot's buildtools/dol2ipl.py output: a 32-byte header
(a date string, its size and a CRC-32) and the unscrambled image, as loaded at 0x81300000. The .dol's
layout comes from the image itself (gekkoboot's packer/link.ld and crt0.S): one text section, the
packer's code, up to its xz stream, which starts the data section; the entry at 0x81300000; and the
.sbss that crt0 clears, whose bounds crt0 loads relative to r13. Anything else is refused.
"""

import argparse
import struct
import sys
import zlib

BASE = 0x81300000                       # Where the boot ROM puts the IPL, and starts it
XZ_MAGIC = b"\xfd7zXZ\x00"              # The packer's compressed program starts the data section
APPLOADER = struct.Struct(">16s8xII")   # Date string, padding, image size, CRC-32 of the image
APPLOADER_DATE = b"*gekkoboot"

# The packer's __eabi (crt0.S): lis r13, _SDA_BASE_@ha ... addi r13, r13, _SDA_BASE_@l, then
# addi r3, r13, __sbss_start@sdarel; addi r4, r13, __sbss_end@sdarel; subf r4, r3, r4
LIS_R13, ADDI_R13 = 0x3DA0, 0x39AD
ADDI_R3_R13, ADDI_R4_R13, SUBF_R4_R3_R4 = 0x386D, 0x388D, 0x7C832050


def image_from_apploader(data):
    """The image in an apploader.img, after checking its header."""
    if len(data) < APPLOADER.size:
        raise ValueError(f"File is {len(data)} bytes, smaller than an apploader header (32 bytes)")
    date, size, crc = APPLOADER.unpack_from(data)
    image = data[APPLOADER.size:]
    if date.rstrip(b"\0") != APPLOADER_DATE:
        raise ValueError(f"Not gekkoboot's apploader.img (date string {date.rstrip(bytes(1))!r})")
    if size != len(image) or zlib.crc32(image) != crc:
        raise ValueError("The apploader header's size or CRC-32 doesn't match its image")
    return image


def _sext16(value):
    return value - ((value & 0x8000) << 1)


def sbss(image, text_size):
    """The .sbss that the packer's crt0 clears, as (load address, size)."""
    words = struct.unpack(f">{text_size // 4}I", image[:text_size])
    for i in range(len(words) - 2):
        if (words[i] >> 16, words[i + 1] >> 16, words[i + 2]) == (ADDI_R3_R13, ADDI_R4_R13, SUBF_R4_R3_R4):
            before = words[max(0, i - 6):i]
            ha = [w & 0xFFFF for w in before if w >> 16 == LIS_R13]
            lo = [w & 0xFFFF for w in before if w >> 16 == ADDI_R13]
            if ha and lo:
                r13 = (ha[-1] << 16) + _sext16(lo[-1])  # The packer's own address, without 0x80000000
                start = r13 + _sext16(words[i] & 0xFFFF)
                end = r13 + _sext16(words[i + 1] & 0xFFFF)
                return (start + 0x80000000) & 0xFFFFFFFF, end - start
    raise ValueError("The packer's crt0 (its .sbss clear) wasn't found before the xz stream")


def dol_from_image(image):
    """A .dol of the image: the packer's code as text 0, the rest as data 0, and the packer's .sbss."""
    text_size = image.find(XZ_MAGIC)
    if text_size <= 0 or text_size % 32:
        raise ValueError("No xz stream at a 32-byte boundary after the packer's code")
    if len(image) % 32:
        raise ValueError(f"The image is {len(image)} bytes, not a whole number of 32-byte blocks")
    bss_address, bss_size = sbss(image, text_size)
    if bss_address != BASE + len(image) or bss_size <= 0:
        raise ValueError(f"The .sbss (0x{bss_address:08X}, {bss_size} bytes) doesn't follow the image "
                         f"(it ends at 0x{BASE + len(image):08X})")
    offsets, addresses, sizes = [0] * 18, [0] * 18, [0] * 18
    offsets[0], addresses[0], sizes[0] = 0x100, BASE, text_size                     # Text 0
    offsets[7], addresses[7], sizes[7] = 0x100 + text_size, BASE + text_size, len(image) - text_size  # Data 0
    header = struct.pack(">64I", *offsets, *addresses, *sizes, bss_address, bss_size, BASE, *([0] * 7))
    return header + image


def main():
    p = argparse.ArgumentParser(description="Rebuild gekkoboot's IPL .dol from a release's apploader.img")
    p.add_argument("apploader", help="The release's swiss_igr/swiss/patches/apploader.img")
    p.add_argument("output", help="The .dol to write")
    args = p.parse_args()
    try:
        with open(args.apploader, "rb") as f:
            data = f.read()
        dol = dol_from_image(image_from_apploader(data))
    except (OSError, ValueError) as e:
        print(f"{args.apploader}: {e}", file=sys.stderr)
        return 1
    with open(args.output, "wb") as f:
        f.write(dol)
    text_size, data_size = struct.unpack_from(">I", dol, 36 * 4)[0], struct.unpack_from(">I", dol, 43 * 4)[0]
    bss_address, bss_size = struct.unpack_from(">II", dol, 54 * 4)
    print(f"{args.output}: {len(dol)} bytes; text 0x{text_size:X}, data 0x{data_size:X} at 0x{BASE:08X}, "
          f".sbss 0x{bss_size:X} at 0x{bss_address:08X}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
