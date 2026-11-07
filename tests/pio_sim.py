"""
Minimal RP2040 PIO simulator for the PicoBoot-DX PIO programs (Python standard library only).

It runs the real machine code that pioasm generates (build-<board>/picoboot-dx.pio.h) at
logic level: one instruction per enabled state machine per PIO cycle. Only the instructions
and options PicoBoot-DX uses are implemented, each following the RP2040 datasheet
(https://datasheets.raspberrypi.com/rp2040/rp2040-datasheet.pdf, page numbers below).
Anything else raises UnsupportedInstruction instead of being guessed.

Not modelled: real timing (EXI clock speed, setup/hold times, CS-to-clock delays) and
anything electrical. Those can only be checked on hardware.
"""

import re
from collections import deque

# Decoded instruction kinds
JMP, WAIT_GPIO, WAIT_IRQ, OUT, PULL, MOV, IRQ_SET, SET = range(8)

JMP_ALWAYS, JMP_X_DEC, JMP_NOT_OSRE = 0b000, 0b010, 0b111
OUT_PINS, OUT_NULL = 0b000, 0b011
REG_X, REG_Y, REG_OSR = 0b001, 0b010, 0b111          # MOV destination/source codes
SET_X, SET_Y, SET_PINDIRS = 0b001, 0b010, 0b100


class UnsupportedInstruction(Exception):
    pass


def decode(word):
    """Decode one instruction word into (kind, a, b); raises for anything not implemented."""
    def unsupported(why):
        return UnsupportedInstruction(f"0x{word:04x}: {why}")

    op, arg = word >> 13, word & 0xFF
    if (word >> 8) & 0x1F:
        raise unsupported("delay/side-set bits are not supported")
    if op == 0b000:                                   # JMP, p.322-323
        cond, addr = arg >> 5, arg & 0x1F
        if cond not in (JMP_ALWAYS, JMP_X_DEC, JMP_NOT_OSRE):
            raise unsupported(f"JMP condition {cond:03b}")
        return (JMP, cond, addr)
    if op == 0b001:                                   # WAIT, p.324
        polarity, source, index = arg >> 7, (arg >> 5) & 0b11, arg & 0x1F
        if source == 0b00:
            return (WAIT_GPIO, polarity, index)       # absolute GPIO number, p.342
        if source == 0b10 and not index & 0x18:
            return (WAIT_IRQ, polarity, index & 0x7)
        raise unsupported("WAIT source other than GPIO or a plain IRQ flag")
    if op == 0b011:                                   # OUT, p.325
        dest, count = arg >> 5, (arg & 0x1F) or 32
        if dest not in (OUT_PINS, OUT_NULL):
            raise unsupported(f"OUT destination {dest:03b}")
        return (OUT, dest, count)
    if op == 0b100:                                   # PULL, p.327
        if arg & 0x80 and not arg & 0x1F:
            return (PULL, (arg >> 6) & 1, (arg >> 5) & 1)   # (IfEmpty, Block)
        raise unsupported("PUSH")
    if op == 0b101:                                   # MOV, p.328
        dest, mov_op, src = arg >> 5, (arg >> 3) & 0b11, arg & 0b111
        if mov_op == 0 and dest in (REG_X, REG_Y) and src in (REG_X, REG_Y, REG_OSR):
            return (MOV, dest, src)
        raise unsupported("MOV other than X/Y <- X/Y/OSR")
    if op == 0b110:                                   # IRQ, p.330
        if arg & 0xE0 or arg & 0x18:
            raise unsupported("IRQ clear/wait or relative index")
        return (IRQ_SET, arg & 0x7, 0)
    if op == 0b111:                                   # SET, p.331
        dest, data = arg >> 5, arg & 0x1F
        if dest not in (SET_X, SET_Y, SET_PINDIRS):
            raise unsupported(f"SET destination {dest:03b}")
        return (SET, dest, data)
    raise unsupported("IN")


def parse_pio_header(text):
    """
    Programs and global defines from a pioasm-generated header. Returns
    ({name: {"instructions", "wrap_target", "wrap", "labels"}}, {define: value}).
    """
    programs = {}
    for name, body in re.findall(r"uint16_t (\w+)_program_instructions\[\] = \{(.*?)\};", text, re.S):
        programs[name] = {
            "instructions": [int(w, 16) for w in re.findall(r"^\s*(0x[0-9a-fA-F]{4}),", body, re.M)],
            "wrap_target": int(re.search(rf"#define {name}_wrap_target (\d+)", text).group(1)),
            "wrap": int(re.search(rf"#define {name}_wrap (\d+)", text).group(1)),
            "labels": {label: int(v) for label, v in re.findall(rf"#define {name}_offset_(\w+) (\d+)u", text)},
        }
    defines = {k: int(v) for k, v in re.findall(r"^#define (\w+) (\d+)$", text, re.M)}
    return programs, defines


