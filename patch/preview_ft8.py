"""Interactive FTX-1 FT8 menu preview using the actual patched ARM firmware."""

import argparse
import array
import struct
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from unicorn import UC_ARCH_ARM, UC_HOOK_CODE, UC_MODE_ARM, Uc
from unicorn.arm_const import (
    UC_ARM_REG_C1_C0_2, UC_ARM_REG_FPEXC,
    UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1,
    UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP,
)

from build_ft8_menu import HOLE_OFFSET, IMAGE_BASE, ROOT
from test_ft8_menu import check_image


WIDTH, HEIGHT = 800, 480
FRAME = 0x60000000
UI = 0x60935BB4
STACK = 0x609FF000
RETURN = 0x61000000
DEFAULT_IMAGE = ROOT / "outputs/FTX-1_DISPLAY_V0110-ft8menu-TEST.sfl"


def expand_stock_data(image, source, size):
    """Decode the stock scatter-loading stream used by the reset handler."""
    out = bytearray()
    p = source - IMAGE_BASE
    while len(out) < size:
        token = image[p]
        p += 1
        literals, length = token & 7, token >> 4
        if not literals:
            literals = image[p]
            p += 1
        if not length:
            length = image[p]
            p += 1
        literals -= 1
        out.extend(image[p:p + literals])
        p += literals
        if token & 8:
            distance = image[p]
            p += 1
            for _ in range(length + 2):
                out.append(out[-distance])
        else:
            out.extend(bytes(length))
    if len(out) != size:
        raise ValueError("Unexpected stock initialization data length")
    return bytes(out)


