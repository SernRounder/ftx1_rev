"""Exercise both modes and the shared audio arena in the packaged DISPLAY."""

import argparse
import wave
import struct
from array import array
from pathlib import Path

from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP

from test_cw import Board, RATE, audio
from test_ft8_arm import recording_16k
from test_ft8_menu import IMAGE_BASE, UI, read_display_sfl
from test_ft8_radio_dma import radio_layout, symbol, workspace_tx_phase


class CombinedBoard(Board):
    allocation = 0x60740000
    arena = 0x603D0880

    def __init__(self, image, elf):
        super().__init__(image, elf)
        from elftools.elf.elffile import ELFFile
        with elf.open("rb") as file:
            table = ELFFile(file).get_section_by_name(".symtab")
            self.cw_vfp = bool(table.get_symbol_by_name("cw_feed_vfp"))
            probe = table.get_symbol_by_name("ft8_fft_prepare") if (
                self.cw_vfp or table.get_symbol_by_name("ft8_vfp_candidate")) else None
        if probe:
            # This UI harness calls poll directly. Run the real worker probe first.
            from unicorn.arm_const import UC_ARM_REG_CPSR
            self.cpu.reg_write(UC_ARM_REG_CPSR, 0x1f)
            self.cpu.cpr_write(15, 0, 12, 0, 0, 0, False, IMAGE_BASE)
            self.cpu.cpr_write(15, 0, 1, 1, 2, 3, False, 3 << 10)
            self.cpu.mem_write(0x60402fa8, struct.pack("<I", 0xe12fff1e))
            self.cpu.mem_write(0x60402efc, struct.pack("<I", 0xe12fff1e))
            self.call(probe[0]["st_value"])
        self.stack = 0x606D8000
        self.radio, _, _, self.fields = radio_layout(elf)
        self.tasks = []
        self.frees = 0
        self.stock_frames = 0
        self.mode_redraws = 0
        self.text_at = {}
        self.commands = []
        self._cmd_seq = 0
        self.stubs[0x3BD3C] = self.stock_mode_draw
        self.stubs[0x450B4] = self.stock_capture
        self.stubs[0x14A1C] = self.send
        for offset, action in {0x7703C: 0, 0xBFA8C: 0, 0xBFAAC: 0,
                               0x7D9E0: self.allocation, 0x7D9EC: self.free}.items():
            address = IMAGE_BASE + offset
            self.stubs[offset] = action
            self.cpu.hook_add(UC_HOOK_CODE, self.stub, begin=address, end=address)
        self.cpu.mem_write(0x604C965C, struct.pack("<I", 0xE12FFF1E))
        self.cpu.mem_write(0x604B0BAC, struct.pack("<H", 0x4770))

    def send(self):
        ptr, size = (self.cpu.reg_read(reg) for reg in (UC_ARM_REG_R0, UC_ARM_REG_R1))
        self.commands.append(bytes(self.cpu.mem_read(ptr, size)))
        return 0

    def refresh(self):
        self.text_at.clear()
        super().refresh()

    def text(self):
        result = super().text()
        sp = self.cpu.reg_read(UC_ARM_REG_SP)
        self.text_at[self.word(sp + 12), self.word(sp + 16)] = self.drawn[-1]
        return result

    def create(self):
        params = self.cpu.reg_read(UC_ARM_REG_R1)
        self.tasks.append((self.word(params + 12), self.word(params + 16)))
        return len(self.tasks)

    def free(self):
        self.frees += 1
        return 0

    def stock_capture(self):
        self.stock_frames += 1
        return 0x1234

    def stock_mode_draw(self):
        self.mode_redraws += 1
        return 0

    def state(self, **values):
        for field, value in values.items():
            self.cpu.mem_write(self.radio + self.fields[field], struct.pack("<I", value))

    def tap(self, x, y, event):
        assert self.hit(x, y) == event
        self.touch(event)

    def choose(self, cw, pitch=None):
        self._cmd_seq += 1
        self.cpu.mem_write(UI, b"\x20" if pitch is not None else b"\0")
        self.cpu.mem_write(UI + 0x13B, b"\x00")
        self.cpu.mem_write(UI + 0x6C, b"\x00")
        self.cpu.mem_write(0x60939947, b"\x05")
        self.cpu.mem_write(0x6093994D, b"\x00")
        if pitch is not None:
            self.set_pitch(pitch)
        self.send_mode(2 if cw else 1, self._cmd_seq)
        self.refresh()

    def capture_one(self):
        self.cpu.mem_write(self.pcm, struct.pack("<HH768h", 768, 0, *([1] * 768)))
        before = self.stock_frames
        assert self.call(0x60445170, self.pcm, end=0x60445174) == 0x1234
        assert self.stock_frames == before + 1

    def type_ft8(self, text):
        if self.word(0x6052C674) >= 21:
            layout = 0
            for char in text:
                if char.isdigit() and layout == 0:
                    self.stock_key(layout, 0x83)
                    layout = 2
                elif char.isalpha() and layout == 2:
                    self.stock_key(layout, 0x82)
                    layout = 0
                self.stock_key(layout, {"<": 8, ">": 0x85}.get(char, ord(char)))
            return
        keys = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 <>"
        for char in text:
            index = keys.index(char)
            row, col = divmod(index, 10)
            self.tap(20 + col * 47 + 23, 128 + row * 70 + 35, 0x1230 + index)

    def stock_key(self, layout, code):
        table = self.cpu.mem_read(0x605373A0 + 500 * layout, 490)
        x, y, w, h, _ = next(rect for rect in struct.iter_unpack("<5H", table)
                             if rect[4] == 0x1200 + code)
        self.tap(x + w // 2, y + h // 2, 0x1300 + code)

    def receive_station_call(self, name):
        frame = bytearray(0x14d)
        frame[0] = 0x60
        frame[0x13e:0x148] = name.ljust(10, b" ")
        frame[-1] = sum(frame) & 0xff
        self.cpu.mem_write(self.pcm, bytes(frame))
        self.call(0x604C9D00, 0, self.pcm, len(frame), end=0x604C9D04)
        assert self.cpu.mem_read(self.pcm, len(frame)) == frame

    def receive_gps(self, sentence, *, accepted=True):
        # Feed the stock NMEA receiver, then run one stock GPS task iteration.
        checksum = 0
        for char in sentence:
            checksum ^= char
        wire = b"$" + sentence + f"*{checksum:02X}\r\n".encode()
        for char in wire:
            parsed = self.call(0x604122D0, char, 0x608A9108)
        assert parsed == accepted
        if not accepted:
            return
        # Initialize the numeric parser's locale for the digit-only fixture.
        self.cpu.mem_write(0x609EBDF4, struct.pack("<I", self.pcm + 0x100))
        self.cpu.mem_write(0x609EBDFC, struct.pack("<I", self.pcm))
        self.cpu.mem_write(self.pcm, b"\x04\0\0\0.")
        results = iter((0, 0xFFFFFFFF))
        hooks = []
        for offset, action in {0x77A50: 0, 0x7BC64: lambda: next(results)}.items():
            self.stubs[offset] = action
            address = IMAGE_BASE + offset
            hooks.append(self.cpu.hook_add(UC_HOOK_CODE, self.stub, begin=address, end=address))
        try:
            self.call(0x60411238)
        finally:
            for hook in hooks:
                self.cpu.hook_del(hook)
        self.call(0x60424D80, self.pcm, end=0x60424D84)
        assert self.cpu.mem_read(self.pcm, 1)[0] & 0x10

    def replay_ft8(self):
        poll = self.word(0x6052C670 + 28)
        samples = recording_16k(Path(__file__).resolve().parents[1] / "downloads/210703_133430.wav")
        if "audio_boundary" in self.fields:
            samples = array("h", [0]) * 116800 + samples + array("h", [0]) * 43200
        for offset in range(0, len(samples), 1600):
            frame = samples[offset:offset + 1600]
            self.clock = (offset + len(frame)) * 125 // 2
            self.cpu.mem_write(self.pcm, struct.pack("<HH", len(frame), 0) + frame.tobytes())
            assert self.call(0x60445170, self.pcm, end=0x60445174) == 0x1234
            self.call(poll, budget=200_000_000)
        self.refresh()
        if "audio_boundary" in self.fields:
            anchor = self.word(self.radio + self.fields["audio_boundary"])
            assert abs(anchor - 7300) < 700, anchor
            assert self.word(self.radio + self.fields["audio_votes"]) >= 2
            print("PASS: off-slot recording decoded through the RX DMA hook and supplied an audio timing reference")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--cw-weak-wav", type=Path,
                        help="Replay the 12 WPM -11 dB reference with 10 percent timing jitter")
    args = parser.parse_args()
    image = read_display_sfl(args.image)
    elf = args.build_dir / "ft8_rx.elf"
    from elftools.elf.elffile import ELFFile
    with elf.open("rb") as file:
        symbols = ELFFile(file).get_section_by_name(".symtab")
        recent_queue = bool(symbols.get_symbol_by_name("dequeue"))
        diagnostic = bool(symbols.get_symbol_by_name("ft8_profile_flush"))
    if recent_queue:
        recent = CombinedBoard(image, elf)
        recent.choose(cw=False)
        workspace = recent.word(symbol(elf, "workspace"))
        dequeue = symbol(elf, "dequeue")
        limit = 5 if diagnostic else 8
        def capture(sequence):
            recent.cpu.mem_write(recent.pcm, struct.pack("<HH32h", 32, 0, *([sequence] * 32)))
            recent.call(0x60445170, recent.pcm, end=0x60445174)

        for sequence in range(12):
            capture(sequence)
        assert (recent.word(workspace), recent.word(workspace + 4)) == (12, 12 - limit)
        borrowed = recent.call(dequeue, workspace)
        assert recent.word(borrowed + 4) == 12 - limit
        for sequence in range(12, 24):
            capture(sequence)
        assert recent.word(borrowed + 4) == 12 - limit
        assert struct.unpack("<h", recent.cpu.mem_read(borrowed + 24, 2))[0] == 12 - limit
        for sequence in range(24 - limit, 24):
            slot = recent.call(dequeue, workspace)
            assert recent.word(slot + 4) == sequence
            assert struct.unpack("<h", recent.cpu.mem_read(slot + 24, 2))[0] == sequence
        assert recent.call(dequeue, workspace) == 0

        # MAIN has just returned to RX but the worker has not handled the handoff yet.
        skip = workspace + workspace_tx_phase(elf, b"skip_rx")
        recent.cpu.mem_write(skip, struct.pack("<I", 1))
        recent.capture_one()
        poll = recent.word(0x6052C670 + 28)
        assert recent.call(poll) == 0
        assert recent.word(skip) == 0 and recent.word(workspace + 4) == 24
        slot = recent.call(dequeue, workspace)
        assert recent.word(slot + 4) == 24
        print("PASS: full queue retains newest PCM in order; first PCM survives TX-to-RX handoff")
    board = CombinedBoard(image, elf)
    stock_keyboard = board.word(0x6052C674) >= 21
    if stock_keyboard:
        board.cpu.mem_write(UI, b"\x50")
        board.cpu.mem_write(UI + 0x13b, b"\x32")
        board.cpu.mem_write(0x607C1F8C, bytes(board.cpu.mem_read(0x605373A0, 490)))
        assert board.hit(40, 120) == 0x1251
        board.touch(0x1251)
        assert len(board.commands) == 2 and all(p[2:4] == b"\x00Q" for p in board.commands)
        board.cpu.mem_write(UI, b"\0")
        print("PASS: stock keyboard hit and press/release reach stock MAIN transport")
    if board.word(0x6052C674) >= 19:
        profile = CombinedBoard(image, elf)
        profile.receive_station_call(b"w9xyz")
        profile.choose(cw=False)
        profile.tap(590, 450, 0x122c)
        profile.refresh()
        assert {"MY CALL", "W9XYZ"} <= set(profile.drawn)
        profile.tap(220, 173, 0x1224)
        profile.type_ft8("PM95>")
        profile.refresh()
        assert "CQ W9XYZ PM95" in profile.drawn
        north = b"GPRMC,123519,A,3535.3179,N,13943.8625,E,0.0,0.0,230394,,"
        south = b"GNRMC,123520,A,3725.3200,S,12205.5400,W,0.0,0.0,230394,,"
        profile.receive_gps(north)
        profile.refresh()
        assert "PM95uo" in profile.drawn, profile.drawn
        profile.receive_gps(south)
        profile.refresh()
        assert {"CF82wn", "CQ W9XYZ CF82"} <= set(profile.drawn), profile.drawn
        profile.receive_gps(south.replace(b",A,", b",V,"), accepted=False)
        profile.refresh()
        assert "PM95" in profile.drawn, profile.drawn
        profile.receive_gps(south)
        profile.clock += 3_001_000
        profile.refresh()
        assert "PM95" in profile.drawn
        profile.tap(220, 110, 0x1222)
        profile.type_ft8("<<<<<W1AW>")
        profile.receive_station_call(b"N0CALL")
        profile.refresh()
        assert "CQ W1AW PM95" in profile.drawn
        board.receive_station_call(b"FTX-1")
        print("PASS: stock MY CALL, NMEA north/east and south/west, invalid/stale fixes, and manual fallback")
    # R3: stock MODE popup and touch events are completely untouched.
    assert image[0x3C51C:0x3C520] == bytes.fromhex("06feffea")
    assert image[0xC6BD8:0xC6BDC] == bytes.fromhex("50fdffea")
    board.cpu.mem_write(UI, b"\x30")
    board.cpu.mem_write(UI + 0x13B, b"\x05\x01")
    board.call(0x6043C51C, UI, 1)
    board.refresh()
    assert not any(label in board.drawn for label in ("CUSTM", "FT8", "CW_DEC"))
    stock_touch_hits = []
    def on_stock_touch():
        stock_touch_hits.append(board.cpu.reg_read(UC_ARM_REG_R1))
        board.cpu.reg_write(UC_ARM_REG_SP, board.stack)
        return 0
    board.stubs[0x232E4] = on_stock_touch
    board.cpu.hook_add(UC_HOOK_CODE, board.stub, begin=0x604232E4, end=0x604232E4)
    for ev in (0x1133, 0x1136, 0x1137, 0x1139):
        board.call(0x604232E0, 1, ev)
    assert stock_touch_hits == [0x1133, 0x1136, 0x1137, 0x1139]

    # R2 + R4: ~B1:XX label expansion and 0x6040AA3C / 0x6041F3A4 bottom-bar labels.
    from unicorn.arm_const import UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_LR
    from test_ft8_menu import RETURN
    def read_cstr(addr):
        raw = bytes(board.cpu.mem_read(addr, 24))
        return raw.split(b"\0", 1)[0].decode("ascii")

    for btn_id, expected_label in ((0xE9, "SWR SCAN"), (0xEA, "BW"), (0xEB, "START"),
                                   (0xEC, "STOP"), (0xED, "EXIT"), (0xEE, "FT8"), (0xEF, "CW_DEC")):
        board.cpu.reg_write(UC_ARM_REG_R0, board.pcm)
        board.cpu.reg_write(UC_ARM_REG_R4, btn_id)
        board.cpu.reg_write(UC_ARM_REG_SP, board.stack)
        board.cpu.reg_write(UC_ARM_REG_LR, RETURN)
        board.cpu.emu_start(0x6041F3A4 | 1, RETURN, count=100_000)
        assert read_cstr(board.cpu.reg_read(UC_ARM_REG_R1)) == expected_label
    # Exercise ~B1:EE and ~B1:EF through 0x604C04CE -> 0x60424644 -> pop {r4, r5, r6, pc}.
    for btn_id, expected_padded in ((0xEE, b"FT8        "), (0xEF, b"CW_DEC     "), (0xE9, b"SWR SCAN   ")):
        dst = board.pcm + 0x200
        board.cpu.mem_write(dst, b"\0" * 16)
        board.cpu.mem_write(board.pcm + 0x100, f"~B1:{btn_id:02X}     ".encode("ascii"))
        board.cpu.mem_write(board.stack - 16, struct.pack("<4I", 0, 0, 0, RETURN))
        board.cpu.reg_write(UC_ARM_REG_R0, dst)
        board.cpu.reg_write(UC_ARM_REG_R1, board.pcm + 0x100)
        board.cpu.reg_write(UC_ARM_REG_R2, 11)
        board.cpu.reg_write(UC_ARM_REG_R4, btn_id)
        board.cpu.reg_write(UC_ARM_REG_R5, dst)
        board.cpu.reg_write(UC_ARM_REG_R6, 2)
        board.cpu.reg_write(UC_ARM_REG_SP, board.stack - 16)
        board.cpu.emu_start(0x604C04CE | 1, RETURN, count=200_000)
        assert bytes(board.cpu.mem_read(dst, 11)) == expected_padded

    # Exercise all three common status frames, including an active first report.
    trig = CombinedBoard(image, elf)
    trig.wire_status = True
    trig.cpu.mem_write(UI, b"\x62")
    trig.cpu.mem_write(UI + 0x13b, b"\x32")
    trig.cpu.mem_write(UI + 0xA3 + 0x4C, b"\x03")
    trig.set_pitch(600)
    trig.send_mode(1, 12, packet_type=0x62, spa=1)
    trig.refresh()
    assert {"FT8 DECODE", "BACK"} <= set(trig.drawn)
    assert trig.word(trig.radio + trig.fields["tx_power_tenths"]) == 370
    trig.send_mode(1, 12, packet_type=0x20)
    trig.refresh()
    assert {"FT8 DECODE", "BACK"} <= set(trig.drawn)

    # Toggle CW_DEC while FT8 is active -> stops FT8, opens CW_DEC, Layer 0 softkeys stay clickable.
    stock_hit_sentinel = 0x604C61E0
    trig.stubs[stock_hit_sentinel - IMAGE_BASE] = 0x4567
    sh = trig.cpu.hook_add(UC_HOOK_CODE, trig.stub, begin=stock_hit_sentinel, end=stock_hit_sentinel)
    trig.send_mode(2, 13, packet_type=0x60)
    trig.refresh()
    assert "CLOSE" in trig.drawn and "FT8 DECODE" not in trig.drawn
    assert trig.hit(40, 450) == 0x4567  # Layer 0 custom button stays clickable
    trig.cpu.hook_del(sh)

    # Toggle FT8 while CW_DEC is active -> stops CW_DEC, opens FT8.
    trig.send_mode(1, 14)
    trig.refresh()
    assert "FT8 DECODE" in trig.drawn and "CLOSE" not in trig.drawn

    # SWR SCAN (UI[0x6C] == 0xED) ignores toggles and forwards BACK to 0x60414A1C.
    trig.cpu.mem_write(UI + 0x6C, b"\xED")
    trig.drawn.clear()
    trig.call(0x60443AE8, end=0x60443AEC)
    assert not trig.drawn
    trig.send_mode(0, 15, packet_type=0x62)
    trig.refresh()
    assert not trig.drawn
    trig.commands.clear()
    trig.cpu.mem_write(trig.pcm, bytes((0xE0, 0, 0x03, 0x0A, 0)))
    trig.call(0x60412A38, trig.pcm, 5, end=0x60412A3C)
    assert trig.commands == [bytes((0xE0, 0, 0x03, 0x0A, 0))]

    # Pre-swap zero-flicker on 0x60442758 wipe + dual-buffer 3 & 4 clean exit + hardware BACK unwind.
    trig.cpu.mem_write(UI + 0x6C, b"\x00")
    buf3, buf4 = 0x60232800, 0x602EE000
    trig.cpu.mem_write(0x607C4BB0, struct.pack("<I", 3))
    trig.stubs[0x448B8] = lambda: buf3 if trig.cpu.reg_read(UC_ARM_REG_R0) == 3 else buf4
    def fill_and_paint():
        frame_ptr = trig.cpu.reg_read(UC_ARM_REG_R0)
        color = trig.cpu.reg_read(UC_ARM_REG_R1) & 0xFFFF
        y = trig.cpu.reg_read(UC_ARM_REG_R2)
        x = trig.cpu.reg_read(UC_ARM_REG_R3)
        w = trig.word(trig.cpu.reg_read(UC_ARM_REG_SP))
        h = trig.word(trig.cpu.reg_read(UC_ARM_REG_SP) + 4)
        trig.fills.append((x, y, w, h))
        if w and h and frame_ptr in (buf3, buf4):
            pixel = struct.pack("<H", color)
            trig.cpu.mem_write(frame_ptr + (y * 800 + x) * 2, pixel)
            trig.cpu.mem_write(frame_ptr + ((y + h - 1) * 800 + x) * 2, pixel)
        return 0
    trig.stubs[0x625A0] = fill_and_paint
    list_redraws = []
    def restore_list():
        assert trig.cpu.reg_read(UC_ARM_REG_R2) == 1
        assert trig.cpu.mem_read(buf3 + 479 * 800 * 2, 2) == b"\0\0"
        assert trig.cpu.mem_read(buf4 + 479 * 800 * 2, 2) == b"\0\0"
        list_redraws.append(1)
        return 0
    trig.stubs[0x2BB54] = restore_list
    trig.refresh()
    assert not trig.drawn
    ft8_state = trig.send_mode(1, 16, packet_type=0x62)
    trig.refresh()
    assert "FT8 DECODE" in trig.drawn
    trig.tap(590, 450, 0x122c)  # -> Config
    trig.refresh()
    assert "FT8 CONFIG" in trig.drawn
    trig.tap(220, 110, 0x1222)  # -> Keyboard
    trig.refresh()
    assert "MY CALL  |" in trig.drawn
    # Simulate 0x60442758 LAYER wipe while Keyboard, Config, Dock are active:
    for expected_text, sentinel_y in (("MY CALL  |", 479),):
        trig.cpu.mem_write(buf3, b"\0" * (800 * 480 * 2))
        trig.drawn.clear()
        trig.call(0x60443AE8, end=0x60443AEC)
        assert expected_text in trig.drawn
        assert trig.cpu.mem_read(buf3 + sentinel_y * 800 * 2, 2) != b"\0\0"
    # Hardware BACK press (1) swallowed without unwinding; release (0) unwinds Keyboard -> Config -> Dock -> Exit.
    trig.commands.clear()
    trig.cpu.mem_write(trig.pcm, bytes((0xE0, 1, 0x03, 0x0A, 0)))
    trig.call(0x60412A38, trig.pcm, 5, end=0x60412A3C)
    trig.refresh()
    assert not trig.drawn and not trig.commands
    assert trig.cpu.mem_read(buf3 + 479 * 800 * 2, 2) != b"\0\0"
    trig.cpu.mem_write(trig.pcm, bytes((0xE0, 0, 0x03, 0x0A, 0)))
    trig.call(0x60412A38, trig.pcm, 5, end=0x60412A3C)
    trig.refresh()
    assert "FT8 CONFIG" in trig.drawn and not trig.commands
    # Wipe Config and verify zero-flicker recovery at 0x043AE8:
    trig.cpu.mem_write(buf3, b"\0" * (800 * 480 * 2))
    trig.drawn.clear()
    trig.call(0x60443AE8, end=0x60443AEC)
    assert "FT8 CONFIG" in trig.drawn
    # BACK Config -> Dock:
    trig.cpu.mem_write(trig.pcm, bytes((0xE0, 0, 0x03, 0x0A, 0)))
    trig.call(0x60412A38, trig.pcm, 5, end=0x60412A3C)
    trig.refresh()
    assert "FT8 DECODE" in trig.drawn and not trig.commands
    # Wipe Dock and verify zero-flicker recovery at 0x043AE8:
    trig.cpu.mem_write(buf3, b"\0" * (800 * 480 * 2))
    trig.drawn.clear()
    trig.call(0x60443AE8, end=0x60443AEC)
    assert "FT8 DECODE" in trig.drawn
    # Seed buffer 4 too, then BACK Dock -> Exit FT8 clears BOTH buffers 3 and 4!
    trig.cpu.mem_write(buf4 + 479 * 800 * 2, b"\xff\xff")
    trig.cpu.mem_write(trig.pcm, bytes((0xE0, 0, 0x03, 0x0A, 0)))
    trig.call(0x60412A38, trig.pcm, 5, end=0x60412A3C)
    trig.refresh()
    close = bytes((0xe8, 0xf8, 70, 84, 56, 2, ft8_state, 0, 0))
    assert not trig.drawn and trig.commands == [close]
    assert list_redraws == [1]
    assert trig.cpu.mem_read(buf3 + 479 * 800 * 2, 2) == b"\0\0"
    assert trig.cpu.mem_read(buf4 + 479 * 800 * 2, 2) == b"\0\0"
    # A repeated report cannot reopen the page. Retry if the close was lost.
    trig.send_mode(1, 16, packet_type=0x62)
    trig.clock += 250000
    trig.refresh()
    assert not trig.drawn and trig.commands == [close, close]
    trig.send_mode(0, 17, packet_type=0x62)
    trig.clock += 250000
    trig.refresh()
    assert not trig.drawn and trig.commands == [close, close]
    trig.commands.clear()
    # CW_DEC Dock BACK exit clears dock region on both buffers 3 and 4 + auto-closes on SWR SCAN:
    cw_state = trig.send_mode(2, 18, packet_type=0x62)
    trig.refresh()
    assert "CLOSE" in trig.drawn
    trig.cpu.mem_write(buf4 + 419 * 800 * 2, b"\xff\xff")
    trig.cpu.mem_write(trig.pcm, bytes((0xE0, 0, 0x03, 0x0A, 0)))
    trig.call(0x60412A38, trig.pcm, 5, end=0x60412A3C)
    trig.refresh()
    assert not trig.drawn and trig.commands == [bytes((0xe8, 0xf8, 70, 84, 56, 2, cw_state, 0, 0))]
    trig.commands.clear()
    assert trig.cpu.mem_read(buf3 + 419 * 800 * 2, 2) == b"\0\0"
    assert trig.cpu.mem_read(buf4 + 419 * 800 * 2, 2) == b"\0\0"
    # Stock popup (UI[0] == 0x30) forwards BACK to 0x60414A1C even if CW_DEC was open:
    trig.send_mode(2, 19)
    trig.refresh()
    assert "CLOSE" in trig.drawn
    trig.cpu.mem_write(UI, b"\x30")
    trig.cpu.mem_write(trig.pcm, bytes((0xE0, 0, 0x03, 0x0A, 0)))
    trig.call(0x60412A38, trig.pcm, 5, end=0x60412A3C)
    assert trig.commands == [bytes((0xE0, 0, 0x03, 0x0A, 0))]
    # SWR SCAN opening while CW_DEC active auto-closes CW_DEC:
    trig.cpu.mem_write(UI, b"\x20")
    trig.cpu.mem_write(UI + 0x6C, b"\xED")
    trig.send_mode(0, 20)
    trig.refresh()
    trig.cpu.mem_write(UI + 0x6C, b"\x00")
    trig.refresh()
    assert "CLOSE" not in trig.drawn
    # Readback can carry the next selection before the old SWR UI is drained.
    trig.cpu.mem_write(UI + 0x6C, b"\xED")
    trig.send_mode(1, 21, packet_type=0x62)
    trig.refresh()
    assert not trig.drawn
    trig.cpu.mem_write(UI + 0x6C, b"\x00")
    trig.refresh()
    assert "FT8 DECODE" in trig.drawn
    # Both edges must stay with the press owner across a stock popup transition.
    trig.commands.clear()
    back_press = bytes((0xE0, 1, 0x03, 0x0A, 0))
    back_release = bytes((0xE0, 0, 0x03, 0x0A, 0))
    def hardware_back(packet):
        trig.cpu.mem_write(trig.pcm, packet)
        trig.call(0x60412A38, trig.pcm, 5, end=0x60412A3C)
    hardware_back(back_press)
    trig.cpu.mem_write(UI, b"\x30")
    hardware_back(back_release)
    trig.refresh()
    assert len(trig.commands) == 1 and trig.commands[0][5:7] == b"\x02\xaa"
    trig.commands.clear()
    hardware_back(back_press)
    trig.cpu.mem_write(UI, b"\x20")
    trig.send_mode(2, 22)
    trig.refresh()
    hardware_back(back_release)
    trig.refresh()
    assert trig.commands == [back_press, back_release] and "CLOSE" in trig.drawn
    print("PASS: custom labels, 0x20/0x60/0x62, checksums, pre-swap recovery, clean BACK, close retry and SWR mutual exclusion")

    board.cpu.mem_write(UI + 0xA3 + 0x4C, b"\x03")

    board.choose(cw=True, pitch=620)
    board.call(board.poll)
    sections = [("CQ TEST", 28), ("DE W1AW", 28), ("TEST END", 28)]
    signal = audio(sections, 625, noise=450, jitter=0.08, pause_units=18)
    expected = [text for text, _ in sections]
    assert board.feed(signal)[2:] == expected, board.drawn
    assert board.feed(array("h", [0]) * (RATE * 4))[2:] == expected
    assert board.tasks == [(6, 32768)]
    board.tap(765, 413, 0x1138)
    board.refresh()
    assert "CLOSE" not in board.drawn

    if board.cw_vfp:
        board.choose(cw=True, pitch=700)
        board.call(board.poll)
        signal = audio([("CQ TEST 599", 20)], 699, noise=240)
        low_pcm = array("h", (round(sample / 560) for sample in signal))
        assert max(map(abs, low_pcm)) <= 8
        assert board.feed(low_pcm)[2:] == ["CQ TEST 599"], board.drawn
        board.tap(765, 413, 0x1138)
        board.refresh()
        print("PASS: CW hardware double precision decodes 699 Hz PCM with peaks at eight counts")

        board.choose(cw=True, pitch=700)
        board.call(board.poll)
        # Start sampling on the first dot, before the 60 ms detector can lock.
        onset = audio([("V TEST 599", 40)], 700, noise=240)[RATE // 5:]
        assert board.feed(onset)[2:] == ["V TEST 599"], board.drawn
        board.tap(765, 413, 0x1138)
        board.refresh()
        print("PASS: CW replays the first dot and joins live decoding without duplicating a character")

        board.choose(cw=True)
        board.call(board.poll)
        signal = audio([("K TEST 599", 20)], 1000)
        assert board.feed(signal)[:2] == ["CW-U/L", "CLOSE"], board.drawn
        board.cpu.mem_write(UI, b"\x20")
        board.cpu.mem_write(UI + 0x129, b"\x4c")
        board.call(board.poll)
        assert board.feed(signal)[:2] == ["CW-U/L", "CLOSE"], board.drawn
        board.set_pitch(700)
        board.call(board.poll)
        result = board.feed(signal)
        assert result[0].startswith("WAIT 700 ") and len(result) == 3, result
        # Use the other VFO and the upper valid pitch value. Leave a
        # different pitch on the first side to catch an offset mix-up.
        board.stubs[0x25838] = 0
        board.cpu.hook_add(UC_HOOK_CODE, board.stub, begin=0x60425838, end=0x60425838)
        board.cpu.mem_write(UI + 0xA3, b"\x03")
        board.set_pitch(1050, side=0)
        board.call(board.poll)
        wanted = audio([("K TEST 599", 20)], 1050, noise=240)
        other = audio([("VVV VVV VVV", 17)], 700)
        other.extend([0] * max(0, len(wanted) - len(other)))
        signal = array("h", (x + 2 * y for x, y in zip(wanted, other)))
        result = board.feed(signal)
        assert " 1050 " in result[0] and result[2:] == ["K TEST 599"], result
        board.tap(765, 413, 0x1138)
        board.refresh()
        board.stubs[0x25838] = 1
        print("PASS: CW requires valid MAIN status, checks both VFOs, and rejects a stronger off-pitch tone")

        if args.cw_weak_wav:
            board.choose(cw=True, pitch=600)
            board.call(board.poll)
            with wave.open(str(args.cw_weak_wav), "rb") as wav:
                assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (RATE, 1, 2)
                result = board.feed(array("h", wav.readframes(wav.getnframes())))
            assert result[2:] == ["CQ TEST DE K1K K K 599"], result
            board.tap(765, 413, 0x1138)
            board.refresh()
            print("PASS: fixed-pitch VFP recovers the -11 dB reference at 12 WPM")

    board.choose(cw=False)
    assert {"BACK", "FT8 DECODE", "SETUP", "STOP"} <= set(board.drawn)
    assert board.cpu.mem_read(board.frame, 2) == bytes(2)
    assert (0, 235, 800, 185) in board.fills
    assert all(y >= 235 and y + h <= 480 for _, y, _, h in board.fills)
    assert board.hit(0, 479) == 0x1134 and board.hit(799, 479) == 0x1221
    assert board.hit(24, 260) == 0x1135
    for row in range(6):
        assert board.hit(30 + row // 3 * 400, 270 + row % 3 * 32) == 0x1200 + row
    assert any("SET TIME OFFSET" in line for line in board.drawn)
    board.tap(590, 450, 0x122c)
    board.refresh()
    assert {"RECENT QSOs (UTC)", "NO LOGGED QSOs", "CQ [MY] [GRID]"} <= set(board.drawn)
    assert (0, 0, 800, 480) in board.fills
    assert board.hit(525, 108) == 0x1135
    assert board.hit(425, 383) == 0x1216
    assert board.hit(525, 383) == 0x122d
    history = b"".join(
        f"<CALL:5>K{i}ABC<QSO_DATE:8>20261115<TIME_ON:6>12{i:02d}00<MODE:3>FT8<eor>\r\n".encode()
        for i in (7, 2, 5, 4, 5, 1, 6, 3)
    ) + b"<CALL:5>K8ABC<QSO_DATE:8>20261115<TIME_ON:6>120800"
    position = 0

    def read_history():
        nonlocal position
        chunk = history[position:position + board.cpu.reg_read(UC_ARM_REG_R2)]
        board.cpu.mem_write(board.cpu.reg_read(UC_ARM_REG_R0), chunk)
        position += len(chunk)
        return len(chunk)

    for addr, action in ((0x6995C, board.pcm), (0x6A8F8, read_history), (0x69E90, 0)):
        board.stubs[addr] = action
        board.cpu.hook_add(UC_HOOK_CODE, board.stub, begin=IMAGE_BASE + addr, end=IMAGE_BASE + addr)
    load_worked = symbol(elf, "load_worked_step")
    board.call(load_worked)
    board.call(load_worked)
    board.refresh()
    for row, i in enumerate(range(7, 1, -1)):
        assert board.text_at[406, 108 + row * 44] == f"K{i}ABC"
        assert board.text_at[770, 108 + row * 44] == f"2026-11-15 12:{i:02d}:00"
    assert {"K1ABC", "K8ABC", "NO LOGGED QSOs"}.isdisjoint(board.drawn)
    print("PASS: SETUP shows six newest complete SD contacts in UTC, with inert history rows")
    local = bytearray((0x26, 0x11, 0x15, 0, 0x18, 0x03, 0x04))
    clock_writes = []

    def read_local():
        board.cpu.mem_write(board.cpu.reg_read(UC_ARM_REG_R0), bytes(local))
        return 0

    def write_local():
        raw = board.cpu.mem_read(board.cpu.reg_read(UC_ARM_REG_R0), 7)
        local[:] = raw
        clock_writes.append(bytes(raw[:3] + raw[4:]))
        return 0

    for addr, action in ((0x135D4, read_local), (0x13640, read_local), (0x13514, write_local)):
        board.stubs[addr] = action
        board.cpu.hook_add(UC_HOOK_CODE, board.stub, begin=IMAGE_BASE + addr, end=IMAGE_BASE + addr)
    board.cpu.mem_write(0x607C01C4, b"\x28")  # Stock UTC+08:00 entry.
    board.tap(450, 447, 0x122e)
    board.refresh()
    assert "YYYYMMDDHHMMSS  20261115180304|" in board.drawn
    for digits in ("20230229130745", "20240229130745"):
        for _ in range(14):
            board.stock_key(2, 8)
        for digit in digits:
            board.stock_key(2, ord(digit))
        board.stock_key(2, 0x85)
        assert len(clock_writes) == (digits[3] == "4"), clock_writes
    assert clock_writes[-1] == bytes.fromhex("24 02 29 13 07 45")
    # A stock DATE&TIME write is still reflected the next time the FT8 editor opens.
    board.cpu.mem_write(board.pcm, bytes((0, 0, 26, 12, 31, 14, 55)))
    board.call(0x60441990, board.pcm)
    board.tap(450, 447, 0x122e)
    board.refresh()
    assert "YYYYMMDDHHMMSS  20261231145500|" in board.drawn
    board.cpu.mem_write(0x607C01C0, b"\x01")  # Stock GPS TIME SET=AUTO.
    board.receive_gps(b"GPRMC,234501,A,3535.3179,N,13943.8625,E,0.0,0.0,290224,,")
    assert clock_writes[-1] == bytes.fromhex("24 03 01 07 45 01"), clock_writes
    board.stock_key(2, 0x85)
    assert len(clock_writes) == 3  # A fix received while editing also prevents manual save.
    board.tap(728, 28, 0x1134)
    board.refresh()
    assert "GPS TIME" in board.drawn and board.hit(450, 447) == 0x1135
    board.cpu.mem_write(0x607C01C0, b"\x00")
    assert board.hit(450, 447) == 0x122e
    board.cpu.mem_write(0x607C01A8, b"\x00")
    # The time-offset regression below supplies its own RTC handlers.
    for addr in (0x135D4, 0x13640, 0x13514):
        board.stubs[addr] = 0
    print("PASS: FT8 and stock writers share RTC; GPS AUTO applies stock timezone across midnight")
    assert board.hit(587, 445) == 0x1220
    assert board.hit(713, 445) == 0x1221
    board.tap(220, 110, 0x1222)
    stock_table = bytes(board.cpu.mem_read(0x607C1F8C, 490))
    board.refresh()
    assert ("MY CALL  |" if stock_keyboard else "MY CALL: _") in board.drawn
    if stock_keyboard:
        assert bytes(board.cpu.mem_read(0x607C1F8C, 490)) == stock_table
        board.stock_key(0, ord("A"))
        board.stock_key(0, 0x81)
        board.stock_key(1, 0x8A)  # Visible A selects uppercase letters.
        board.stock_key(0, 0x83)  # Visible 123/#%^ selects digits and symbols.
        board.stock_key(2, ord("5"))
        board.stock_key(2, ord("/"))
        board.stock_key(2, 0x82)  # ABC returns to the letter page.
        board.stock_key(0, ord("B"))
    else:
        board.tap(43, 160, 0x1230)
    board.refresh()
    assert ("MY CALL  A5/B|" if stock_keyboard else "MY CALL: A") in board.drawn
    board.tap(728, 28, 0x1134)
    board.refresh()
    assert "FT8 CONFIG" in board.drawn and "MY CALL: A" not in board.drawn
    assert board.tasks == [(6, 32768), (5, 4096)]
    # The CW worker can finish a preempted block after CLOSE invalidates its session.
    gate = symbol(args.build_dir / "ft8_rx.elf", "capture_enabled")
    board.cpu.mem_write(gate, struct.pack("<I", 1))
    board.tap(220, 173, 0x1224)
    board.type_ft8("PM95>")
    board.tap(728, 28, 0x1134)
    board.replay_ft8()
    live_elf = "ft8_rx.elf" if board.word(0x6052C674) >= 28 else "ft8_radio.elf"
    view = board.word(symbol(args.build_dir / live_elf, "live_view"))
    if board.word(0x6052C674) >= 24:
        poll = board.word(0x6052C670 + 28)
        assert board.word(view + 24) > 8 and "RARE" in board.drawn
        board.tap(460, 450, 0x1227)
        board.call(poll)
        board.refresh()
        assert board.word(view + 28) >> 2 == 1
        board.tap(330, 450, 0x1226)
        board.call(poll)
        board.refresh()
        assert board.word(view + 28) == 1
        for _ in range(2):
            board.tap(330, 450, 0x1226)
            board.call(poll)
            board.refresh()
        assert board.word(view + 28) == 0 and "RARE" in board.drawn

        written = []
        rtc = bytes((0x26, 0x11, 0x13, 0x05, 0, 0, 0))

        def read_rtc():
            board.cpu.mem_write(board.cpu.reg_read(UC_ARM_REG_R0), rtc)
            return 0

        def write_rtc():
            written.append(bytes(board.cpu.mem_read(board.cpu.reg_read(UC_ARM_REG_R0), 7)))
            return 0

        for offset, action in ((0x135D4, read_rtc), (0x13514, write_rtc)):
            board.stubs[offset] = action
            board.cpu.hook_add(UC_HOOK_CODE, board.stub, begin=IMAGE_BASE + offset,
                               end=IMAGE_BASE + offset)
        board.tap(590, 450, 0x122c)
        board.tap(220, 237, 0x1228)
        timing = board.word(0x6052C674) >= 32
        for digit in ("-1.8" if timing else "235959"):
            board.stock_key(2, ord(digit))
        board.stock_key(2, 0x85)
        if timing:
            assert not written
            board.refresh()
            assert {"-1.8", "00/30"} <= set(board.drawn)
            board.tap(220, 269, 0x122b)
            board.refresh()
            assert "15/45" in board.drawn
        else:
            assert written == [rtc[:4] + bytes((0x23, 0x59, 0x59))]
            board.refresh()
        assert "ON" in board.drawn
        board.tap(220, 301, 0x1229)
        board.refresh()
        assert "OFF" in board.drawn
        board.tap(220, 301, 0x1229)
        board.refresh()
        assert "ON" in board.drawn
        board.tap(220, 301, 0x1229)  # Leave manual TX enabled for the next checks.
        board.refresh()
        assert "OFF" in board.drawn
        board.tap(220, 364, 0x1240)
        board.stock_key(2, ord("0"))
        board.stock_key(2, 0x85)
        board.refresh()
        assert board.text_at[359, 359] == "0"
        board.tap(220, 396, 0x1241)
        board.stock_key(2, ord("0"))
        board.stock_key(2, 0x85)
        board.refresh()
        assert any("0|" in text and text.startswith("CQ ROUNDS") for text in board.drawn)
        board.stock_key(2, 8)
        for digit in "-1":
            board.stock_key(2, ord(digit))
        board.stock_key(2, 0x85)
        board.refresh()
        assert "-1 (CONTINUOUS)" in board.drawn
        board.tap(728, 28, 0x1134)
        board.refresh()
        print("PASS: page/sort, time editor, default-on AUTO, and numeric retry/CQ settings")
    messages = ["K1JT HA0DU KN07", "XE2X HA2NP RR73"]
    if "audio_boundary" not in board.fields:
        messages.append("CQ F5RXL IN94")
    for message in messages:
        assert any(message in line for line in board.drawn), (message, board.drawn)
    board.state(status_report=0x80)
    board.tap(195, 445, 0x1220)  # placeholders cannot arm
    board.call(board.word(0x6052C670 + 28))
    board.refresh()
    assert not any("ARMED" in line for line in board.drawn)
    board.tap(590, 450, 0x122c)
    board.tap(220, 110, 0x1222)
    board.type_ft8("W9XYZ>")
    board.tap(220, 173, 0x1224)
    board.type_ft8("PM95>")
    board.refresh()
    assert {"PM95", "CQ W9XYZ PM95"} <= set(board.drawn)
    assert "1000" in board.drawn
    board.tap(220, 205, 0x1225)
    for digit in "150":
        board.stock_key(2, ord(digit))
    board.stock_key(2, 0x85)
    board.refresh()
    assert "TX Hz  150|" in board.drawn  # Out of range stays in the editor.
    board.stock_key(2, ord("0"))
    board.stock_key(2, 0x85)
    board.refresh()
    assert "1500" in board.drawn
    board.tap(728, 28, 0x1134)
    board.refresh()
    assert board.text_at[140, 239] == "00/30" and board.text_at[540, 239] == "15/45"
    assert board.text_at[606, 239] == "TX"
    rows_offset = workspace_tx_phase(args.build_dir / live_elf, b"rows")
    distances, selected = set(), None
    slots = workspace_tx_phase(args.build_dir / live_elf, b"slot_count")
    for row in range(6):
        if row % 3 >= board.cpu.mem_read(view + slots + row // 3, 1)[0]:
            continue
        data = board.cpu.mem_read(view + rows_offset + row * 44, 44)
        message = bytes(data[:35]).split(b"\0", 1)[0].decode("ascii")
        snr, freq = struct.unpack_from("<bH", data, 35)
        km, = struct.unpack_from("<H", data, 42)
        x = row // 3 * 400
        y = 270 + row % 3 * 32
        distance = "--" if km == 0xffff else f"~{km}"
        distances.add(km != 0xffff)
        assert board.text_at[x + 9, y] == message
        assert [board.text_at[x + off, y + 16] for off in (287, 326, 390)] == [
            distance, f"{snr:+03d}", str(freq),
        ]
        if selected is None and message not in ("CQ", ""):
            sender = data[41]
            if sender:
                selected = row, snr, message[sender - 1:].split()[0]
    assert True in distances
    assert selected is not None
    row, snr, call = selected
    board.tap(40 + row // 3 * 400, 270 + row % 3 * 32, 0x1200 + row)
    board.tap(590, 450, 0x122c)
    board.refresh()
    report = f"{snr:+03d}"
    for message in (f"{call} W9XYZ PM95", f"{call} W9XYZ {report}", f"{call} W9XYZ R{report}",
                    f"{call} W9XYZ RRR", f"{call} W9XYZ 73", "CQ W9XYZ PM95"):
        assert message in board.drawn
        board.tap(525, 383, 0x122d)
        board.refresh()
    board.tap(587, 445, 0x1220)
    board.call(board.word(0x6052C670 + 28))
    board.refresh()
    assert board.word(view + 20) == 1
    stage1 = args.build_dir / live_elf
    workspace = board.word(symbol(stage1, "workspace"))
    assert board.word(workspace + workspace_tx_phase(stage1, b"tx_hz")) == 1500
    board.tap(713, 445, 0x1221)
    board.call(board.word(0x6052C670 + 28))
    print("PASS: per-row Hz, distance, dB, correct sender, and explicit TX NEXT")
    if board.word(0x606C2FC0 + 4) >= 27:
        board.refresh()
        assert "FULL AUTO" in board.drawn
        board.tap(220, 333, 0x122a)
        board.refresh()
        assert "END" in board.drawn
        board.tap(728, 28, 0x1134)
        board.refresh()
        assert {"END AUTO", "QSO 0  Q 0  CQ INF", "NEXT CQ"} <= set(board.drawn)
        board.tap(713, 445, 0x1221)
        print("PASS: FULL AUTO button and live queue preview appear in the combined UI")
    reserved = bytes([0xA5]) * 0x4000
    board.cpu.mem_write(board.arena, reserved)
    board.capture_one()
    board.call(board.poll)
    assert board.cpu.mem_read(board.arena, len(reserved)) == reserved

    # Simulate leaving FT8 while the adapter is still returning a DMA block.
    board.state(parked=0, lease=4, borrowed=0x603D5880)
    board.cpu.mem_write(board.frame + 800 * 480 * 2 - 2, b"\x86\x31\x75\x42")
    board.tap(65, 450, 0x1134)
    board.refresh()
    assert board.cpu.mem_read(board.frame + 800 * 480 * 2 - 2, 4) == b"\0\0\x75\x42"
    board.choose(cw=True, pitch=600)
    assert "CW OFFLINE" in board.drawn and board.frees == 0, board.drawn
    board.capture_one()
    board.call(board.poll)
    assert board.cpu.mem_read(board.arena, len(reserved)) == reserved

    board.state(parked=1, lease=0, borrowed=0)
    board.refresh()
    assert board.frees == 1
    board.call(board.poll)
    assert board.feed(audio([("CQ TEST 599", 20)], 600, noise=450))[2:] == ["CQ TEST 599"]
    assert board.tasks == [(6, 32768), (5, 4096)]
    print("PASS: dual-column FT8 hit targets, keyboard BACK, overlay bounds, CW rows, and buffer handoff")

    if board.word(0x6052C674) >= 15:
        board.tap(765, 413, 0x1138)
        board.refresh()
        board.choose(cw=False)
        board.state(tx_wait_s=12, **({"status_report": 0x80} if board.word(0x6052C674) >= 17
                                   else {"status_seen": 1}))
        board.capture_one()
        live = 0x6052C670
        poll, arm = board.word(live + 28), board.word(live + 44)
        board.call(poll, budget=200_000_000)
        board.cpu.mem_write(board.pcm, b"CQ W9XYZ FN31\0")
        assert board.call(arm, board.pcm, 1000)
        board.call(poll)
        board.refresh()
        assert any("ARMED 12s" in line for line in board.drawn), board.drawn
        board.state(tx_wait_s=11)
        board.refresh()
        assert any("ARMED 11s" in line for line in board.drawn), board.drawn
        board.clock += (32 if board.word(0x6052C674) >= 32 else 17) * 1_000_000
        board.call(poll)
        board.refresh()
        assert any(" NO SLOT" in line for line in board.drawn), board.drawn
        print("PASS: armed countdown repaints independently of PCM, and the menu shows NO SLOT")

    # Feed a real frame in the RX window immediately before an armed TX.
    # Advance the emulated timer inside candidate decoding to exercise the
    # same deadline checks that run when the worker is preempted on-device.
    timed = CombinedBoard(image, elf)
    timed.stubs[0x797C8] = 0
    timed.cpu.hook_add(UC_HOOK_CODE, timed.stub, begin=0x604797C8, end=0x604797C8)
    timed.receive_station_call(b"N1JFU")
    timed.choose(cw=False)
    if diagnostic:
        profile_flush = symbol(elf, "ft8_profile_flush")
        profile_writes = []

        def profile_open():
            addr = timed.cpu.reg_read(UC_ARM_REG_R0)
            path = b"I:\\FTX-1\\FT8TIME.BIN\0"
            assert timed.cpu.mem_read(addr, len(path)) == path
            return 1

        def profile_write():
            addr = timed.cpu.reg_read(UC_ARM_REG_R0)
            size = timed.cpu.reg_read(UC_ARM_REG_R1)
            count = timed.cpu.reg_read(UC_ARM_REG_R2)
            assert size == 12 and count > 0
            profile_writes.extend(struct.iter_unpack("<IIHH", timed.cpu.mem_read(addr, size * count)))
            return count

        for addr, function in ((0x6995C, profile_open), (0x6B51C, profile_write), (0x69E90, 0)):
            timed.stubs[addr] = function
            timed.cpu.hook_add(UC_HOOK_CODE, timed.stub, begin=IMAGE_BASE + addr, end=IMAGE_BASE + addr)
    else:
        profile_flush = None
    red_rows = set()

    def observe_red_fill():
        if timed.cpu.reg_read(UC_ARM_REG_R1) == 0xa000:
            red_rows.add((timed.cpu.reg_read(UC_ARM_REG_R3), timed.cpu.reg_read(UC_ARM_REG_R2)))
        return timed.fill()

    timed.stubs[0x625A0] = observe_red_fill
    timed.state(status_report=0x80)
    tail = args.build_dir / "ft8_rx.elf"
    clock = symbol(tail, "ft8_clock")
    timed.cpu.mem_write(clock, struct.pack("<6I", 0, 0, 1, 0, 1, 0))
    live = 0x6052C670
    poll, arm = timed.word(live + 28), timed.word(live + 44)
    timed.clock = 0  # Start the scripted DMA timeline without wrapping the timer.
    timed.cpu.mem_write(timed.pcm, b"CQ W9XYZ FN31\0")
    assert timed.call(arm, timed.pcm, 1000)
    timed.call(poll)
    seen = []
    candidate = symbol(tail, "ft8_hw_candidate") & ~1

    def candidate_start(*_):
        seen.append(timed.clock)
        if len(seen) == 30:
            timed.clock = 14_500_000

    candidate_hook = timed.cpu.hook_add(UC_HOOK_CODE, candidate_start, begin=candidate, end=candidate)
    samples = recording_16k(Path(__file__).resolve().parents[1] / "downloads/210703_133430.wav")

    def feed_frame(frame, edge, deadline):
        timed.clock = edge
        timed.state(worker_polling=1, decode_timed=1, decode_deadline=deadline)
        timed.cpu.mem_write(timed.pcm, struct.pack("<HH", len(frame), 0) + frame.tobytes())
        timed.call(0x60445170, timed.pcm, end=0x60445174)
        if edge == 13_450_000:
            # The RTC estimate moves the frame back to phase 13.440 after
            # DMA has already clipped and marked it as the last frame.
            timed.cpu.mem_write(clock, struct.pack("<I", 10))
        timed.call(poll, budget=200_000_000)
        if edge == 13_450_000:
            timed.cpu.mem_write(clock, bytes(4))

    offset = 0
    while offset < 14_500 * 16:
        edge = min(offset + 1600, 13_450 * 16) if offset < 13_450 * 16 else offset + 1600
        frame = samples[offset:edge]
        offset += len(frame)
        feed_frame(frame, offset * 125 // 2, 14_500_000)
        if offset == 12_200 * 16:
            timed.refresh()
            assert all((9, y) not in timed.text_at for y in (270, 302, 334))
        if timed.clock >= 14_500_000:
            break
    timed.refresh()
    assert len(seen) == 30 and seen[0] == 13_450_000, seen
    if profile_flush:
        traced = recent_queue or any(tag in args.build_dir.name for tag in ("rx-trace", "rx-seal"))
        if traced:
            window = symbol(elf, "ft8_live_profile_window")
            timed.call(window, 14500)
        timed.call(profile_flush, 1)
        kinds = {event for _, _, event, _ in profile_writes}
        assert set(range(0x8101, 0x8110)) <= kinds, kinds
        assert sum(event == 0x8105 for _, _, event, _ in profile_writes) == 30
        if recent_queue:
            assert {0x811C, 0x811D, 0x811E, 0x8123} <= kinds, kinds
        if traced:
            assert any(event == 0x8119 and detail >= 12640 for _, _, event, detail in profile_writes)
        if "rx-seal" in args.build_dir.name:
            assert {0x811C, 0x811D, 0x811E} <= kinds, kinds
        print("PASS: decoder stage records and all 30 attempts reached the SD append path")
    assert timed.text_at.get((9, 270)) == "N1JFU EA6EE R-07", timed.drawn
    assert (1, 270) in red_rows, red_rows
    assert "RX #1" in timed.drawn
    print("PASS: the sealed frame starts decode despite a 10 ms RTC correction; partial results carry batch 1")

    left = {pos: line for pos, line in timed.text_at.items() if pos[0] == 9 and pos[1] in (270, 302, 334)}
    assert left and all((409, y) not in timed.text_at for _, y in left), timed.drawn
    timed.cpu.hook_del(candidate_hook)
    # A frame straddling the slot boundary contributes only its new-slot
    # samples. The deliberately discarded tail must not become a PCM gap.
    work = timed.word(symbol(tail, "workspace"))
    # The RX core and the live workspace both have a samples member.
    # Read the published sync state and the ARM RX API's actual PCM count.
    from elftools.elf.elffile import ELFFile
    with tail.open("rb") as handle:
        samples_offset = next(
            field.attributes["DW_AT_data_member_location"].value
            for unit in ELFFile(handle).get_dwarf_info().iter_CUs()
            for die in unit.iter_DIEs()
            if die.tag == "DW_TAG_structure_type" and die.attributes.get("DW_AT_name")
            and die.attributes["DW_AT_name"].value == b"workspace"
            for field in die.iter_children()
            if field.attributes.get("DW_AT_name") and field.attributes["DW_AT_name"].value == b"samples"
        )
    next_sequence = timed.word(live + 20)
    before_tail = timed.call(next_sequence)
    feed_frame(array("h", [123]) * 1600, 14_950_000, 14_500_000)
    assert timed.call(next_sequence) == before_tail
    feed_frame(array("h", [123]) * 800 + array("h", [0]) * 800, 15_050_000, 29_500_000)
    assert timed.word(work + samples_offset) == 800, timed.word(work + samples_offset)
    offset = 15_050 * 16
    print("PASS: slot tail does not enqueue; a crossing frame retains only the next slot's PCM")
    # No keying in this fixture. Feed the same waveform one slot later.
    stream = array("h", samples[:240_000])
    stream.extend([0] * (240_000 - len(stream)))
    stream.extend(samples)
    timed.tap(470, 450, 0x1227)
    timed.call(poll)
    timed.refresh()
    assert any(line.startswith("PAGE 2/") for line in timed.drawn), timed.drawn
    while offset < 29_600 * 16:
        frame = stream[offset:offset + 1600]
        offset += len(frame)
        feed_frame(frame, offset * 125 // 2, 29_500_000)
    timed.refresh()
    assert all(timed.text_at.get(pos) == line for pos, line in left.items()), timed.drawn
    assert any((409, y) in timed.text_at for _, y in left), timed.drawn
    assert timed.text_at.get((409, 270)) == "N1JFU EA6EE R-07" and (401, 270) in red_rows
    assert timed.text_at[206, 239] == "TX"
    assert {"RX #1", "RX #2"} <= set(timed.drawn), timed.drawn
    assert any(line.startswith("PAGE 1/") for line in timed.drawn), timed.drawn
    print("PASS: 00/30 and 15/45 retain separate results and TX labels the chosen slot")

    timed.clock = 30_010_000
    timed.state(status_report=(timed.clock & ~255) | 0x80)
    work = timed.word(symbol(tail, "workspace"))
    phase = work + workspace_tx_phase(tail)
    assert timed.call(timed.word(live + 52), 30_000) == 1, (
        timed.word(phase), timed.word(timed.radio + timed.fields["stop_requested"]),
        timed.word(timed.radio + timed.fields["lease"]))
    assert timed.word(timed.radio + timed.fields["lease"]) == 1
    print("PASS: the armed transmission starts at the next boundary after the RX scan")

    if profile_flush and traced:
        watchdog = symbol(tail, "watchdog_step")
        timed.clock = 43_000_000
        timed.state(lease=3, stop_requested=1, last_heartbeat=timed.clock,
                    status_report=(timed.clock & ~255) | 0x89)
        timed.call(watchdog)
        timed.capture_one()  # DMA may still call back during TX.
        timed.clock += 60_000
        timed.state(status_report=(timed.clock & ~255) | 0x88)
        timed.call(watchdog)
        timed.call(poll)
        timed.clock = 45_050_000
        timed.capture_one()
        for _ in range(8):
            timed.capture_one()  # Overflow the six-frame queue without polling.
        timed.call(profile_flush, 1)
        events = [event for _, _, event, _ in profile_writes]
        assert all(event in events for event in (0x8112, 0x8113, 0x8115, 0x8116, 0x8117)), events[-20:]
        assert events.index(0x8112) < events.index(0x8115) < events.index(0x8113) < events.index(0x8116)
        print("PASS: SD trace records STOP, DMA during TX, MAIN RX, first queued PCM and queue overflow")


if __name__ == "__main__":
    main()
