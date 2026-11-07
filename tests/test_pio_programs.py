"""
Runs the real PIO programs from a firmware build in the simulator (tests/pio_sim.py),
against a simulated GameCube reading the IPL. Needs the build's generated
picoboot-dx.pio.h and src/ipl.h, so it is skipped unless PICOBOOT_BUILD_DIR is set:

    PICOBOOT_BUILD_DIR=build-pico python3 -m unittest discover -s tests -p 'test_pio_programs.py' -v
"""

import os
import random
import unittest

import pio_sim
from helpers import REPO, header_array_words

BUILD_DIR = os.environ.get("PICOBOOT_BUILD_DIR")
IPL_H = os.path.join(REPO, "src", "ipl.h")

# Mirrors src/picoboot-dx.c and src/pio.c by hand; keep in sync with the C code.
DATA_PIN = 6                    # PIN_DATA
SKIPPED_TRANSFERS = 224         # pio_prepare_transfer(pio, transfer_start_sm, 224, pio_x)
BITS_PER_TRANSFER = 8191 + 1    # pio_prepare_transfer(pio, clocked_output_sm, 8191, pio_y)
WORDS_PER_TRANSFER = BITS_PER_TRANSFER // 32

# The instructions pio_prepare_transfer() executes with pio_sm_exec()
PULL_IFEMPTY_BLOCK = 0x80E0     # pio_encode_pull(true, true)
MOV_X_OSR, MOV_Y_OSR = 0xA027, 0xA047
OUT_NULL_32 = 0x6060

SET_PINDIRS_0 = 0xE080          # set pindirs, 0
MOV_Y_Y = 0xA042                # mov y, y (does nothing)


def load_programs():
    with open(os.path.join(BUILD_DIR, "picoboot-dx.pio.h")) as f:
        return pio_sim.parse_pio_header(f.read())


def prepare_transfer(sm, count, mov):
    """Same steps as pio_prepare_transfer() in src/pio.c."""
    sm.fifo.append(count)                           # pio_sm_put()
    for word in (PULL_IFEMPTY_BLOCK, mov, OUT_NULL_32):
        sm.exec_instruction(word)


def simulate(words, *, lazy_autopull=False, patch=None, extra_transfers=2):
    """
    Set up both state machines like on_transfer_program_init(), clocked_output_program_init()
    and main() do, then let a simulated console read the IPL: 224 short transfers, one 1K
    transfer per 256 payload words, and a few short transfers afterwards (fonts, RTC).
    """
    programs, defines = load_programs()
    transfers = len(words) // WORDS_PER_TRANSFER
    console = pio_sim.Console(defines["CS_PIN"], defines["CLK_PIN"],
                              [64] * SKIPPED_TRANSFERS + [BITS_PER_TRANSFER] * transfers + [64] * extra_transfers)
    pio = pio_sim.PIO(console.level, lazy_autopull=lazy_autopull)
    clocked_program = dict(programs["clocked_output"])
    if patch:
        clocked_program["instructions"] = patch(list(clocked_program["instructions"]))
    # on_transfer: SDK default config (shift right, no autopull); clocked_output: shift left,
    # autopull at 32 bits, joined 8-word TX FIFO, OUT and SET on the data pin
    on_transfer = pio.add_sm(programs["on_transfer"])
    clocked_output = pio.add_sm(clocked_program, autopull=True, threshold=32, shift_right=False,
                                out_base=DATA_PIN, out_count=1, set_base=DATA_PIN, set_count=1, fifo_depth=8)
    prepare_transfer(on_transfer, SKIPPED_TRANSFERS, MOV_X_OSR)
    prepare_transfer(clocked_output, BITS_PER_TRANSFER - 1, MOV_Y_OSR)
    on_transfer.enabled = clocked_output.enabled = True
    received, changes = pio_sim.run(pio, console, clocked_output, words, DATA_PIN)
    return {"received": received, "changes": changes, "console": console, "transfers": transfers,
            "pc": clocked_output.pc, "disable_chip": programs["clocked_output"]["labels"]["disable_chip"]}


def bits_of(words):
    return [(w >> (31 - i)) & 1 for w in words for i in range(32)]