class Panel:
    def __init__(self, image):
        self.cpu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        self.cpu.mem_map(FRAME, 0xA00000)
        self.cpu.mem_map(RETURN, 0x1000)
        self.cpu.mem_write(IMAGE_BASE, image)
        self.packets = []
        self.fonts = {}
        self.labels = []

        for entry in (0x2C015C, 0x2C016C):
            src, dest, size, _ = struct.unpack_from("<4I", image, entry)
            self.cpu.mem_write(dest, expand_stock_data(image, src, size))
        self.cpu.mem_write(0x607C4BB0, struct.pack("<I", 3))  # Stock framebuffer layer 3.
        # VFP coprocessor access, as the stock boot code enables on device.
        self.cpu.reg_write(UC_ARM_REG_C1_C0_2, 0x00F00000)
        self.cpu.reg_write(UC_ARM_REG_FPEXC, 0x40000000)

        for off, hook in ((0x41FF8, self._skip_worker), (0x14A1C, self._record_transport),
                          (0x23D64, self._draw_text), (0x135D4, self._read_rtc)):
            address = IMAGE_BASE + off
            self.cpu.hook_add(UC_HOOK_CODE, hook, begin=address, end=address)

    def _skip_worker(self, cpu, _address, _size, _data):
        cpu.reg_write(UC_ARM_REG_PC, cpu.reg_read(UC_ARM_REG_LR))

    def _record_transport(self, cpu, address, size, data):
        ptr, length = (cpu.reg_read(reg) for reg in (UC_ARM_REG_R0, UC_ARM_REG_R1))
        self.packets.append(bytes(cpu.mem_read(ptr, length)))
        self._skip_worker(cpu, address, size, data)

    def _read_rtc(self, cpu, address, size, data):
        # 2026-11-10 .. 12:00:30 as seven BCD bytes (year, month, day, dow, h, m, s).
        out = cpu.reg_read(UC_ARM_REG_R0)
        cpu.mem_write(out, bytes([0x26, 0x11, 0x10, 0x02, 0x12, 0x00, 0x30]))
        cpu.reg_write(UC_ARM_REG_R0, 0)
        self._skip_worker(cpu, address, size, data)

    def _draw_text(self, cpu, address, size, data):
        # The stock font object is normally created from flash metadata at boot.
        # Use the firmware's actual arguments and draw the preview glyphs into RGB565 RAM.
        frame, glyphs, count, font_size = (
            cpu.reg_read(reg) for reg in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)
        )
        sp = cpu.reg_read(UC_ARM_REG_SP)
        _, color, _, x, y, align = struct.unpack("<6I", cpu.mem_read(sp, 24))
        if count and x < WIDTH and y < HEIGHT:
            label = bytes(cpu.mem_read(glyphs, count * 2)).decode("utf-16le", errors="replace")
            self.labels.append(label)
            px = min(max(font_size - 3, 10), 28)
            if px not in self.fonts:
                self.fonts[px] = ImageFont.load_default(size=px)
            font = self.fonts[px]
            width = round(font.getlength(label))
            if align & 0x202:
                x += x // 2 - width // 2
            elif not align & 1:
                x -= width if align & 4 else width // 2
            if not 0 <= x < WIDTH:
                raise ValueError(f"Preview text outside the framebuffer: {label!r}")
            w = min(WIDTH - x, width + 2)
            h = min(HEIGHT - y, px + 3)
            mask = Image.new("L", (w, h))
            ImageDraw.Draw(mask).text((0, 0), label, font=font, fill=255, anchor="lt")
            rgb565 = struct.pack("<H", color & 0xFFFF)
            pixels = mask.tobytes()
            for line in range(h):
                offset = frame + 2 * ((y + line) * WIDTH + x)
                row = cpu.mem_read(offset, w * 2)
                for col, alpha in enumerate(pixels[line * w:(line + 1) * w]):
                    if alpha >= 96:
                        row[col * 2:col * 2 + 2] = rgb565
                cpu.mem_write(offset, bytes(row))
        cpu.reg_write(UC_ARM_REG_R0, 0)
        self._skip_worker(cpu, address, size, data)

    def _call(self, offset, *args, end=RETURN, stack=STACK, budget=20_000_000):
        regs = UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3
        for reg, arg in zip(regs, (*args, 0, 0, 0, 0)):
            self.cpu.reg_write(reg, arg)
        self.cpu.reg_write(UC_ARM_REG_LR, RETURN)
        self.cpu.reg_write(UC_ARM_REG_SP, stack)
        self.cpu.emu_start(IMAGE_BASE + offset, end, count=budget)
        pc = self.cpu.reg_read(UC_ARM_REG_PC)
        sp = self.cpu.reg_read(UC_ARM_REG_SP)
        if pc != end or sp != stack:
            raise RuntimeError(f"Firmware call {offset:#x} did not return (PC={pc:#x}, SP={sp:#x})")
        return self.cpu.reg_read(UC_ARM_REG_R0)

    def _refresh(self):
        self.labels.clear()
        self._call(0x438F4, end=IMAGE_BASE + 0x438F8)

    def show_mode(self):
        self.cpu.mem_write(UI, b"\0")
        self._refresh()
        self.cpu.mem_write(FRAME, bytes(WIDTH * HEIGHT * 2))
        self.cpu.mem_write(UI, b"\x30")
        self.cpu.mem_write(UI + 0x13B, b"\x05\x01")
        self._call(0x3C51C, UI, 1)
        self._refresh()

    def tap(self, x, y):
        self._call(0x41D4, x, y)
        self._call(0x23498, 0)
        self._call(0x23498, 0)
        self._call(0x41F8)
        self._call(0x23498, 0)
        self._refresh()

    def screen(self):
        pixels = bytes(self.cpu.mem_read(FRAME, WIDTH * HEIGHT * 2))
        return Image.frombytes("RGB", (WIDTH, HEIGHT), pixels, "raw", "BGR;16")


