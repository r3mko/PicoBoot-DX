#!/usr/bin/env python3

# Based on dol2ipl.py from https://github.com/redolution/gekkoboot
# Original source by 9ary, bootrom descrambler reversed by segher

import argparse, math, struct, sys
from typing import List

def scramble(data):
    """
    Apply GameCube bootrom scrambling algorithm to the payload data.
    Uses three 16-bit LFSR registers (t, u, v) and generates a keystream byte-by-byte.
    """
    acc = 0           # accumulator for building each keystream byte
    nacc = 0          # counter bits accumulated so far

    # Initial LFSR register values as defined by original bootrom routine
    t = 0x2953
    u = 0xD9C2
    v = 0x3FF1

    x = 1             # working bit to be xored into accumulator
    it = 0            # current data index

    # Iterate until every byte of data has been processed
    while it < len(data):
        # Extract LSBs and next bits for feedback calculation
        t0 = t & 1
        t1 = (t >> 1) & 1
        u0 = u & 1
        u1 = (u >> 1) & 1
        v0 = v & 1

        # Calculate new bit x based on taps and previous state
        x ^= t1 ^ v0
        x ^= u0 | u1
        x ^= (t0 ^ u1 ^ v0) & (t0 ^ u0)

        # Shift and conditionally apply feedback polynomials
        if t0 == u0:
            v >>= 1
            if v0:
                v ^= 0xB3D0    # feedback mask for v

        if t0 == 0:
            u >>= 1
            if u0:
                u ^= 0xFB10    # feedback mask for u

        t >>= 1
        if t0:
            t ^= 0xA740        # feedback mask for t

        # Accumulate bits into acc until we have a full byte
        nacc = (nacc + 1) % 256
        acc = (acc * 2 + x) % 256
        if nacc == 8:
            data[it] ^= acc    # XOR the keystream byte into data
            nacc = 0
            it += 1

    return data

def flatten_dol(data):
    """
    Parse a .dol executable image and flatten it into a single contiguous memory image.
    Returns (entry_point, base_load_address, flattened_image_bytes).
    """
    # DOL header consists of 64 big-endian 32-bit words
    header = struct.unpack(">64I", data[:256])

    offsets = header[:18]        # file offsets for each section
    addresses = header[18:36]    # load addresses for each section
    sizes = header[36:54]        # sizes for each section
    bss_address = header[54]     # start of BSS segment (uninitialized)
    bss_size = header[55]        # size of BSS segment
    entry = header[56]           # program entry point

    # Determine the address range that contains actual data
    dol_min = min(addr for addr in addresses if addr)
    dol_max = max(addr + size for addr, size in zip(addresses, sizes))

    # Allocate a bytearray for the in-memory image
    img = bytearray(dol_max - dol_min)

    # Copy each section from file image into its load address in img
    for offset, address, size in zip(offsets, addresses, sizes):
        if size > 0:
            start = address - dol_min
            img[start:start + size] = data[offset:offset + size]

    # Return entry, base address, and flattened image
    return entry, dol_min, img

def bytes_to_c_array(data):
    """
    Convert bytes into a list of formatted 32-bit big-endian hex literals
    for inclusion in a C source array.
    """
    hex_values: List[str] = []

    for offset in range(0, len(data), 4):
        # Grab up to 4 bytes from the data
        word_bytes = data[offset:offset + 4]
        # Convert to unsigned int, big-endian
        word_int = int.from_bytes(
            word_bytes,
            byteorder="big",
            signed=False
        )
        # Format as hex digits
        hex_literal = f"0x{word_int:08x}"
        hex_values.append(hex_literal)

    return hex_values

def generate_header_file(byte_groups, executable, size):
    """
    Build a C header file string containing the scrambled payload as a uint32_t array.
    Includes metadata comments (file, size).
    """
    output = "#include <stdio.h>\n\n"
    
    output += "//\n"
    output += f"// File: {executable}, size: {size} bytes\n"
    output += "//\n\n"

    output += "uint32_t __in_flash(\"ipl_data\") ipl[] = {\n\t"
    # Write array elements, 4 per line
    for num, elem in enumerate(byte_groups):
        if num > 0 and num % 4 == 0:
            output += "\n\t"
        output += elem
        if num != len(byte_groups) - 1:
            output += ", "
    output += "\n};\n"

    return output

def main():
    """
    Main entry point: process .dol file, scramble payload, and output C header.
    """
    args = parse_args()

    executable = args.input
    output = args.output

    if executable.endswith(".dol"):
        # Read the input executable into memory
        with open(executable, "rb") as f:
            dol = bytearray(f.read())

        entry, load, img = flatten_dol(dol)
        # Mask and set proper bits for entry and load addresses
        entry &= 0x017FFFFF
        entry |= 0x80000000
        load &= 0x017FFFFF
        size = len(img)

        print(f"Entry point:   0x{entry:08X}")
        print(f"Load address:  0x{load:08X}")
        print(f"Image size:    {size} bytes ({size // 1024}K)\n")
    else:
        print("Unknown input format")
        return -1

    # Validate against expected entry and base addresses
    if entry != 0x81300000 or load != 0x01300000:
        print(f"Invalid entry point and base address ({hex(entry)}:{hex(load)})")
        return -1

    # Create: 0x720-byte header + image
    # 224 CS pulses * 8 = 1792 = 0x700
    # 32 pipeline flush bytes = 0x20
    hdr_img = bytearray(0x720) + img

    # Align: image size to the next 1K boundary if needed
    size += 0x20
    align_size = 1024 # bytes
    if size % align_size != 0:
        chunks = math.ceil(size / align_size)
        new_size = chunks * align_size
        print(f"Image needs to be aligned to {new_size} bytes ({chunks}x{align_size}B)")
        hdr_img += bytearray(new_size - size)

    # Scramble: remove the first 0x700 bytes (224 CS) after, but keep 0x20 bytes (pipeline flush)
    scrambled_img = scramble(hdr_img)[0x700:]

    print(f"Output (scrambled) binary size: {len(scrambled_img)} bytes ({len(scrambled_img) // 1024}K)")

    # Convert scrambled bytes into C array literals
    byte_groups = bytes_to_c_array(scrambled_img)

    # Generate full header file content
    h_file = generate_header_file(byte_groups, executable, size)

    # Write generated header to the output path
    with open(output, "w") as f:
        f.write(h_file)

def parse_args():
    p = argparse.ArgumentParser(
        description = "Convert a .dol executable into a scrambled C header file."
    )

    p.add_argument("input", help = "Path to the .dol executable")
    p.add_argument("output", help = "Path to write the header (.h) file")

    return p.parse_args()

if __name__ == "__main__":
    sys.exit(main())
