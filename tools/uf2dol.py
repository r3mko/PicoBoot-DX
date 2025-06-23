#!/usr/bin/env python3

# Based on dol2ipl.py from https://github.com/redolution/gekkoboot
# Original source by 9ary, bootrom descrambler reversed by segher

import argparse, struct, sys

# Magic numbers used in UF2 files
UF2_MAGIC_START0 = 0x0A324655
UF2_MAGIC_START1 = 0x9E5D5157
UF2_MAGIC_END = 0x0AB16F30

# Default memory addresses and offsets for DOL files
DOL_FILE_OFFSET = 0x100
DOL_LOAD_ADDRESS = 0x01300000
DOL_ENTRY_ADDRESS = 0x81300000

# Header marker for validation
IPLBOOT_HEADER = b'IPLBOOT '

def descramble(data):
    """Descrambles data using the GameCube bootrom scrambling algorithm."""
    acc, nacc = 0, 0
    t, u, v, x = 0x2953, 0xD9C2, 0x3FF1, 1

    for index in range(len(data)):
        for _ in range(8):
            t0, t1 = t & 1, (t >> 1) & 1
            u0, u1 = u & 1, (u >> 1) & 1
            v0 = v & 1

            x ^= t1 ^ v0
            x ^= u0 | u1
            x ^= (t0 ^ u1 ^ v0) & (t0 ^ u0)

            if t0 == u0:
                v >>= 1
                if v0:
                    v ^= 0xB3D0

            if t0 == 0:
                u >>= 1
                if u0:
                    u ^= 0xFB10

            t >>= 1
            if t0:
                t ^= 0xA740

            nacc = (nacc + 1) % 256
            acc = (acc * 2 + x) % 256

        data[index] ^= acc

    return data

def parse_uf2(file_path):
    """Extracts and assembles binary data from a UF2 formatted file."""
    blocks = {}
    addresses = []
    sizes = []

    with open(file_path, "rb") as uf2_file:
        while True:
            block = uf2_file.read(512)
            if len(block) < 512:
                break

            (magic_start0, magic_start1, _, addr, size, _, _, _, data, magic_end) = struct.unpack("<8I476sI", block)

            if (magic_start0 == UF2_MAGIC_START0 and
                magic_start1 == UF2_MAGIC_START1 and
                magic_end == UF2_MAGIC_END):
                blocks[addr] = data[:size]
                addresses.append(addr)
                sizes.append(size)

    binary_image = bytearray()
    for address in sorted(blocks):
        binary_image += blocks[address]

    return binary_image, addresses, sizes

def build_dol_header(file_offset, load_address, data_size, entry_address):
    """Creates a DOL header."""
    offsets = [0] * 18
    addresses = [0] * 18
    sizes = [0] * 18

    offsets[0] = file_offset
    addresses[0] = load_address
    sizes[0] = data_size

    bss_address = 0x00000000
    bss_size = 0x00000000

    header = offsets + addresses + sizes + [bss_address, bss_size, entry_address] + [0] * 7

    return struct.pack(">64I", *header)

def extract_dol_from_uf2(input_uf2, output_dol):
    """Converts a UF2 file into a DOL file by extracting and reconstructing its content."""
    binary_data, block_addresses, block_sizes = parse_uf2(input_uf2)

    if not binary_data.startswith(IPLBOOT_HEADER):
        raise ValueError("The file does not contain a valid IPLBOOT header.")

    total_size = struct.unpack(">I", binary_data[8:12])[0]
    scrambled_data = binary_data[32:total_size - 4]

    descrambled_data = descramble(bytearray(0x720) + scrambled_data)[0x720:]

    dol_header = build_dol_header(DOL_FILE_OFFSET, DOL_LOAD_ADDRESS, len(descrambled_data), DOL_ENTRY_ADDRESS)

    with open(output_dol, "wb") as dol_file:
        dol_file.write(dol_header)
        dol_file.write(descrambled_data)

    print("UF2 File Information:")
    print(f"  Block count:          {len(block_addresses)}")
    print(f"  Address range:        0x{min(block_addresses):08X} - 0x{max(block_addresses) + block_sizes[-1]:08X}")
    print(f"  Extracted firmware:   {len(binary_data)} bytes ({len(binary_data) // 1024}K)")
    print(f"  Image size:           {len(scrambled_data)} bytes ({len(scrambled_data) // 1024}K)\n")

    print("DOL Output Information:")
    print(f"  Entry point:          0x{DOL_ENTRY_ADDRESS:08X}")
    print(f"  Load address:         0x{DOL_LOAD_ADDRESS:08X}")
    print(f"  Image size:           {len(descrambled_data)} bytes ({len(descrambled_data) // 1024}K)\n")

    print(f"Successfully converted UF2 file to DOL format at '{output_dol}'")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Convert UF2 files to DOL format easily."
    )

    parser.add_argument("input", help="Path to the input UF2 file")
    parser.add_argument("output", help="Path to the output DOL file")

    args = parser.parse_args()    
    extract_dol_from_uf2(args.input, args.output)