def program(words, wrap_target=0, wrap=None, labels=None):
    """A program dict like parse_pio_header() returns, for hand-written test programs."""
    return {"instructions": list(words), "wrap_target": wrap_target,
            "wrap": len(words) - 1 if wrap is None else wrap, "labels": labels or {}}


class StateMachine:
    def __init__(self, pio, prog, *, autopull=False, threshold=32, shift_right=True,
                 out_base=0, out_count=1, set_base=0, set_count=1, fifo_depth=4):
        self.pio = pio
        self.words = list(prog["instructions"])
        self.instructions = [decode(w) for w in self.words]
        self.wrap_target, self.wrap = prog["wrap_target"], prog["wrap"]
        self.autopull, self.threshold, self.shift_right = autopull, threshold, shift_right
        self.out_base, self.out_count = out_base, out_count
        self.set_base, self.set_count = set_base, set_count
        self.fifo_depth = fifo_depth                  # 8 when the TX FIFO is joined, p.335
        self.fifo = deque()
        self.pc = self.x = self.y = self.osr = 0
        self.osr_count = 32                           # empty after reset/restart, p.338
        self.enabled = False

    # -- helpers ---------------------------------------------------------------------------
    def _next(self):
        self.pc = self.wrap_target if self.pc == self.wrap else self.pc + 1

    def _refill(self):
        self.osr = self.fifo.popleft()
        self.osr_count = 0

    def _out(self, dest, count):
        mask = (1 << count) - 1
        if self.shift_right:
            data, self.osr = self.osr & mask, (self.osr >> count) if count < 32 else 0
        else:
            data, self.osr = (self.osr >> (32 - count)) & mask, (self.osr << count) & 0xFFFFFFFF
        self.osr_count = min(32, self.osr_count + count)    # saturating, p.325
        if dest == OUT_PINS:
            for i in range(min(count, self.out_count)):
                self.pio.pin_out[self.out_base + i] = (data >> i) & 1

    # -- one PIO cycle -----------------------------------------------------------------------
    def step(self, t):
        kind, a, b = self.instructions[self.pc]
        if kind == OUT:
            self._out_cycle(a, b)
            return
        self._execute(kind, a, b, t)
        # Autopull on non-'OUT' cycles, including stalled ones (p.339)
        if (self.autopull and not self.pio.lazy_autopull
                and self.osr_count >= self.threshold and self.fifo):
            self._refill()

    def _out_cycle(self, dest, count):
        if self.autopull and self.pio.lazy_autopull:
            # Deliberately wrong model (rp2040js): refill only at the start of the next OUT
            if self.osr_count >= self.threshold:
                if not self.fifo:
                    return                            # stall
                self._refill()
            self._out(dest, count)
            self._next()
            return
        # Autopull on 'OUT' cycles (p.339)
        if self.autopull and self.osr_count >= self.threshold:
            if self.fifo:
                self._refill()
            return                                    # stall: can't fill and OUT in one cycle
        self._out(dest, count)
        self._next()
        if self.autopull and self.osr_count >= self.threshold and self.fifo:
            self._refill()                            # refill in the same cycle as the OUT

    def _execute(self, kind, a, b, t):
        pio = self.pio
        if kind == JMP:                               # p.322-323
            if a == JMP_ALWAYS:
                taken = True
            elif a == JMP_X_DEC:
                taken = self.x != 0                   # "non-zero, prior to decrement"
                self.x = (self.x - 1) & 0xFFFFFFFF    # X is always decremented
            else:
                taken = self.osr_count < self.threshold   # !OSRE
            if taken:
                self.pc = b
            else:
                self._next()
        elif kind == WAIT_GPIO:                       # p.324, synchronised input p.342
            if pio.synced_input(b, t) == a:
                self._next()
        elif kind == WAIT_IRQ:                        # p.324: polarity 1 clears the flag
            if ((pio.irq >> b) & 1) == a:
                if a:
                    pio.irq_clear |= 1 << b
                self._next()
        elif kind == IRQ_SET:                         # p.330
            pio.irq_set |= 1 << a
            self._next()
        elif kind == SET:                             # p.331
            if a == SET_X:
                self.x = b
            elif a == SET_Y:
                self.y = b
            else:
                for i in range(self.set_count):
                    pio.pin_dir[self.set_base + i] = (b >> i) & 1
            self._next()
        elif kind == MOV:                             # p.328
            value = {REG_X: self.x, REG_Y: self.y, REG_OSR: self.osr}[b]
            if a == REG_X:
                self.x = value
            else:
                self.y = value
            self._next()
        elif kind == PULL:                            # p.327; with autopull: no-op unless empty, p.339
            if_empty, block = a, b
            if (if_empty or self.autopull) and self.osr_count < self.threshold:
                self._next()
            elif self.fifo:
                self._refill()
                self._next()
            elif not block:
                self.osr, self.osr_count = self.x, 0
                self._next()

    def exec_instruction(self, word, t=0):
        """Like pio_sm_exec(): run one instruction immediately; the PC only changes for a JMP."""
        kind, a, b = decode(word)
        pc = self.pc
        if kind == OUT:
            self._out_cycle(a, b)
        else:
            self._execute(kind, a, b, t)
        if self.pc == pc and kind != JMP:
            raise RuntimeError(f"exec'd instruction 0x{word:04x} stalled")
        if kind != JMP:
            self.pc = pc
        self.pio.end_cycle()