def first_difference(got, expected):
    for i, (a, b) in enumerate(zip(got, expected)):
        if a != b:
            return f"bit {i}: got {a}, expected {b}"
    return f"length {len(got)}, expected {len(expected)}" if len(got) != len(expected) else None


def delivery_problems(words, result):
    """Everything wrong with how the payload reached the console (empty list if correct)."""
    problems = []
    received, console = result["received"], result["console"]
    first, last = SKIPPED_TRANSFERS, SKIPPED_TRANSFERS + result["transfers"] - 1
    for n in range(first):
        if any(bit is not None for bit in received[n]):
            problems.append(f"data line driven during skipped transfer {n}")
            break
    for k in range(result["transfers"]):
        expected = bits_of(words[k * WORDS_PER_TRANSFER:(k + 1) * WORDS_PER_TRANSFER])
        difference = first_difference(received[first + k], expected)
        if difference:
            problems.append(f"transfer {k}: {difference}")
    for n in range(last + 1, len(console.cs_falls)):
        if any(bit is not None for bit in received[n]):
            problems.append(f"data line driven during later transfer {n}")
    if len(result["changes"]) != 2:
        problems.append(f"data line direction changed {len(result['changes'])} times, expected on once and off once")
    else:
        (t_on, on), (t_off, off) = result["changes"]
        if not (on == 1 and console.cs_falls[first] < t_on < console.cs_rises[first]):
            problems.append("data line not driven from the first payload transfer")
        if not (off == 0 and console.cs_rises[last] < t_off < console.cs_falls[last + 1]):
            problems.append("data line not released right after CS goes high at the end of the payload")
    if result["pc"] != result["disable_chip"]:
        problems.append(f"clocked_output ended at {result['pc']}, not at disable_chip ({result['disable_chip']})")
    return problems


def random_words(transfers, seed):
    rng = random.Random(seed)
    return [rng.getrandbits(32) for _ in range(transfers * WORDS_PER_TRANSFER)]


@unittest.skipUnless(BUILD_DIR, "set PICOBOOT_BUILD_DIR to a firmware build directory")
class PioProgramsTest(unittest.TestCase):
    def test_single_transfer(self):
        words = random_words(1, seed=1)
        self.assertEqual(delivery_problems(words, simulate(words)), [])

    def test_three_transfers(self):
        words = random_words(3, seed=2)
        self.assertEqual(delivery_problems(words, simulate(words)), [])

    @unittest.skipUnless(os.path.exists(IPL_H), "src/ipl.h not generated (run tools/process_ipl.py)")
    def test_full_builtin_ipl(self):
        """The case that booted on a GameCube: the bundled IPL, 60 transfers."""
        with open(IPL_H) as f:
            words = header_array_words(f.read())
        self.assertEqual(len(words), 60 * WORDS_PER_TRANSFER)
        self.assertEqual(delivery_problems(words, simulate(words)), [])


@unittest.skipUnless(BUILD_DIR, "set PICOBOOT_BUILD_DIR to a firmware build directory")
class NegativeTest(unittest.TestCase):
    """These must fail, to show the tests above can catch the mistakes they are meant for."""

    def test_wrong_autopull_model_is_detected(self):
        """rp2040js-style autopull (refill only at the next OUT) stops after one transfer."""
        words = random_words(3, seed=3)
        problems = delivery_problems(words, simulate(words, lazy_autopull=True))
        self.assertTrue(any(p.startswith("transfer 1:") for p in problems), problems)

    def test_releasing_the_line_before_cs_goes_high_is_detected(self):
        """Without `wait 1 gpio CS_PIN` before `set pindirs 0`, the last bit is lost."""
        def without_hold(instructions):
            i = instructions.index(SET_PINDIRS_0)
            self.assertEqual(instructions[i - 1] & 0xFF80, 0x2080, "wait 1 gpio before set pindirs 0")
            instructions[i - 1] = MOV_Y_Y
            return instructions

        words = random_words(2, seed=4)
        problems = delivery_problems(words, simulate(words, patch=without_hold))
        self.assertIn(f"transfer 1: bit {BITS_PER_TRANSFER - 1}: got None, expected {bits_of(words)[-1]}", problems)


if __name__ == "__main__":
    unittest.main()
