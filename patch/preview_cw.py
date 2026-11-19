"""Interactive ARM preview of the standalone FTX-1 CW firmware."""

import argparse
import math
import random
import struct
from array import array
from pathlib import Path

from elftools.elf.elffile import ELFFile
from PIL import Image, ImageDraw, ImageFont
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0

from build_ft8_menu import HOLE_OFFSET, IMAGE_BASE, ROOT
from preview_ft8 import FRAME, HEIGHT, UI, WIDTH, Panel
from test_cw import audio
from test_ft8_menu import read_display_sfl


class CWPanel(Panel):
    PCM = 0x61100000
    DETAIL = PCM + 0x1000

    def __init__(self, image, elf_path):
        super().__init__(image)
        with elf_path.open("rb") as file:
            elf = ELFFile(file)
            code = elf.get_section_by_name(".payload").data()
            if image[HOLE_OFFSET:HOLE_OFFSET + len(code)] != code:
                raise ValueError("CW ELF does not match the packaged SFL")
            table = elf.get_section_by_name(".symtab")
            self.poll_offset = table.get_symbol_by_name("cw_worker_step")[0]["st_value"] - IMAGE_BASE
        self.cpu.mem_map(self.PCM, 0x2000)
        self.clock = 0
        self.mode = "CW-U"
        self.active = False
        self.menu_open = False
        self.samples = audio([("CQ CQ DE W1AW", 28), ("TEST CW 599 DE W1AW", 18),
                              ("73 DE W1AW", 18)], 600, pause_units=18)
        self.position = 0
        self.background = {mode: demo_scope(mode) for mode in ("CW-U", "CW-L")}
        for offset, result in ((0x78FB0, 1), (0x7A830, 0), (0x3000, 0), (0x1669C, None)):
            address = IMAGE_BASE + offset
            self.cpu.hook_add(UC_HOOK_CODE, self._service(result), begin=address, end=address)
        self.cpu.mem_write(0x60939947, b"\x05")
        self.set_mode("CW-U")

    def _service(self, result):
        def complete(cpu, address, size, data):
            cpu.reg_write(UC_ARM_REG_R0, self.clock if result is None else result)
            self._skip_worker(cpu, address, size, data)
        return complete

    def _refresh(self):
        self.clock += 101_000
        super()._refresh()

    def paint_scope(self):
        self.cpu.mem_write(FRAME, self.background[self.mode])

    def set_mode(self, mode):
        self.mode = mode
        self.cpu.mem_write(UI + 0xA3 + 0x4C, bytes((2 if mode == "CW-L" else 3,)))
        if not self.menu_open:
            self.paint_scope()
            self._call(self.poll_offset)
            self._refresh()

    def show_mode(self):
        self.paint_scope()
        self.menu_open = True
        selection = 2 if self.mode == "CW-L" else 3
        self.cpu.mem_write(UI, b"\x30")
        self.cpu.mem_write(UI + 0x13B, bytes((5, selection)))
        self._call(0x3C51C, UI, selection)
        self._refresh()

    def tap(self, x, y):
        event = self._call(0x2387C, x, y, self.DETAIL)
        if event in (0x1133, 0x1134, 0x1135):
            self._call(0x232E0, 1, event)
            self._call(0x232E0, 0, event)
        if event == 0x1134:
            self.active = True
            self.menu_open = False
            self.position = 0
            self.cpu.mem_write(UI, b"\x20")
            self.paint_scope()
        elif event == 0x1135:
            self.active = False
        elif self.menu_open and event in (0x1122, 0x1123):
            self.menu_open = False
            self.cpu.mem_write(UI, b"\x20")
            self.set_mode("CW-L" if event == 0x1122 else "CW-U")
        self._call(self.poll_offset)
        self._refresh()
        if event in (0x1134, 0x1135):
            # The hardware composites a transparent UI erase above the scope.
            # This preview uses a single framebuffer, so repaint the RF fixture.
            self.paint_scope()
            self._refresh()
        return event

    def advance(self):
        if not self.active or self.menu_open or self.position >= len(self.samples):
            return False
        chunk = self.samples[self.position:self.position + 768]
        self.position += len(chunk)
        self.cpu.mem_write(self.PCM, struct.pack("<HH", len(chunk), 0) + chunk.tobytes())
        self._call(0x45170, self.PCM, end=0x60445174)
        self._call(self.poll_offset)
        self._refresh()
        return True


