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
JMP_PIN = 0x00C0                # jmp pin, <address in the low 5 bits>
WAIT_0_GPIO, WAIT_1_GPIO = 0x2000, 0x2080   # wait 0 / 1 gpio, <pin in the low 5 bits>

# Extra pulses on the console's lines, a few cycles after a CS rise (the next CS fall is 16 later)
GLITCH_OFFSET, STRAY_CLK_OFFSET, PULSE_WIDTH = 3, 8, 2
CS_LOW_UNTIL = 4                # With cs_low_until: CS reads low until then (the first CS fall is at 16)
CONSOLE_GAP = 16                # pio_sim.Console's gap: the last clock's period ends this long before CS rises
MID_TRANSFER = 4000 * 8         # cs_blip() in the middle of a 1K transfer: 4000 clocks of 8 cycles before CS rises
SLOW_HALF_PERIOD = 8            # half_period for a 64 ns EXI clock at 250 MHz (the default 4 is 32 ns)


def cs_glitch(after=None, offset=GLITCH_OFFSET):
    """CS low without clocks, after transfer `after` (None: before the first transfer)."""
    return ("CS_PIN", after, offset, 0)


def stray_clk(after=None):
    """A CLK pulse while CS is high, like another device on EXI0's shared clock."""
    return ("CLK_PIN", after, STRAY_CLK_OFFSET, 1)


def cs_blip(transfer, before_cs_rise):
    """CS high for a moment within transfer `transfer`, `before_cs_rise` cycles before its CS rise."""
    return ("CS_PIN", transfer, -before_cs_rise, 1)


def load_programs():
    with open(os.path.join(BUILD_DIR, "picoboot-dx.pio.h")) as f:
        return pio_sim.parse_pio_header(f.read())


def prepare_transfer(sm, count, mov):
    """Same steps as pio_prepare_transfer() in src/pio.c."""
    sm.fifo.append(count)                           # pio_sm_put()
    for word in (PULL_IFEMPTY_BLOCK, mov, OUT_NULL_32):
        sm.exec_instruction(word)


def simulate(words, *, lazy_autopull=False, patch=None, on_transfer_patch=None, pulses=(), extra_transfers=2,
             cs_low_until=None, half_period=4):
    """
    Set up both state machines like on_transfer_program_init(), clocked_output_program_init()
    and main() do, then let a simulated console read the IPL: 224 short transfers, one 1K
    transfer per 256 payload words, and a few short transfers afterwards (fonts, RTC).
    `pulses` adds cs_glitch() / stray_clk() / cs_blip() pulses to the console's lines.
    `cs_low_until` starts CS low, and `half_period` sets the clock (pio_sim.Console).
    """
    programs, defines = load_programs()
    transfers = len(words) // WORDS_PER_TRANSFER
    console = pio_sim.Console(defines["CS_PIN"], defines["CLK_PIN"],
                              [64] * SKIPPED_TRANSFERS + [BITS_PER_TRANSFER] * transfers + [64] * extra_transfers,
                              half_period=half_period, cs_low_until=cs_low_until)
    for pin, after, offset, level in pulses:
        start = offset if after is None else console.cs_rises[after] + offset
        console.add_pulse(defines[pin], start, PULSE_WIDTH, level)
    pio = pio_sim.PIO(console.level, lazy_autopull=lazy_autopull)
    on_transfer_program = dict(programs["on_transfer"])
    if on_transfer_patch:
        on_transfer_program["instructions"] = on_transfer_patch(list(on_transfer_program["instructions"]))
    clocked_program = dict(programs["clocked_output"])
    if patch:
        clocked_program["instructions"] = patch(list(clocked_program["instructions"]))
    # on_transfer: SDK default config (shift right, no autopull), JMP PIN on CS; clocked_output:
    # shift left, autopull at 32 bits, joined 8-word TX FIFO, OUT and SET on the data pin
    on_transfer = pio.add_sm(on_transfer_program, jmp_pin=defines["CS_PIN"])
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
class GlitchTest(unittest.TestCase):
    """A CS glitch without clocks (seen as the console powers up) must not count as a skipped transfer."""

    def assert_delivered(self, pulses, words=None, cs_low_until=None):
        words = words or random_words(2, seed=5)
        self.assertEqual(delivery_problems(words, simulate(words, pulses=pulses, cs_low_until=cs_low_until)), [])

    def test_cs_low_at_start(self):
        """Without a pull-up, CS reads low (the pad's reset pull-down) until the console first drives it high."""
        self.assert_delivered([], cs_low_until=CS_LOW_UNTIL)

    def test_cs_low_at_start_then_a_cs_glitch(self):
        """The power-on glitch as it comes with the pull-down: CS low, driven high, then a pulse without clocks."""
        self.assert_delivered([cs_glitch(offset=CS_LOW_UNTIL + 4)], cs_low_until=CS_LOW_UNTIL)

    def test_cs_glitch_during_the_skipped_transfers(self):
        for after in (None, 0, 100, SKIPPED_TRANSFERS - 2):
            with self.subTest(after=after):
                self.assert_delivered([cs_glitch(after)])

    def test_clk_pulse_while_cs_is_high(self):
        for after in (None, 50):
            with self.subTest(after=after):
                self.assert_delivered([stray_clk(after)])

    def test_cs_glitch_followed_by_a_clk_pulse_while_cs_is_high(self):
        for after in (None, 100, SKIPPED_TRANSFERS - 2):
            with self.subTest(after=after):
                self.assert_delivered([cs_glitch(after), stray_clk(after)])

    @unittest.skipUnless(os.path.exists(IPL_H), "src/ipl.h not generated (run tools/process_ipl.py)")
    def test_full_builtin_ipl_with_a_cs_glitch_and_a_clk_pulse(self):
        with open(IPL_H) as f:
            words = header_array_words(f.read())
        self.assert_delivered([cs_glitch(100), stray_clk(100)], words)


