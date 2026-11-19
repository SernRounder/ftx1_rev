"""Exercise the standalone CW image with generated PCM and real ARM hooks."""

import argparse
import math
import random
import re
import struct
import wave
from array import array
from pathlib import Path

from elftools.elf.elffile import ELFFile
from unicorn import UC_ARCH_ARM, UC_HOOK_CODE, UC_MODE_ARM, Uc
from unicorn.arm_const import (
    UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP,
)

from test_ft8_menu import IMAGE_BASE, RETURN, UI, read_display_sfl

RATE = 16000
ALPHABET = dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
                    ".- -... -.-. -.. . ..-. --. .... .. .--- -.- .-.. -- -. --- "
                    ".--. --.- .-. ... - ..- ...- .-- -..- -.-- --.. "
                    "----- .---- ..--- ...-- ....- ..... -.... --... ---.. ----.".split(), strict=True))


class Colored:
    """Band-limited noise: adjacent samples correlate like real AF output."""

    def __init__(self, rng, amp):
        self.rng, self.amp = rng, amp
        self.window = [0.0, 0.0, 0.0, 0.0]

    def next(self):
        self.window = self.window[1:] + [self.rng.uniform(-self.amp, self.amp)]
        return sum(self.window) / 2


def audio(segments, pitch, *, noise=0, jitter=0, pause_units=7, soft=0):
    """soft: fixed rise/fall time in milliseconds, like real keying shaping."""
    rng = random.Random(2120)
    gen = Colored(rng, noise) if noise else None
    output = array("h")

    def interval(mark, units, dot):
        count = round(units * dot * (1 + rng.uniform(-jitter, jitter)))
        start = len(output)
        ramp = round(soft * RATE / 1000)
        for i in range(count):
            level = 1.0
            if ramp:
                level = min(1.0, min(i, count - 1 - i) / ramp)
            value = (gen.next() if gen else 0)
            if mark:
                value += 4000 * level * math.sin(2 * math.pi * pitch * (start + i) / RATE)
            output.append(int(round(value)))

    interval(False, 2, RATE // 10)
    for text, wpm in segments:
        dot = RATE * 1.2 / wpm
        words = text.split()
        for word_index, word in enumerate(words):
            for letter_index, letter in enumerate(word):
                for mark_index, mark in enumerate(ALPHABET[letter]):
                    if mark_index:
                        interval(False, 1, dot)
                    interval(True, 1 if mark == "." else 3, dot)
                if letter_index + 1 < len(word):
                    interval(False, 3, dot)
            if word_index + 1 < len(words):
                interval(False, 7, dot)
        interval(False, pause_units, dot)
    return output


def raw_audio(letters, pitch, wpm=20, *, noise=0):
    """Morse from explicit element patterns, one letter per list entry."""
    rng = random.Random(9)
    gen = Colored(rng, noise) if noise else None
    output = array("h")
    dot = RATE * 1.2 / wpm

    def interval(mark, units):
        start = len(output)
        output.extend(round((gen.next() if gen else 0) +
                            (4000 * math.sin(2 * math.pi * pitch * (start + i) / RATE) if mark else 0))
                      for i in range(round(units * dot)))

    interval(False, 2)
    for index, pattern in enumerate(letters):
        for mark_index, mark in enumerate(pattern):
            if mark_index:
                interval(False, 1)
            interval(True, 1 if mark == "." else 3)
        interval(False, 3 if index + 1 < len(letters) else 7)
    interval(False, 20)
    return output


def dash_fade_audio():
    """Six Ks at 20 WPM, with a 28 ms dropout in the final K's first dash."""
    samples = raw_audio(["-.-"] * 6, 600)
    dot = RATE * 60 // 1000
    dash_center = (2 + 5 * 12) * dot + 3 * dot // 2
    half_fade = 14 * RATE // 1000
    samples[dash_center - half_fade:dash_center + half_fade] = array("h", [0]) * (2 * half_fade)
    return samples


class Board:
    def __init__(self, image, elf):
        self.cpu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        self.cpu.mem_map(0x60000000, 0xA00000)
        self.cpu.mem_map(RETURN, 0x1000)
        self.cpu.mem_write(IMAGE_BASE, image)
        self.stack = 0x609FF000
        self.pcm = 0x600F0000
        self.details = self.pcm + 0x1000
        self.frame = 0x60010000
        self.drawn = []
        self.fills = []
        self.commands = []
        self.clock = 0
        self._cmd_seq = 0
        self.wire_status = False
        with elf.open("rb") as file:
            table = ELFFile(file).get_section_by_name(".symtab")
            self.poll = table.get_symbol_by_name("cw_worker_step")[0]["st_value"]
        self.stubs = {0x41FF8: 0, 0x410D0: 0, 0x2BB54: 0, 0x3BD3C: 0, 0x1669C: lambda: self.clock,
                      0x448B8: self.frame, 0x625A0: self.fill, 0x23D64: self.text,
                      0x62818: 0, 0x78FB0: self.create, 0x7A830: 0, 0x3000: 0,
                      0x450B4: 0x1234, 0xB0BAC: 0, 0xC965C: 0, 0x14A1C: self.send}
        for offset in self.stubs:
            address = IMAGE_BASE + offset
            self.cpu.hook_add(UC_HOOK_CODE, self.stub, begin=address, end=address)
        for address in (0x60414A1C, 0x604410D0, 0x6042BB54):
            self.cpu.mem_write(address, struct.pack("<I", 0xE12FFF1E))

    def send(self):
        ptr, size = (self.cpu.reg_read(reg) for reg in (UC_ARM_REG_R0, UC_ARM_REG_R1))
        self.commands.append(bytes(self.cpu.mem_read(ptr, size)))
        return 0

    def word(self, addr):
        return struct.unpack("<I", self.cpu.mem_read(addr, 4))[0]

    def stub(self, cpu, addr, _size, _user):
        action = self.stubs[addr - IMAGE_BASE]
        result = action() if callable(action) else action
        cpu.reg_write(UC_ARM_REG_R0, result)
        cpu.reg_write(UC_ARM_REG_PC, cpu.reg_read(UC_ARM_REG_LR))

    def text(self):
        pointer = self.cpu.reg_read(UC_ARM_REG_R1)
        count = self.cpu.reg_read(UC_ARM_REG_R2)
        self.drawn.append(bytes(self.cpu.mem_read(pointer, 2 * count)).decode("utf-16le"))
        return 0

    def fill(self):
        self.fills.append((self.cpu.reg_read(UC_ARM_REG_R3), self.cpu.reg_read(UC_ARM_REG_R2),
                           self.word(self.cpu.reg_read(UC_ARM_REG_SP)),
                           self.word(self.cpu.reg_read(UC_ARM_REG_SP) + 4)))
        return 0

    def create(self):
        params = self.cpu.reg_read(UC_ARM_REG_R1)
        assert self.word(params + 12) == 6 and self.word(params + 16) == 4096
        return 1

    def call(self, addr, r0=0, r1=0, r2=0, *, end=RETURN, budget=4_000_000):
        for register, value in ((UC_ARM_REG_R0, r0), (UC_ARM_REG_R1, r1), (UC_ARM_REG_R2, r2),
                                (UC_ARM_REG_SP, self.stack), (UC_ARM_REG_LR, RETURN)):
            self.cpu.reg_write(register, value)
        self.cpu.emu_start(addr, end, count=budget)
        assert self.cpu.reg_read(UC_ARM_REG_PC) == end
        assert self.cpu.reg_read(UC_ARM_REG_SP) == self.stack
        return self.cpu.reg_read(UC_ARM_REG_R0)

    def hit(self, x, y):
        return self.call(0x6042387C, x, y, self.details)

    def touch(self, event):
        self.call(0x604232E0, 1, event)
        self.call(0x604232E0, 0, event)

    def refresh(self):
        self.clock += 101_000
        self.drawn.clear()
        self.fills.clear()
        self.call(0x604438F4, end=0x604438F8)
        self.call(0x60443AE8, end=0x60443AEC)

    def set_pitch(self, pitch, side=1):
        self.cpu.mem_write(UI + 0xDD + side * 0x4C, bytes(((pitch - 300) // 10,)))

    def send_mode(self, mode, revision, *, packet_type=0x20, power=37, spa=0):
        size = {0x20: 0x13c, 0x60: 0x14d, 0x62: 0x23b}[packet_type]
        stock = bytearray(size)
        stock[0], stock[34], stock[-2] = packet_type, 0x65, 0x32
        stock[-1] = sum(stock) & 0xff
        pkt = stock.copy()
        state = 0x80 | ((revision & 15) << 3) | (mode << 1)
        pkt[9], pkt[32], pkt[33] = 0x80, power, state | spa
        pkt[-1] = sum(pkt[:-1]) & 0xff
        self.cpu.mem_write(self.pcm, bytes(pkt))
        if self.wire_status:
            metadata = self.pcm + 0x400
            self.cpu.mem_write(metadata, struct.pack("<BBHB7x", packet_type, 0, size - 2, 1))
            self.cpu.reg_write(UC_ARM_REG_R3, size)
            assert self.call(0x604C9BF4, 0, metadata, self.pcm) == size
        else:
            self.call(0x604C9D00, 0, self.pcm, len(pkt), end=0x604C9D04)
        assert self.cpu.mem_read(self.pcm, len(pkt)) == stock
        return state

    def activate(self, mode, pitch=600):
        self._cmd_seq += 1
        self.cpu.mem_write(UI, b"\x20")
        self.cpu.mem_write(UI + 0x13B, b"\x00")
        self.cpu.mem_write(UI + 0x6C, b"\x00")
        self.cpu.mem_write(0x60939947, b"\x05")
        self.cpu.mem_write(UI + 0xA3 + 0x4C, bytes((mode,)))
        self.set_pitch(pitch)
        self.send_mode(2, self._cmd_seq)
        self.refresh()
        assert "CLOSE" in self.drawn
        self.call(self.poll)

    def feed(self, samples):
        for offset in range(0, len(samples), 768):
            frame = samples[offset:offset + 768]
            self.cpu.mem_write(self.pcm, struct.pack("<HH", len(frame), 0) + frame.tobytes())
            assert self.call(0x60445170, self.pcm, end=0x60445174) == 0x1234
            self.call(self.poll)
        self.refresh()
        assert all(y >= 378 and y + height <= 420 for _, y, _, height in self.fills)
        return self.drawn


def wpm_from(lines):
    for line in lines:
        if line.endswith("WPM") or "WPM " in line:
            digits = line[:line.find("WPM")]
            if digits.isdigit():
                return int(digits)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--weak-wav", type=Path, help="Replay the agreed -11 dB, 12 WPM reference")
    args = parser.parse_args()
    image = read_display_sfl(args.image)
    if args.weak_wav:
        board = Board(image, args.build_dir / "cw.elf")
        board.activate(2)
        with wave.open(str(args.weak_wav), "rb") as wav:
            assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (RATE, 1, 2)
            result = board.feed(array("h", wav.readframes(wav.getnframes())))
        assert result[2:] == ["CQ TEST DE K1K K K 599"] and wpm_from(result) == 12, result
        print("PASS: -11 dB reference decoded CQ TEST DE K1K K K 599 at 12 WPM", flush=True)
    board = Board(image, args.build_dir / "cw.elf")
    board.activate(2)
    result = board.feed(dash_fade_audio())
    assert result[2:] == ["KKKKKK"], result
    print("PASS: 28 ms mid-dash dropout preserves the final K", flush=True)
    for speed, pitch, mode in ((10, 425, 2), (20, 600, 3), (30, 725, 2), (40, 950, 3)):
        board = Board(image, args.build_dir / "cw.elf")
        board.activate(mode, pitch // 10 * 10)
        result = board.feed(audio([("CQ TEST 599", speed)], pitch, noise=240))
        assert "CQ TEST 599" in result, (speed, result)
        reported = wpm_from(result)
        assert reported and abs(reported - speed) <= 3, (speed, reported)
        caption = result[0]
        assert re.fullmatch(r"\d+WPM \d+ R\d+", caption), caption
        assert board.hit(765, 413) == 0x1134
        board.touch(0x1134)
        board.refresh()
        assert "CLOSE" not in board.drawn
        print(f"PASS: CW mode {mode}, {pitch} Hz, {speed} WPM -> {reported} WPM [{caption}]", flush=True)

    board = Board(image, args.build_dir / "cw.elf")
    board.activate(3, 620)
    # A corrupt DMA header (count beyond the buffer) must be rejected before
    # any payload word is read; on hardware a wild read is a data abort.
    board.cpu.mem_write(board.pcm, struct.pack("<HH", 65535, 0))
    assert board.call(0x60445170, board.pcm, end=0x60445174) == 0x1234
    board.call(board.poll)
    board.feed(array("h", [0]) * 768)  # the decoder keeps running afterwards
    assert any(line.startswith("WAIT ") for line in board.drawn), board.drawn
    gen = Colored(random.Random(7), 5000)
    noise = array("h", (int(round(gen.next())) for _ in range(RATE * 8)))
    result = board.feed(noise)
    assert (len(result) == 3 and result[0].startswith("WAIT ") and result[1] == "CLOSE"
            and re.fullmatch(r"F\d+ D[012] P\d+ L\d+", result[2])), result
    frames = int(result[0][result[0].rfind("R") + 1:])
    assert frames == math.ceil(RATE * 8 / 768) + 2, result  # noise frames + the corrupt and silence probes
    result = board.feed(audio([("CQ TEST 599", 28), ("VVV TEST DE W1AW", 18)], 625,
                              noise=450, jitter=0.08))
    text = result[-1]
    assert text.startswith("CQ TEST 599 ") and text.endswith("TEST DE W1AW"), result
    reported = wpm_from(result)
    assert reported and abs(reported - 18) <= 2, result
    board.cpu.mem_write(0x60939942 + 0x0B, b"\x50")
    stock_hit = 0x604C61E0
    board.stubs[stock_hit - IMAGE_BASE] = 0x4567
    stock_hook = board.cpu.hook_add(UC_HOOK_CODE, board.stub, begin=stock_hit, end=stock_hit)
    board.refresh()
    assert "CLOSE" not in board.drawn and board.hit(765, 413) == 0x4567
    board.cpu.hook_del(stock_hook)
    board.cpu.mem_write(0x60939942 + 0x0B, b"\0")
    board.cpu.mem_write(UI + 0x1F, b"\x02")
    result = board.feed(audio([("CQ TEST 599", 28)], 625))
    assert result == ["CW-U/L", "CLOSE", text], result
    print("PASS: noise rejection, 28 to 18 WPM with timing jitter, and pause during TX", flush=True)

    # The real DMA stream may interleave two channels. Duplicated pairs and
    # distinct channels must both demux to one lane and still decode.
    for kind in ("dup", "cross"):
        board = Board(image, args.build_dir / "cw.elf")
        board.activate(3)
        mono = audio([("CQ TEST 599", 20)], 600, noise=240)
        if kind == "dup":
            stream = array("h", (sample for value in mono for sample in (value, value)))
        else:
            other = Colored(random.Random(31), 2000)
            stream = array("h", (sample for value in mono
                                 for sample in (value, int(round(other.next())))))
        result = board.feed(stream)
        assert "CQ TEST 599" in result, (kind, result)
    print("PASS: duplicated and distinct interleaved word streams decode after channel demux", flush=True)

    board = Board(image, args.build_dir / "cw.elf")
    board.activate(2)
    result = board.feed(raw_audio(["........", "."], 600))
    text = result[-1]
    assert text.startswith("?") and text.endswith("E"), result  # overlong code emits ?, dot letter survives
    result = board.feed(audio([("CQ TEST", 20)], 600, noise=300))
    assert "CQ TEST" in result, result
    print("PASS: overlong Morse code emits a low-confidence ? instead of vanishing", flush=True)

    for speed in (12, 20, 30, 40):
        board = Board(image, args.build_dir / "cw.elf")
        board.activate(2)
        result = board.feed(audio([("CQ TEST 599", speed)], 600, noise=600, jitter=0.16))
        assert "CQ TEST 599" in result, (speed, result)
    print("PASS: 16% timing jitter and added noise at all four test speeds", flush=True)

    # Unstable-fist regressions: mid-message speed drift, soft keying edges
    # that clip every detected mark short, and heavy element jitter. Each of
    # these used to shred letters into runs of single-dot "e".
    board = Board(image, args.build_dir / "cw.elf")
    board.activate(2)
    result = board.feed(audio([("CQ TEST", 20), ("DE W1AW", 14), ("73", 20)], 600, pause_units=3))
    joined = " ".join(result[2:])
    assert "CQ TEST" in joined and "DE W1AW" in joined, result
    print("PASS: 20 to 14 to 20 WPM drift inside one transmission", flush=True)

    for edge in (6, 12):
        board = Board(image, args.build_dir / "cw.elf")
        board.activate(2)
        result = board.feed(audio([("CQ TEST 599", 15)], 600, noise=200, soft=edge))
        text = result[-1]
        assert "CQ TEST" in text, (edge, result)
        print(f"PASS: {edge} ms keying rise/fall decodes [{text}]", flush=True)

    board = Board(image, args.build_dir / "cw.elf")
    board.activate(2)
    result = board.feed(audio([("CQ TEST", 15)], 600, noise=300, jitter=0.22))
    assert "CQ TEST" in result, result
    print("PASS: 22% element jitter at 15 WPM", flush=True)

    # The real panel tap sits near the bottom of the 16-bit range: bench
    # peaks of 4..5 on noise and 7 on signal. Decode these levels directly.
    for scale, label in ((8, "bench level"), (60, "quiet channel")):
        board = Board(image, args.build_dir / "cw.elf")
        board.activate(3)
        full = audio([("CQ TEST 599", 15)], 600, noise=0)
        tiny = array("h", (int(round(sample * scale / 4000)) for sample in full))
        result = board.feed(tiny)
        assert "CQ TEST 599" in result, (label, result)
        print(f"PASS: peak-{scale} {label} stream decodes [{result[0]}]", flush=True)

    board = Board(image, args.build_dir / "cw.elf")
    board.activate(3)
    gen = Colored(random.Random(11), 5)
    quiet_noise = array("h", (int(round(gen.next())) for _ in range(RATE * 8)))
    result = board.feed(quiet_noise)
    assert len(result) == 3 and result[0].startswith("WAIT "), result
    print("PASS: low-level noise stays silent", flush=True)

    board = Board(image, args.build_dir / "cw.elf")
    board.activate(2, 420)
    assert "CQ TEST" in board.feed(audio([("CQ TEST", 33)], 425, noise=320))
    gen = Colored(random.Random(81), 2600)
    result = board.feed(array("h", (int(round(gen.next())) for _ in range(RATE * 24))))
    assert result[0].startswith("WAIT ") and result[2:] == ["CQ TEST"], result
    board.set_pitch(780)
    board.call(board.poll)
    result = board.feed(audio([("K K DE K1K", 16)], 775, noise=120, jitter=0.09))
    assert result[2:] == ["CQ TEST", "K K DE K1K"] and abs(wpm_from(result) - 16) <= 2, result
    print("PASS: long noise clears old lock; clean -.- and 16 WPM recover at a new pitch", flush=True)

    for speed in (12, 40):
        board = Board(image, args.build_dir / "cw.elf")
        board.activate(2)
        short = audio([("CQ TEST", speed), ("DE W1AW", speed)], 600, pause_units=14)
        assert board.feed(short)[2:] == ["CQ TEST DE W1AW"]
        long_pause = array("h", [0]) * (RATE * 8)
        assert board.feed(long_pause)[2:] == ["CQ TEST DE W1AW"]
        sections = audio([("CQ TEST", speed), ("DE W1AW", speed), ("TEST END", speed)],
                         600, pause_units=17)
        expected = ["CQ TEST", "DE W1AW", "TEST END"]
        assert board.feed(sections)[2:] == expected
        assert board.feed(long_pause)[2:] == expected
        assert board.feed(long_pause)[2:] == expected
    print("PASS: short gaps stay on one row, long gaps retain the last three rows, sustained silence adds no blank rows")

    # Verify R2/R3/R4 + Pre-Swap + BACK on standalone CW:
    cw_elf = args.build_dir / "cw.elf"
    board = Board(image, cw_elf)
    # 1) Stock MODE popup untouched (0x03C51C not hooked, 0x1133 passes to stock)
    assert image[0x3C51C:0x3C520] == bytes.fromhex("06feffea")
    # Idle boot, then CW mode from a list frame with nonzero extension data.
    board.cpu.mem_write(UI, b"\x62")
    board.cpu.mem_write(UI + 0x13b, b"\x32")
    board.send_mode(0, 0, packet_type=0x62)
    board.refresh()
    assert "CLOSE" not in board.drawn
    selection = board.send_mode(2, 8, packet_type=0x62)
    board.refresh()
    assert "CLOSE" in board.drawn
    board.send_mode(2, 8, packet_type=0x60)
    board.refresh()
    assert "CLOSE" in board.drawn
    board.cpu.mem_write(board.frame + 419 * 800 * 2, b"\0\0")
    board.drawn.clear()
    board.call(0x60443AE8, end=0x60443AEC)
    assert "CLOSE" in board.drawn
    # 4) Hardware BACK (0x030A) swallows press+release and exits CW_DEC, clearing dock region
    board.commands.clear()
    back_pkt = bytes((0xE0, 1, 0x03, 0x0A, 0))
    board.cpu.mem_write(board.pcm, back_pkt)
    board.call(0x60412A38, board.pcm, 5, end=0x60412A3C)
    assert not board.commands
    board.refresh()
    assert "CLOSE" in board.drawn  # only release triggers exit
    board.cpu.mem_write(board.pcm, bytes((0xE0, 0, 0x03, 0x0A, 0)))
    board.call(0x60412A38, board.pcm, 5, end=0x60412A3C)
    assert not board.commands
    board.refresh()
    assert "CLOSE" not in board.drawn
    assert board.cpu.mem_read(board.frame + 419 * 800 * 2, 2) == b"\0\0"
    assert board.commands == [bytes((0xe8, 0xf8, 70, 84, 56, 2, selection, 0, 0))]
    board.commands.clear()
    # 5) SWR SCAN (UI[0x6C] == 0xED) blocks toggle and forwards BACK to MAIN
    board.cpu.mem_write(UI + 0x6C, b"\xED")
    board.send_mode(0, 9)
    board.refresh()
    assert "CLOSE" not in board.drawn
    board.cpu.mem_write(board.pcm, bytes((0xE0, 0, 0x03, 0x0A, 0)))
    board.call(0x60412A38, board.pcm, 5, end=0x60412A3C)
    assert board.commands == [bytes((0xE0, 0, 0x03, 0x0A, 0))]
    print("PASS: standalone CW common status, pre-swap wipe recovery, and BACK verified")


if __name__ == "__main__":
    main()