def demo_scope(mode):
    """Draw the simulated RF scope behind the native firmware controls."""
    screen = Image.new("RGB", (WIDTH, HEIGHT), "#07101a")
    draw = ImageDraw.Draw(screen)
    large = ImageFont.load_default(size=54)
    small = ImageFont.load_default(size=16)
    draw.rectangle((0, 0, 799, 28), fill="#172534")
    draw.text((14, 6), "MAIN VFO", font=small, fill="#8dd1ff")
    draw.text((465, 51), "7.030.000", font=large, fill="#6cc9ff")
    draw.text((716, 38), mode, font=small, fill="white")
    draw.text((16, 119), "S  1    3    5    7    9     +20    +40", font=small, fill="#e6eef4")
    draw.line((18, 146, 347, 146), fill="#5ca8cf", width=2)
    draw.line((18, 146, 109, 146), fill="#8df1af", width=4)
    draw.rectangle((4, 173, 795, 404), outline="#586e7d", fill="#071420")
    for x in range(5, 796, 79):
        draw.line((x, 174, x, 404), fill="#293f4d")
    for y in range(204, 405, 29):
        draw.line((5, y, 795, y), fill="#233c4d")
    rng = random.Random(4)
    points = []
    for x in range(5, 796):
        peak = sum(amplitude * math.exp(-((x - center) / width) ** 2)
                   for amplitude, center, width in ((116, 398, 13), (52, 516, 18), (62, 251, 11)))
        points.append((x, int(372 - peak - rng.randrange(0, 14))))
    draw.line(points, fill="#5fc7ec", width=2)
    draw.line((398, 175, 398, 403), fill="#9bddb8")
    for index, label in enumerate(("D-MODE", "3DSS", "MULTI", "SCOPE", "SPAN", "SPEED")):
        x = index * WIDTH // 6
        draw.rectangle((x, 420, (index + 1) * WIDTH // 6 - 1, 479),
                       fill="#1c2a38", outline="#07101a")
        draw.text((x + 14, 437), label, font=small, fill="#e6eef4")
    return array("H", ((r & 0xf8) << 8 | (g & 0xfc) << 3 | b >> 3
                       for r, g, b in screen.getdata())).tobytes()


def screenshots(panel, directory):
    directory.mkdir(parents=True, exist_ok=True)
    panel.show_mode()
    assert "CUSTM" in panel.labels
    panel.screen().save(directory / "mode.png")
    assert panel.tap(520, 382) == 0x1133 and "CW_DEC" in panel.labels
    panel.screen().save(directory / "custm.png")
    assert panel.tap(520, 382) == 0x1134
    while panel.advance():
        pass
    assert any("W1AW" in label for label in panel.labels), panel.labels
    panel.screen().save(directory / "cw-decode.png")
    assert panel.tap(768, 413) == 0x1135 and not panel.active
    panel.screen().save(directory / "closed.png")
    print("PASS: MODE → CUSTM → CW_DEC → decode → CLOSE", flush=True)


def show_window(panel):
    import tkinter as tk
    from tkinter import ttk

    from PIL import ImageTk

    window = tk.Tk()
    window.title("FTX-1 · CW 解码模拟")
    window.resizable(False, False)
    controls = ttk.Frame(window, padding=8)
    controls.pack(fill="x")
    canvas = tk.Canvas(window, width=WIDTH, height=HEIGHT, highlightthickness=0)
    canvas.pack()
    item = canvas.create_image(0, 0, anchor="nw")

    def refresh():
        canvas.picture = ImageTk.PhotoImage(panel.screen())
        canvas.itemconfigure(item, image=canvas.picture)

    def open_mode():
        panel.show_mode()
        refresh()

    def on_tap(event):
        panel.tap(event.x, event.y)
        refresh()

    def set_mode(mode):
        panel.set_mode(mode)
        refresh()

    def play():
        if panel.active:
            panel.position = 0

    def tick():
        if panel.advance():
            refresh()
        window.after(48, tick)

    ttk.Button(controls, text="MODE", command=open_mode).pack(side="left")
    for mode in ("CW-U", "CW-L"):
        ttk.Button(controls, text=mode, command=lambda value=mode: set_mode(value)).pack(side="left", padx=4)
    ttk.Button(controls, text="重播测试电码", command=play).pack(side="left", padx=4)
    ttk.Label(controls, text="演示频谱 · 测试电码 28→18 WPM").pack(side="right")
    canvas.bind("<Button-1>", on_tap)
    open_mode()
    window.after(48, tick)
    window.mainloop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path,
                        default=ROOT / "outputs/cw-bench-rx2/FTX-1_DISPLAY_V0110.SFL")
    parser.add_argument("--elf", type=Path, required=True)
    parser.add_argument("--screenshots", type=Path)
    args = parser.parse_args()
    panel = CWPanel(read_display_sfl(args.image), args.elf)
    if args.screenshots:
        screenshots(panel, args.screenshots)
    else:
        show_window(panel)


if __name__ == "__main__":
    main()
