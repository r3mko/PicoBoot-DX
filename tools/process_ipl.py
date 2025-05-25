#!/usr/bin/env python3

# Based on dol2ipl.py from https://github.com/redolution/gekkoboot
# Original source by 9ary, bootrom descrambler reversed by segher

from datetime import datetime
import math
import struct
import sys

# Padding bytes added after the 0x700-byte header to align the payload
payload_padding = [
    0x81, 0x4a, 0xe6, 0xc8, 0x00, 0x04, 0xc5, 0x77, 
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
]

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
    dol_min = min(a for a in addresses if a)
    dol_max = max(a + s for a, s in zip(addresses, sizes))

    # Allocate a bytearray for the in-memory image
    img = bytearray(dol_max - dol_min)

    # Copy each section from file image into its load address in img
    for offset, address, size in zip(offsets, addresses, sizes):
        if size > 0:
            start = address - dol_min
            img[start:start + size] = data[offset:offset + size]

    # Return entry, base address, and flattened image
    return header[56], dol_min, img


def bytes_to_c_array(data):
    """
    Convert bytes into a list of formatted 32-bit big-endian hex literals
    for inclusion in a C source array.
    """
    p_list = [data[i:i + 4] for i in range(0, len(data), 4)]
    return ["0x%08x" % int.from_bytes(b, byteorder='big', signed=False) for b in p_list]


def generate_header_file(elements, executable, input_file, output_file, size):
    """
    Build a C header file string containing the scrambled payload as a uint32_t array.
    Includes metadata comments (command, file, size, timestamp).
    """
    output = '#include <stdio.h>\n\n'
    output += '//\n'
    output += f'// Command: {executable} {input_file} {output_file}\n'
    output += '//\n'
    output += f'// File: {input_file}, size: {size} bytes\n'
    output += '//\n'
    output += f'// File generated on {datetime.now().strftime("%d.%m.%Y %H:%M:%S")}\n'
    output += '//\n\n'
    output += 'uint32_t __in_flash("ipl_data") ipl[]  = {\n\t'

    # Write array elements, 4 per line
    for num, elem in enumerate(elements):
        if num > 0 and num % 4 == 0:
            output += '\n\t'
        output += elem
        if num != len(elements) - 1:
            output += ', '

    output += '\n};\n'
    return output


def main():
    """
    Main entry point: process .dol file, scramble payload, and output C header.
    """
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <executable> <output>")
        return -1

    executable = sys.argv[1]
    output = sys.argv[2]

    # Read the input executable into memory
    with open(executable, "rb") as f:
        exe = bytearray(f.read())

    if executable.endswith(".dol"):
        entry, load, img = flatten_dol(exe)
        # Mask and set proper bits for entry and load addresses
        entry &= 0x017FFFFF
        entry |= 0x80000000
        load &= 0x017FFFFF
        size = len(img)

        print(f"Entry point:   0x{entry:08X}")
        print(f"Load address:  0x{load:08X}")
        print(f"Image size:    {size} bytes ({size // 1024}K)")
    else:
        print("Unknown input format")
        return -1

    # Validate against expected entry and base addresses
    if entry != 0x81300000 or load != 0x01300000:
        print(f"Invalid entry point and base address ({hex(entry)}:{hex(load)})")
        return -1

    # Build payload: 0x700-byte header + fixed padding + image
    payload = bytearray(0x700) + bytearray(payload_padding) + img
    payload_size = size + 0x20  # include DOL header (32 bytes)

    # Align payload size to the next 1K boundary if needed
    if payload_size % 1024 != 0:
        new_size_k = math.ceil(payload_size / 1024)
        new_size = new_size_k * 1024
        print(f"Payload needs to be aligned to {new_size_k}K")
        payload += bytearray(new_size - payload_size)
        payload_size = new_size

    print(f"Output binary size: {payload_size} bytes ({payload_size // 1024}K)")

    # Scramble payload, skipping the first 0x700 bytes (header/padding)
    scrambled_payload = scramble(payload)[0x700:]
    payload_size = len(scrambled_payload)

    # Convert scrambled bytes into C array literals
    byte_groups = bytes_to_c_array(scrambled_payload)

    # Generate full header file content
    out = generate_header_file(byte_groups, sys.argv[0], executable, output, size)

    # Write generated header to the output path
    with open(output, "w") as f:
        f.write(out)

if __name__ == "__main__":
    sys.exit(main())