class LivePanel(Panel):
    WORK = 0x61100000
    WORKER_STACK = 0x61210000
    DMA_FRAME = 0x61220000

    def __init__(self, image, *, simulate_tx=True):
        super().__init__(image)
        (magic, version, work, stack, bind, sequence, sync, poll, position,
         grid, tx, arm, attach_tx) = struct.unpack_from("<4s12I", image, HOLE_OFFSET)
        if (magic, version) != (b"FT8L", 6) or not 0 < work <= 0x100000:
            raise ValueError("Unexpected integrated firmware API")
        if stack % 0x1000 or not 0x8000 <= stack <= 0x10000:
            raise ValueError("Unexpected FT8 worker stack size")
        self.cpu.mem_map(self.WORK, (work + 0xFFF) & ~0xFFF)
        self.cpu.mem_map(self.WORKER_STACK - stack, stack)
        self.cpu.mem_map(self.DMA_FRAME, 0x1000)
        self.sequence_entry = sequence - IMAGE_BASE
        self.sync_entry = sync - IMAGE_BASE
        self.poll_entry = poll - IMAGE_BASE
        self.position_entry = position - IMAGE_BASE
        self.grid_entry = grid - IMAGE_BASE
        self.tx_entry = tx - IMAGE_BASE
        self.arm_entry = arm - IMAGE_BASE
        if not self._call(bind - IMAGE_BASE, self.WORK, work):
            raise RuntimeError("Firmware rejected the emulated RX workspace")

        self.time_samples = 0
        self.tx_events = []
        self.audio_blocks = []
        self.tx_deadline = None
        self.tx_allow_start = True
        self.tx_accept_audio = True
        self.tx_drain_result = 1
        self.tx_confirm_stop = True
        if simulate_tx:
            # These addresses live in Unicorn-only memory and do not patch stock I/O.
            callbacks = (self._tx_now, self._tx_start, self._tx_submit,
                         self._tx_drained, self._tx_stop)
            addresses = tuple(RETURN + 0x10 + 4 * i for i in range(len(callbacks)))
            for address, hook in zip(addresses, callbacks):
                self.cpu.hook_add(UC_HOOK_CODE, hook, begin=address, end=address)
            self.cpu.mem_write(self.DMA_FRAME, struct.pack("<5I", *addresses))
            if not self._call(attach_tx - IMAGE_BASE, self.DMA_FRAME):
                raise RuntimeError("Firmware rejected the simulation-only TX adapter")

    def _tx_return(self, result, cpu, address, size, data):
        cpu.reg_write(UC_ARM_REG_R0, result & 0xFFFFFFFF)
        self._skip_worker(cpu, address, size, data)

    def _tx_now(self, cpu, address, size, data):
        self._tx_return(self.time_samples // 16, cpu, address, size, data)

    def _tx_start(self, cpu, address, size, data):
        lease = cpu.reg_read(UC_ARM_REG_R0)
        if not self.tx_allow_start or self.tx_deadline is not None:
            self._tx_return(0, cpu, address, size, data)
            return
        self.tx_deadline = self.time_samples + lease * 16
        self.tx_events.append("on")
        self._tx_return(1, cpu, address, size, data)

    def _tx_submit(self, cpu, address, size, data):
        ptr, frames = (cpu.reg_read(r) for r in (UC_ARM_REG_R0, UC_ARM_REG_R1))
        ok = self.tx_deadline is not None and frames == 800 and self.tx_accept_audio
        if ok:
            self.audio_blocks.append(bytes(cpu.mem_read(ptr, frames * 4)))
        self._tx_return(ok, cpu, address, size, data)

    def _tx_drained(self, cpu, address, size, data):
        self._tx_return(self.tx_drain_result, cpu, address, size, data)

    def _tx_stop(self, cpu, address, size, data):
        if self.tx_confirm_stop and self.tx_deadline is not None:
            self.tx_events.append("off")
            self.tx_deadline = None
        self._tx_return(self.tx_deadline is None, cpu, address, size, data)

    def _advance_samples(self, samples):
        self.time_samples += samples
        if self.tx_deadline is not None and self.time_samples >= self.tx_deadline:
            self.tx_deadline = None
            self.tx_events.append("lease-expired")

    def advance_ms(self, milliseconds):
        self._advance_samples(milliseconds * 16)

    def tap(self, x, y):
        super().tap(x, y)
        # Service control requests immediately in the preview, even with no RX frame.
        self.poll()
        self.refresh()

    def sync_slot(self, skip=0):
        sequence = self._call(self.sequence_entry)
        return self._call(self.sync_entry, sequence, skip, stack=self.WORKER_STACK) != 0

    def set_position(self, lat_e6, lon_e6):
        return self._call(self.position_entry, lat_e6 & 0xFFFFFFFF, lon_e6 & 0xFFFFFFFF) != 0

    def _send_text(self, entry, text):
        data = text.encode("ascii")
        if len(data) >= 0x1000:
            raise ValueError("Input too long for the emulator buffer")
        self.cpu.mem_write(self.DMA_FRAME, data + b"\0")
        return self._call(entry, self.DMA_FRAME) != 0

    def set_grid(self, grid):
        return self._send_text(self.grid_entry, grid)

    def record_tx(self, message):
        return self._send_text(self.tx_entry, message)

    def arm(self, message, frequency_hz):
        data = message.encode("ascii")
        self.cpu.mem_write(self.DMA_FRAME, data + b"\0")
        return self._call(self.arm_entry, self.DMA_FRAME, frequency_hz) != 0

    def capture(self, samples, *, count=None):
        count = len(samples) if count is None else count
        self._advance_samples(len(samples))
        self.cpu.mem_write(self.DMA_FRAME, struct.pack("<HH", count, 0x1234) + samples.tobytes())
        metadata = self._call(0x45170, self.DMA_FRAME, end=IMAGE_BASE + 0x45174)
        if metadata != 0x1234:
            raise RuntimeError("Patched DMA hook changed the native frame metadata")

    def poll(self):
        return self._call(self.poll_entry, stack=self.WORKER_STACK, budget=1_000_000_000)

    def refresh(self):
        labels = self.labels[:]
        self._refresh()
        if not self.labels:
            self.labels = labels


def screenshot_test(panel, directory):
    directory.mkdir(parents=True, exist_ok=True)
    panel.show_mode()
    menu = panel.screen()
    panel.tap(510, 380)
    receive = panel.screen()
    assert receive.tobytes() != menu.tobytes()
    assert not panel.packets
    panel.tap(625, 130)
    assert panel.screen().tobytes() == menu.tobytes()
    assert not panel.packets
    panel.tap(265, 174)  # Native USB cell.
    assert panel.packets[-2:] == [bytes.fromhex("e001012100"), bytes.fromhex("e000012100")]
    menu.save(directory / "ft8-mode.png")
    receive.save(directory / "ft8-rx.png")
    print("PASS: actual firmware framebuffer, FT8 enter/back, and stock USB dispatch")


def show_window(panel, replay_samples=None, *, demo_position=False):
    import tkinter as tk
    from tkinter import ttk
    from PIL import ImageTk

    window = tk.Tk()
    title = "FT8 RX lab" if replay_samples is not None else "FT8 firmware preview"
    window.title(f"FTX-1 · DISPLAY V01-10 · {title}")
    window.resizable(False, False)
    toolbar = ttk.Frame(window, padding=(12, 8))
    toolbar.pack(fill="x")
    location_note = " · 演示坐标" if demo_position else ""
    ttk.Label(toolbar, text=f"FTX-1  |  DISPLAY V01-10  |  ARM 模拟 · 预览字体{location_note}").pack(side="left")
    canvas = tk.Canvas(window, width=WIDTH, height=HEIGHT, bg="black", highlightthickness=0)
    canvas.pack()
    canvas_image = canvas.create_image(0, 0, anchor="nw")
    status = tk.StringVar()
    ttk.Label(window, textvariable=status, padding=(12, 8)).pack(fill="x")
    replay = None
    replay_position = 0
    silence = array.array("h", [0]) * 1999

    def paint():
        canvas.photo = ImageTk.PhotoImage(panel.screen())
        canvas.itemconfigure(canvas_image, image=canvas.photo)

    def mode():
        stop_replay()
        panel.show_mode()
        if replay_samples is not None:
            panel.poll()
        paint()
        status.set("点击底排 FT8 回放样本并解码。" if replay_samples is not None else
                   "点击底排 FT8 进入接收页，然后点击屏幕上的 BACK 返回。")

    def stop_replay():
        nonlocal replay
        if replay is not None:
            window.after_cancel(replay)
            replay = None

    def play_chunk():
        nonlocal replay_position, replay
        replay = None
        if replay_position == len(replay_samples):
            if panel.tx_deadline is None and " ARMED" not in panel.labels:
                return
            for _ in range(4):
                panel.capture(silence)
                panel.poll()
            panel.refresh()
            paint()
            status.set("模拟发射。音频和键控事件留在模拟器内。")
            replay = window.after(40, play_chunk)
            return
        for _ in range(4):
            if replay_position == len(replay_samples):
                panel.refresh()
                paint()
                status.set("录音回放结束。TX NEXT 可启动模拟发射。")
                if " ARMED" in panel.labels:
                    replay = window.after(40, play_chunk)
                return
            end = min(replay_position + 1999, len(replay_samples))
            panel.capture(replay_samples[replay_position:end])
            panel.poll()
            replay_position = end
        replay = window.after(10, play_chunk)

    def touch(event):
        nonlocal replay_position, replay
        old_count = len(panel.packets)
        panel.tap(event.x, event.y)
        paint()
        if replay_samples is not None and "WAITING FOR SLOT" in panel.labels and panel.sync_slot():
            stop_replay()
            panel.refresh()
            paint()
            replay_position = 0
            status.set("正在向固件的接收钩子回放 WAV。")
            replay = window.after(10, play_chunk)
        elif replay_samples is not None and "MODE" in panel.labels:
            stop_replay()
            status.set("点击底排 FT8 回放样本并解码。")
        elif replay_samples is not None and " ARMED" in panel.labels and replay is None:
            replay = window.after(40, play_chunk)
        elif len(panel.packets) != old_count:
            status.set("已捕获原厂发往 MAIN 的菜单事件。此预览未连接 MAIN。")
        else:
            status.set("正在执行固件的触摸分发和屏幕绘制。")

    ttk.Button(toolbar, text="MODE", command=mode).pack(side="right")
    canvas.bind("<ButtonRelease-1>", touch)
    mode()
    window.mainloop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sfl", type=Path)
    parser.add_argument("--live", action="store_true", help="Use the integrated receiver image")
    parser.add_argument("--wav", type=Path, help="15-second slot recording for the live preview")
    position = parser.add_mutually_exclusive_group()
    position.add_argument("--grid", help="Override the local locator for this preview")
    position.add_argument("--position", type=float, nargs=2, metavar=("LAT", "LON"),
                          help="Override the local latitude and longitude in decimal degrees")
    parser.add_argument("--screenshots", type=Path, help="Run the emulator check and export PNGs")
    args = parser.parse_args()
    if args.live:
        from test_ft8_arm import recording_16k
        from test_ft8_menu import read_display_sfl

        path = args.sfl or ROOT / "outputs/FTX-1_DISPLAY_V0110-ft8live-LAB.sfl"
        panel = LivePanel(read_display_sfl(path))
        samples = recording_16k(args.wav or ROOT / "downloads/210703_133430.wav")
        demo_position = args.grid is None and args.position is None
        if args.grid is not None:
            if not args.grid.isascii() or not panel.set_grid(args.grid):
                parser.error("Invalid 4- or 6-character Maidenhead locator")
        else:
            from math import isfinite

            lat, lon = args.position or (35 + 35.3179 / 60, 139 + 43.8625 / 60)
            if not (isfinite(lat) and isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
                parser.error("Invalid latitude or longitude")
            if not panel.set_position(round(lat * 1e6), round(lon * 1e6)):
                parser.error("The firmware rejected the latitude or longitude")
        if args.screenshots:
            parser.error("Use test_ft8_live.py --screenshots for an integrated image")
        show_window(panel, samples, demo_position=demo_position)
        return
    if args.wav or args.grid or args.position:
        parser.error("--wav, --grid and --position require --live")
    payload = (ROOT / "patch/build/ft8_menu.bin").read_bytes()
    panel = Panel(check_image(args.sfl or DEFAULT_IMAGE, payload, False))
    if args.screenshots:
        screenshot_test(panel, args.screenshots)
    else:
        show_window(panel)


if __name__ == "__main__":
    main()
