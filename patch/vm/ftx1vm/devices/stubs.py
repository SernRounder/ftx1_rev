"""Miscellaneous stub devices: completion flags, SPIBSC/CPG/PL310/SDHI."""

from .. import addrs


class StubDevice:
    def __init__(self, name, base, size, read_value=0):
        self.NAME = name
        self.BASE = base
        self.SIZE = size
        self.read_value = read_value
        self.writes = {}
        self.bus = None

    def read(self, off, size):
        return self.read_value

    def write(self, off, value, size):
        self.writes[off] = value


class AlwaysReadyFlags(StubDevice):
    """QSPI/SPI channel completion flags (0x607C0650..0x607C0660): polled
    busy-waits everywhere in the 0x208xx/0x209xx driver family.  The VM has
    no transfer engine, so every read reports "complete" (1)."""

    def read(self, off, size):
        return (1 << (8 * min(size, 4))) - 1     # 0xFF.. bytes


class RIICMinimal(StubDevice):
    """Minimal RIIC (I2C master) model for boot: ICSR2 (0x24) reports
    TDRE|TEND|START (bus idle, tx empty); ICDRR (0x30) reads 0.  The touch
    task's polling transactions complete immediately with "no data"."""

    def read(self, off, size):
        if off == 0x24:                      # ICSR2
            return 0xC8                       # TDRE | TEND | START
        if off == 0x30:                       # ICDRR
            return 0x00
        if off == 0x04:                       # ICCR2: bus not busy
            return 0x00
        return 0


def attach_stubs(bus, log=None):
    devs = [
        AlwaysReadyFlags("chan-flags", 0x607C0650, 0x10),
        RIICMinimal("riic0", addrs.RIIC0_BASE + 0x000, 0x400),
        RIICMinimal("riic1", addrs.RIIC0_BASE + 0x400, 0x400),
        RIICMinimal("riic2", addrs.RIIC0_BASE + 0x800, 0x400),
        RIICMinimal("riic3", addrs.RIIC0_BASE + 0xC00, 0x400),
        StubDevice("qspi", addrs.CPG_BASE + 0x400, 0x80),
        StubDevice("cpg", addrs.CPG_BASE, 0x400),
        StubDevice("pl310", addrs.PL310_BASE, 0x1000),
        StubDevice("spibsc0", addrs.SPIBSC0_BASE, 0x100),
        StubDevice("spibsc1", addrs.SPIBSC1_BASE, 0x100),
        StubDevice("sdhi0", addrs.SDHI0_BASE, 0x200),
        StubDevice("mtu2", addrs.MTU2_BASE, 0x300),
        StubDevice("jcu", addrs.JCU_BASE, 0x200),
        StubDevice("dmac", 0xE8200000, 0x1000),
        StubDevice("irqc", 0xFCFE7000, 0x100),
        StubDevice("pior", 0xFCFEF800, 0x100),
    ]
    for dev in devs:
        bus.attach(dev)
    return devs