@unittest.skipUnless(BUILD_DIR, "set PICOBOOT_BUILD_DIR to a firmware build directory")
class PayloadNoiseTest(unittest.TestCase):
    """CS noise around the payload transfers must not shift the transfers after it."""

    def assert_delivered(self, pulses, transfers=2, half_period=4):
        words = random_words(transfers, seed=8)
        self.assertEqual(delivery_problems(words, simulate(words, pulses=pulses, half_period=half_period)), [])

    def test_cs_blip_within_a_payload_transfer(self):
        self.assert_delivered([cs_blip(SKIPPED_TRANSFERS, MID_TRANSFER)])

    def test_cs_blip_at_a_payload_transfers_last_clocks(self):
        """A blip between the second-to-last and the last clock, which the CS wait alone lets through."""
        second_to_last_clock = CONSOLE_GAP + 4 * SLOW_HALF_PERIOD     # rises this long before CS does
        for after_clock in (4, 7, 10):
            with self.subTest(after_clock=after_clock):
                self.assert_delivered([cs_blip(SKIPPED_TRANSFERS, second_to_last_clock - after_clock)],
                                      half_period=SLOW_HALF_PERIOD)

    def test_cs_glitch_between_payload_transfers(self):
        """A glitch without clocks right before the first payload transfer, and between the first two of three."""
        for after in (SKIPPED_TRANSFERS - 1, SKIPPED_TRANSFERS):
            with self.subTest(after=after):
                self.assert_delivered([cs_glitch(after)], transfers=3)

    def test_cs_glitch_then_a_clk_pulse_while_cs_is_high(self):
        """A glitch without clocks as above, then a clock while CS is high one transfer later."""
        for after in (SKIPPED_TRANSFERS - 1, SKIPPED_TRANSFERS):
            with self.subTest(after=after):
                self.assert_delivered([cs_glitch(after), stray_clk(after + 1)], transfers=3)

    def test_cs_blip_then_a_clk_pulse_while_cs_is_high(self):
        """A blip within the first payload transfer, then a clock while CS is high after it or a transfer later."""
        for after in (SKIPPED_TRANSFERS, SKIPPED_TRANSFERS + 1):
            with self.subTest(after=after):
                self.assert_delivered([cs_blip(SKIPPED_TRANSFERS, MID_TRANSFER), stray_clk(after)], transfers=3)


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

    def find_jmp_pin(self, instructions):
        i = next(i for i, word in enumerate(instructions) if word & 0xFFE0 == JMP_PIN)
        self.assertEqual(instructions[i - 1] & 0xFF80, 0x2080, "wait 1 gpio (CLK) before jmp pin")
        return i

    def test_counting_a_cs_glitch_is_detected(self):
        """Without the CLK check (v0.10's on_transfer), a CS glitch counts as a skipped transfer."""
        def without_clk_check(instructions):
            i = self.find_jmp_pin(instructions)
            instructions[i - 1] = instructions[i] = MOV_Y_Y
            return instructions

        words = random_words(2, seed=6)
        problems = delivery_problems(words, simulate(words, on_transfer_patch=without_clk_check,
                                                     pulses=[cs_glitch()]))
        self.assertIn(f"data line driven during skipped transfer {SKIPPED_TRANSFERS - 1}", problems)

    def test_counting_a_cs_glitch_with_a_stray_clock_is_detected(self):
        """With the CLK wait but without `jmp pin`, a CS glitch followed by a clock while CS is high counts."""
        def without_cs_check(instructions):
            instructions[self.find_jmp_pin(instructions)] = MOV_Y_Y
            return instructions

        words = random_words(2, seed=7)
        problems = delivery_problems(words, simulate(words, on_transfer_patch=without_cs_check,
                                                     pulses=[cs_glitch(), stray_clk()]))
        self.assertIn(f"data line driven during skipped transfer {SKIPPED_TRANSFERS - 1}", problems)

    def check_transfer_end_waits(self, instructions):
        """clocked_output starts with `set x, 31`, then waits for CLK low, CLK high, CS high and CS low."""
        self.assertEqual([word & 0xFF80 for word in instructions[1:5]],
                         [WAIT_0_GPIO, WAIT_1_GPIO, WAIT_1_GPIO, WAIT_0_GPIO])

    def test_taking_the_next_irq_before_a_transfer_ends_is_detected(self):
        """Without the waits for a transfer's last clock and the CS edges (v0.13), a CS blip shifts the next transfer."""
        def without_transfer_end_waits(instructions):
            self.check_transfer_end_waits(instructions)
            instructions[1:5] = [MOV_Y_Y] * 4
            return instructions

        # At the slow clock: at the default one, the four `mov y, y` take long enough to miss the last clock
        words = random_words(2, seed=9)
        problems = delivery_problems(words, simulate(words, patch=without_transfer_end_waits,
                                                     pulses=[cs_blip(SKIPPED_TRANSFERS, 2 * MID_TRANSFER)],
                                                     half_period=SLOW_HALF_PERIOD))
        self.assertTrue(any(p.startswith("transfer 1:") for p in problems), problems)

    def test_cs_wait_without_the_last_clock_wait_is_detected(self):
        """With the CS wait but not the wait for the last clock, a blip right before that clock passes it."""
        def without_last_clock_wait(instructions):
            self.check_transfer_end_waits(instructions)
            instructions[1:3] = [MOV_Y_Y] * 2
            return instructions

        words = random_words(2, seed=10)
        second_to_last_clock = CONSOLE_GAP + 4 * SLOW_HALF_PERIOD
        problems = delivery_problems(words, simulate(words, patch=without_last_clock_wait,
                                                     pulses=[cs_blip(SKIPPED_TRANSFERS, second_to_last_clock - 7)],
                                                     half_period=SLOW_HALF_PERIOD))
        self.assertTrue(any(p.startswith("transfer 1:") for p in problems), problems)

    def test_a_clk_pulse_while_cs_is_high_without_the_cs_low_wait_is_detected(self):
        """Without the wait for the next transfer's CS fall, CS noise leaves IRQ 0 set early, and a later clock while
        CS is high counts as the next transfer's first address clock."""
        def without_cs_low_wait(instructions):
            self.check_transfer_end_waits(instructions)
            instructions[4] = MOV_Y_Y
            return instructions

        words = random_words(3, seed=11)
        for noise in (cs_blip(SKIPPED_TRANSFERS, MID_TRANSFER), cs_glitch(SKIPPED_TRANSFERS)):
            with self.subTest(noise=noise):
                problems = delivery_problems(words, simulate(words, patch=without_cs_low_wait,
                                                             pulses=[noise, stray_clk(SKIPPED_TRANSFERS + 1)]))
                self.assertTrue(any(p.startswith("transfer 2:") for p in problems), problems)


if __name__ == "__main__":
    unittest.main()
