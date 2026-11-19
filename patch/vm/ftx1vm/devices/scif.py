"""SCIF5 UART (panel <-> MAIN link, 345600 8N2) with GIC-wired interrupts.

Register map (stride 4, 16-bit regs): SCSMR 0x00, SCBRR 0x04, SCSCR 0x08,
SCFTDR 0x0C, SCFSR 0x10, SCFRDR 0x14, SCFCR 0x18, SCFDR 0x1C, SCLSR 0x24,
SCEMR 0x28.

TX: firmware writes SCFTDR then the TXI ISR (243) sends more; we complete
instantly (TDRE set, TXI pended when TIE) and hand the byte to the peer.
RX: peer bytes enter the FIFO with RDF set and RXI (242) pended when RIE;
the stock RX ISR (FUN_0001CC6C) drains SCFRDR and clears SCFSR.
"""

from .. import addrs

# SCFSR bits
TDRE, RDF, ERR = 0x80, 0x40, 0x1C


class SCIF5:
    NAME = "scif5"
    BASE = addrs.SCIF5_BASE
    SIZE = 0x40

    def __init__(self, clock, gic, peer=None, log=None):
        self.clock = clock
        self.gic = gic
        self.peer = peer                  # MainSim: receives TX bytes
        self.log = log or (lambda *_: None)
        self.tx_bytes = bytearray()
        self.rx_fifo = bytearray()
        self.scr = 0
        self.fsr = TDRE                   # transmit empty, nothing received
        self.bit_ns = 1_000_000_000 // addrs.SCIF5_BAUD
        self.irq_tx = self.irq_rx = 0
        self.rx_log = bytearray()

    # --- guest interface ---------------------------------------------------
    def read(self, off, size):
        if off == 0x08:                   # SCSCR
            return self.scr
        if off == 0x10:                   # SCFSR
            return self.fsr
        if off == 0x14:                   # SCFRDR (pops one byte)
            if self.rx_fifo:
                return self.rx_fifo.pop(0)
            return 0
        if off == 0x1C:                   # SCFDR: [15:8] tx count, [7:0] rx count
            return (0 << 8) | min(len(self.rx_fifo), 0x1F)
        if off == 0x24:                   # SCLSR: no overrun
            return 0
        return 0

    def write(self, off, value, size):
        if off == 0x08:                   # SCSCR
            old = self.scr
            self.scr = value & 0xFF
            if value & 0x80 and not old & 0x80:     # TIE turned on
                self._pend_tx()
            if value & 0x40 and not old & 0x40:     # RIE turned on
                if self.rx_fifo:
                    self.gic.pend(addrs.IRQ_SCIF5_RXI)
        elif off == 0x0C:                 # SCFTDR: byte to MAIN
            self.tx_bytes.append(value & 0xFF)
            if self.peer:
                self.peer.feed_byte(value & 0xFF)
        elif off == 0x10:                 # SCFSR: writing clears bits
            self.fsr &= ~(value & 0xFF) & ~0x03
        elif off == 0x18:                 # SCFCR: TFRST/RFRST reset FIFOs
            if value & 0x04:
                self.rx_fifo.clear()
        # SCSMR/SCBRR/SCFCR others: accepted, no behavioural model needed

    # --- peer -> guest -------------------------------------------------------
    def rx_inject(self, data):
        """Queue bytes for the firmware at wire cadence; RDF+RXI per byte."""
        for i, byte in enumerate(data):
            self.clock.at(i * self.bit_ns * 10, lambda ns, b=byte: self._rx_byte(b))

    def _rx_byte(self, byte):
        self.rx_fifo.append(byte)
        self.rx_log.append(byte)
        self.fsr |= RDF
        if self.scr & 0x40:               # RIE
            self.gic.pend(addrs.IRQ_SCIF5_RXI)
            self.irq_rx += 1

    def _pend_tx(self):
        if self.fsr & TDRE and self.scr & 0x80:
            self.gic.pend(addrs.IRQ_SCIF5_TXI)
            self.irq_tx += 1


def attach_scif5(bus, clock, gic, peer=None, log=None):
    dev = SCIF5(clock, gic, peer, log)
    bus.attach(dev)
    return dev
