"""OSTM0/1 interval timers (RZ/A1H) — OSTM0 is the µITRON kernel tick.

Register map: CMP 0x00, CNT 0x04, TE 0x10, TS 0x14, TT 0x18,
CTL 0x20 (bit 1 selects free-running mode).

The kernel tick cadence is derived from whatever OCR the firmware writes;
`ostm_hz` defaults to the 32 MHz used by the stock tick conversion.
"""

from .. import addrs


class OSTM:
    def __init__(self, base, intid, clock, gic, ostm_hz=32_000_000, log=None,
                 name="ostm"):
        self.NAME = name
        self.BASE = base
        self.SIZE = 0x400
        self.clock = clock
        self.gic = gic
        self.period_ns = 1_000_000_000 / ostm_hz
        self.ocr = 0
        self.running = False
        self.mode_interval = True
        self.control = 0
        self._start_ns = 0
        self._counter = 0
        self._generation = 0
        self.started_count = 0
        self.ticks = 0
        self.log = log or (lambda *_: None)
        self._due_ns = None
        self.intid = intid

    # --- register file -----------------------------------------------------
    def read(self, off, size):
        if off == 0x00:                # CMP
            return self.ocr
        if off == 0x04:                # CNT
            if not self.running:
                return self._counter
            if not self.mode_interval:
                return int((self.clock.now_ns - self._start_ns) / self.period_ns) & 0xFFFFFFFF
            return max(0, int((self._due_ns - self.clock.now_ns) / self.period_ns) - 1)
        if off == 0x10:                # TE
            return 1 if self.running else 0
        if off == 0x20:                # CTL
            return self.control
        return 0

    def write(self, off, value, size):
        if off == 0x00:
            self.ocr = value & 0xFFFFFFFF
        elif off == 0x14 and value & 1 and not self.running:
            self.running = True
            self.started_count += 1
            self._start_ns = self.clock.now_ns
            self._arm()
        elif off == 0x18 and value & 1:
            self._counter = self.read(0x04, 4)
            self.running = False
            self._due_ns = None
            self._generation += 1
        elif off == 0x20:
            self.control = value & 0x03
            self.mode_interval = not (value & 2)

    # --- timing ------------------------------------------------------------
    def _arm(self):
        interval = max(1, round((self.ocr + 1) * self.period_ns))
        self._due_ns = self.clock.now_ns + interval
        generation = self._generation
        self.clock.at(interval, lambda now: self._tick(now, generation))

    def _tick(self, now_ns, generation):
        if not self.running or generation != self._generation:
            return None
        self.ticks += 1
        self.gic.pend(self.intid)
        counts = self.ocr + 1 if self.mode_interval else 1 << 32
        interval = max(1, round(counts * self.period_ns))
        self._due_ns = now_ns + interval
        return interval


def attach_ostms(bus, clock, gic, log=None, ostm_hz=32_000_000):
    ostm0 = OSTM(addrs.OSTM0_BASE, addrs.IRQ_OSTM0, clock, gic, ostm_hz, log, "ostm0")
    ostm1 = OSTM(addrs.OSTM1_BASE, addrs.IRQ_OSTM1, clock, gic, ostm_hz, log, "ostm1")
    bus.attach(ostm0)
    bus.attach(ostm1)
    return ostm0, ostm1
