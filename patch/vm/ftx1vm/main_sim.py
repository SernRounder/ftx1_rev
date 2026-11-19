"""MainSim: behavioural MAIN (RX651) peer on the SCIF5 link.

Panel->MAIN framing (dec_1464c): AA 00 LEN(u16=payload+1) cmd data... SUM
(SUM = 8-bit sum over cmd+data).  MAIN->panel replies are bare
cmd data... SUM.  Every panel command gets an ACK (06 cmd sum); a periodic
0x65 datetime push keeps the clock task fed ("frequency content left
empty" until real state data is wired in).
"""

import struct
import time as _time


def _sum(payload):
    return sum(payload) & 0xFF


class MainSim:
    def __init__(self, scif, clock, log=None, epoch=None):
        self.scif = scif
        self.clock = clock
        self.log = log or (lambda *_: None)
        self.epoch = epoch or (2026, 11, 10, 0, 0, 0)     # y m d h m s
        self.rx = bytearray()
        self.frames = []                 # (cmd, data) panel->MAIN
        self.replies = bytearray()       # everything we sent back
        self.ack_all = True
        self.clock.at(50_000_000, self._push_time)         # first datetime push at 50 ms

    # --- panel -> MAIN -------------------------------------------------------
    def feed_byte(self, byte):
        self.rx.append(byte)
        n = len(self.rx)
        if n >= 4 and self.rx[0] == 0xAA and self.rx[1] == 0x00:
            length = struct.unpack_from("<H", self.rx, 2)[0]
            if n >= 4 + length:          # LEN counts cmd+data+sum? payload+1
                frame = bytes(self.rx[:4 + length])
                self.rx = self.rx[4 + length:]
                payload = frame[4:4 + length - 1]          # cmd+data (sum excl.)
                if _sum(payload) == frame[3 + length]:
                    self.frames.append((payload[0], payload[1:]))
                    self._on_frame(payload[0], payload[1:])
                else:
                    self.log(f"[main] bad checksum: {frame.hex()}")

    def _on_frame(self, cmd, data):
        self.log(f"[main] panel cmd {cmd:#04x} data={data.hex()}")
        if self.ack_all:
            self._reply(bytes([0x06, cmd]))

    def _reply(self, payload):
        frame = bytes(payload) + bytes([_sum(payload)])
        self.replies.extend(frame)
        self.scif.rx_inject(frame)

    # --- periodic datetime push (cmd 0x65) -----------------------------------
    def _push_time(self, now_ns):
        secs = now_ns // 1_000_000_000
        y0, mo0, d0, h0, mi0, s0 = self.epoch
        base = _time.mktime((y0, mo0, d0, h0, mi0, s0, 0, 0, -1)) if hasattr(_time, "mktime") else 0
        total = int(base) + secs
        lt = _time.gmtime(total)
        payload = bytes([0x65, lt.tm_year - 2000, lt.tm_mon, lt.tm_mday,
                         (lt.tm_wday + 1) % 7, lt.tm_hour, lt.tm_min, lt.tm_sec])
        self._reply(payload)
        return 1_000_000_000             # every second
