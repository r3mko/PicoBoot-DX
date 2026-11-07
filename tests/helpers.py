"""
Shared helpers for the PicoBoot-DX tests (Python standard library only).

Run all tests from the repository root with:
    python3 -m unittest discover -s tests -v
"""

import importlib.util
import math
import os
import struct
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(REPO, "tools")

# Bundled IPL, relative to the repository root (same path CI passes to process_ipl.py)
IPL_DOL = os.path.join("assets", "ipl", "iplboot.dol")

PAYLOAD_BASE = 0x10080000           # Flash address of the payload region
UF2_FAMILY_RP2040 = 0xE48BFF56


def load_tool(name):
    """Import tools/<name>.py as a module (the tools are scripts, not a package)."""
    spec = importlib.util.spec_from_file_location(name, os.path.join(TOOLS, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_tool(name, *args):
    """Run tools/<name>.py from the repository root; returns the CompletedProcess."""
    return subprocess.run(
        [sys.executable, "-I", "-B", os.path.join(TOOLS, name + ".py"), *args],
        cwd=REPO, capture_output=True, text=True,
    )


def read_ipl_dol():
    with open(os.path.join(REPO, IPL_DOL), "rb") as f:
        return bytearray(f.read())


def make_dol(sections, entry=0x81300000, bss=(0, 0)):
    """
    Build a DOL file. `sections` is a list of (load_address, data) for up to 18
    sections; their data is stored after the 256-byte header in the given order.
    """
    header = [0] * 64
    body = bytearray()
    for num, (address, data) in enumerate(sections):
        header[num] = 0x100 + len(body)     # file offset
        header[18 + num] = address          # load address
        header[36 + num] = len(data)        # size
        body += data
    header[54], header[55] = bss
    header[56] = entry
    return struct.pack(">64I", *header) + bytes(body)


def make_payload(img, scramble):
    """
    Payload in the PicoBoot format, built the same way as upstream gekkoboot's
    buildtools/dol2ipl.py (https://github.com/redolution/gekkoboot):
    32-byte "IPLBOOT " header with the total size, scrambled image padded to
    4 bytes, "PICO" footer.
    """
    data = scramble(bytearray(0x720) + img)[0x720:]
    data = data.ljust(math.ceil(len(data) / 4) * 4, b"\0") + b"PICO"
    header = struct.pack(">8sI20x", b"IPLBOOT ", len(data) + 32)
    return bytearray(header + data)


def uf2_block(address, chunk, seq=0, total=1, family=UF2_FAMILY_RP2040, size=None):
    """One 512-byte UF2 block (flags: family ID present)."""
    return struct.pack(
        "<8I476sI",
        0x0A324655, 0x9E5D5157, 0x00002000, address,
        len(chunk) if size is None else size, seq, total, family,
        bytes(chunk), 0x0AB16F30,
    )


def uf2_blocks(data, base=PAYLOAD_BASE):
    """
    Split data into 256-byte UF2 blocks starting at `base`, like upstream's
    pack_uf2(): every block declares 256 bytes, the last one zero-padded.
    """
    chunks = [data[i:i + 256] for i in range(0, len(data), 256)]
    return [uf2_block(base + 256 * n, chunk, n, len(chunks), size=256) for n, chunk in enumerate(chunks)]


def header_array_words(text):
    """The uint32_t values of the `ipl[]` array in a generated ipl.h."""
    body = text.split("ipl[] = {", 1)[1].split("};", 1)[0]
    return [int(word, 16) for word in body.replace(",", " ").split()]