class PIO:
    """One PIO block: state machines, shared IRQ flags and the GPIO pins they drive."""

    def __init__(self, input_level, *, lazy_autopull=False, sync_cycles=2):
        self.input_level = input_level                # input_level(gpio, t) -> 0/1, driven externally
        self.lazy_autopull = lazy_autopull
        self.sync_cycles = sync_cycles                # 2-flipflop input synchroniser, p.342
        self.irq = self.irq_set = self.irq_clear = 0
        self.pin_out = [0] * 32
        self.pin_dir = [0] * 32
        self.sms = []

    def add_sm(self, prog, **config):
        sm = StateMachine(self, prog, **config)
        self.sms.append(sm)
        return sm

    def synced_input(self, gpio, t):
        return self.input_level(gpio, t - self.sync_cycles)

    def pin(self, gpio):
        """Level the PIO drives on a pin, or None while it is an input (released)."""
        return self.pin_out[gpio] if self.pin_dir[gpio] else None

    def end_cycle(self):
        # IRQ flag changes become visible from the next cycle
        if self.irq_set or self.irq_clear:
            self.irq = (self.irq & ~self.irq_clear) | self.irq_set
            self.irq_set = self.irq_clear = 0

    def step(self, t):
        for sm in self.sms:
            if sm.enabled:
                sm.step(t)
        self.end_cycle()


class Console:
    """
    GameCube side of the EXI bus at logic level: drives CS (active low) and CLK (idle low),
    and reads DATA at the rising edge of every data clock. Each transfer is CS low, 32
    address clocks, the given number of data clocks, CS high.
    """

    def __init__(self, cs_pin, clk_pin, data_clocks, half_period=4, gap=16):
        self.cs_pin, self.clk_pin = cs_pin, clk_pin
        events = {cs_pin: [(-10**9, 1)], clk_pin: [(-10**9, 0)]}
        self.samples = []                             # (time, transfer, bit)
        self.cs_falls, self.cs_rises = [], []
        t = gap
        for n, clocks in enumerate(data_clocks):
            events[cs_pin].append((t, 0))
            self.cs_falls.append(t)
            t += gap
            for c in range(32 + clocks):
                events[clk_pin].append((t, 1))
                if c >= 32:
                    self.samples.append((t, n, c - 32))
                events[clk_pin].append((t + half_period, 0))
                t += 2 * half_period
            t += gap
            events[cs_pin].append((t, 1))
            self.cs_rises.append(t)
            t += gap
        self.end = t
        self._times = {pin: [e[0] for e in ev] for pin, ev in events.items()}
        self._levels = {pin: [e[1] for e in ev] for pin, ev in events.items()}
        self._cursor = {pin: (0, -10**9) for pin in events}

    def level(self, gpio, t):
        times = self._times.get(gpio)
        if times is None:
            return 0
        i, last = self._cursor[gpio]
        if t < last:                                  # queries are normally monotonic
            i = 0
        while i + 1 < len(times) and times[i + 1] <= t:
            i += 1
        self._cursor[gpio] = (i, t)
        return self._levels[gpio][i]


def run(pio, console, data_sm, words, data_pin, extra_cycles=64):
    """
    Simulate until the console is done. A DMA channel feeds `words` into the data state
    machine's TX FIFO (paced by its DREQ, one word per cycle at most). Returns
    (bits read per transfer, list of (time, direction) changes of the data pin).
    """
    words = deque(words)
    received = {}
    samples = console.samples
    s = 0
    direction = pio.pin_dir[data_pin]
    changes = []
    for t in range(console.end + extra_cycles):
        if words and len(data_sm.fifo) < data_sm.fifo_depth:
            data_sm.fifo.append(words.popleft())
        while s < len(samples) and samples[s][0] == t:
            received.setdefault(samples[s][1], []).append(pio.pin(data_pin))
            s += 1
        pio.step(t)
        if pio.pin_dir[data_pin] != direction:
            direction = pio.pin_dir[data_pin]
            changes.append((t, direction))
    return received, changes
