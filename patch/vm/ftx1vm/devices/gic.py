"""PL390 (GICv1) model: distributor 0xE8201000 + CPU interface 0xE8202000.

Semantics needed by the stock kernel (dec_irq.txt FUN_0001613C/FUN_000164F0):
register enables/priorities/targets/configs at boot, IRQ entry reads GICC_IAR
(at 0xE820200C), nested-priority management through PMR/BPR, EOIR write
deactivates.  Single core: targeting is accepted but ignored.
"""

from .. import addrs

SPURIOUS = 1023


class GIC:
    NAME = "gic"
    BASE = addrs.GICD_BASE
    SIZE = 0x2000            # covers GICD 0xE8201000 + GICC 0xE8202000

    def __init__(self, intids=addrs.GIC_INTIDS, log=None):
        self.nints = ((intids + 31) // 32) * 32
        self.enabled = set()
        self.pending = set()
        self.active = []               # stack of (intid, prio)
        self.prio = {i: 0 for i in range(self.nints)}
        self.gicd_ctl = 0
        self.gicc_ctl = 0
        self.pmr = 0
        self.bpr = 0
        self.log = log or (lambda *_: None)
        self.iar_reads = {}
        self.injections = 0

    # --- injection API -----------------------------------------------------
    def pend(self, intid):
        if intid not in self.pending:
            self.pending.add(intid)
            self.injections += 1

    def running_prio(self):
        return min((p for _, p in self.active), default=0xFF)

    def best(self):
        """Highest-priority deliverable INTID or None (priority field order)."""
        if not (self.gicd_ctl & 1) or not (self.gicc_ctl & 1):
            return None
        best = None
        for intid in self.enabled & self.pending:
            p = self.prio.get(intid, 0)
            if p >= self.pmr:          # PMR masks equal/lower priority (0 blocks all)
                continue
            if p >= self.running_prio():
                continue
            if best is None or (p, intid) < best[:2]:
                best = (p, intid)
        return None if best is None else best[1]

    def deliverable(self):
        return self.best() is not None

    # --- register file -----------------------------------------------------
    def read(self, off, size):
        if off < 0x1000:               # distributor
            return self._gicd_read(off, size)
        return self._gicc_read(off - 0x1000, size)

    def write(self, off, value, size):
        if off < 0x1000:
            self._gicd_write(off, value, size)
        else:
            self._gicc_write(off - 0x1000, value, size)

    def _gicd_read(self, off, size):
        if off == 0x000:               # CTLR
            return self.gicd_ctl
        if off == 0x004:               # TYPER: (lines-1) | cpu number
            return ((self.nints // 32) - 1)
        if off == 0x008:               # IIDR
            return 0x0200143B          # generic ARM GIC stub ID (ICDIIDR unused by firmware)
        if 0x100 <= off < 0x200:       # ISENABLER/ICENABLER (reads = status)
            idx = ((off - 0x100) & 0x7F) * 8
            return self._enabled_word(idx)
        if 0x200 <= off < 0x300:       # ISPENDR/ICPENDR
            idx = (off - 0x200) * 8
            word = 0
            for i in range(idx, min(idx + 32, self.nints)):
                if i in self.pending:
                    word |= 1 << (i - idx)
            return word
        if 0x300 <= off < 0x400:       # ISACTIVER
            idx = (off - 0x300) * 8
            word = 0
            for i, _ in self.active:
                if idx <= i < idx + 32:
                    word |= 1 << (i - idx)
            return word
        if 0x400 <= off < 0x400 + self.nints:           # IPRIORITYR (byte regs)
            base_idx = off - 0x400
            return sum(self.prio.get(base_idx + k, 0) << (8 * k) for k in range(size))
        if 0x800 <= off < 0x800 + self.nints:           # ITARGETSR
            return sum(0x01 << (8 * k) for k in range(min(size, 4)))
        if 0xC00 <= off < 0xC00 + self.nints // 4:      # ICFGR (2 bits each)
            idx = (off - 0xC00) * 16
            word = 0
            for i in range(idx, min(idx + 16, self.nints)):
                if getattr(self, "edge", set()) and i in self.edge:
                    word |= 2 << (2 * (i - idx))
            return word
        return 0

    def _enabled_word(self, idx):
        word = 0
        for i in range(idx, min(idx + 32, self.nints)):
            if i in self.enabled:
                word |= 1 << (i - idx)
        return word

    def _gicd_write(self, off, value, size):
        if off == 0x000:
            self.gicd_ctl = value & 1
        elif 0x100 <= off < 0x180:     # ISENABLER
            idx = (off - 0x100) * 8
            for b in range(32):
                if value & (1 << b) and idx + b < self.nints:
                    self.enabled.add(idx + b)
        elif 0x180 <= off < 0x200:     # ICENABLER (kernel pool 0xE8201180)
            idx = (off - 0x180) * 8
            for b in range(32):
                if value & (1 << b):
                    self.enabled.discard(idx + b)
        elif 0x200 <= off < 0x280:     # ISPENDR (software-interrupt pends)
            idx = (off - 0x200) * 8
            for b in range(32):
                if value & (1 << b):
                    self.pend(idx + b)
        elif 0x280 <= off < 0x300:     # ICPENDR
            idx = (off - 0x280) * 8
            for b in range(32):
                if value & (1 << b):
                    self.pending.discard(idx + b)
        elif 0x400 <= off < 0x400 + self.nints:
            base_idx = off - 0x400
            for k in range(min(size, 4)):
                self.prio[base_idx + k] = (value >> (8 * k)) & 0xFF
        elif 0xC00 <= off < 0xC40:     # ICFGR
            idx = (off - 0xC00) * 16
            self.edge = getattr(self, "edge", set())
            for b in range(16):
                if value & (2 << (2 * b)):
                    self.edge.add(idx + b)
                else:
                    self.edge.discard(idx + b)
        # ITARGETSR writes accepted & ignored

    def _gicc_read(self, off, size):
        if off == 0x000:               # CTLR
            return self.gicc_ctl
        if off == 0x004:               # PMR
            return self.pmr
        if off == 0x008:               # BPR
            return self.bpr
        if off == 0x00C:               # IAR
            intid = self.best()
            if intid is None:
                return SPURIOUS
            self.pending.discard(intid)
            self.active.append((intid, self.prio.get(intid, 0)))
            self.iar_reads[intid] = self.iar_reads.get(intid, 0) + 1
            return intid
        if off == 0x014:               # RPR
            return self.running_prio()
        if off == 0x018:               # HPPIR
            intid = self.best()
            return SPURIOUS if intid is None else intid
        if off == 0xFC:                # IIDR
            return 0x0202143B
        return 0

    def _gicc_write(self, off, value, size):
        if off == 0x000:
            self.gicc_ctl = value & 7
        elif off == 0x004:
            self.pmr = value & 0xFF
        elif off == 0x008:
            self.bpr = value & 7
        elif off == 0x010:             # EOIR
            for i in range(len(self.active) - 1, -1, -1):
                if self.active[i][0] == value & 0x3FF:
                    del self.active[i]
                    break
