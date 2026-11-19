"""Exercise the actual patched ARM instructions with the stock firmware and UI stubs."""

import argparse
import runpy
import struct
import zlib
from pathlib import Path

from unicorn import UC_ARCH_ARM, UC_HOOK_CODE, UC_MODE_ARM, Uc
from unicorn.arm_const import (
    UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1,
    UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP,
)

from build_ft8_menu import HOOKS, HOLE_OFFSET, IMAGE_BASE, PROBE_HOOK, ROOT, TAIL_OFFSET


UI = 0x60935BB4
RETURN = 0x61000000
STACK = 0x609FF000
FRAME = 0x60020000
ARGS = UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3


def read_display_sfl(path):
    packer = runpy.run_path(str(ROOT / "work/tools/ft710-internals/decode_sfl.py"))
    sfl = path.read_bytes()
    img, encrypted = packer["extract_continuous"](sfl, "display")
    crc = zlib.crc32(encrypted + bytes.fromhex("8f93c635"))
    assert sfl[0x220:0x228] == f"{crc:08X}".encode()
    assert int(sfl[0x200:0x220].split()[1]) == len(sfl)
    return img


def check_image(path, payload, probe, *, decoder=None):
    from build_ft8_menu import LIVE_HOOK

    stock = (ROOT / "work/dec/display/display.bin").read_bytes()
    img = read_display_sfl(path)
    tail = (bytes(TAIL_OFFSET - len(stock)) + decoder if decoder is not None else
            b"\0\0\0\0FT8P" if probe else b"")
    # merge_display may append up to two zero pad bytes so the container round-trips.
    assert len(stock) + len(tail) <= len(img) <= len(stock) + len(tail) + 2
    assert img[len(stock):len(stock) + len(tail)] == tail
    assert not any(img[len(stock) + len(tail):])

    hooks = HOOKS + ((LIVE_HOOK,) if decoder is not None else (PROBE_HOOK,) if probe else ())
    allowed = {offset + i for offset, *_ in hooks for i in range(4)}
    allowed.update(range(HOLE_OFFSET, HOLE_OFFSET + len(payload)))
    assert img[HOLE_OFFSET:HOLE_OFFSET + len(payload)] == payload
    assert all(a == b or i in allowed for i, (a, b) in enumerate(zip(img, stock)))
    return img


def exercise(img, probe):
    cpu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    cpu.mem_map(0x60000000, 0xA00000)
    cpu.mem_map(RETURN, 0x1000)
    cpu.mem_write(IMAGE_BASE, img)
    calls = []

    def stub(machine, addr, _size, _user):
        offset = addr - IMAGE_BASE
        if offset == 0x232E4:
            # The stock hook resumes after replaying the eight-register push.
            assert machine.reg_read(UC_ARM_REG_SP) == STACK - 32
            calls.append("stock touch")
            machine.reg_write(UC_ARM_REG_SP, STACK)
        elif offset == 0x23D64:
            ptr = machine.reg_read(UC_ARM_REG_R1)
            n = machine.reg_read(UC_ARM_REG_R2)
            calls.append(bytes(machine.mem_read(ptr, 2 * n)).decode("utf-16le"))
        elif offset == 0x448B8:
            machine.reg_write(UC_ARM_REG_R0, FRAME)
        else:
            calls.append({0x41FF8: "stock worker", 0x3BD3C: "stock popup",
                          0x625A0: "fill", 0x62818: "bitmap"}[offset])
        machine.reg_write(UC_ARM_REG_PC, machine.reg_read(UC_ARM_REG_LR))

    for off in (0x232E4, 0x23D64, 0x448B8, 0x41FF8, 0x3BD3C, 0x625A0, 0x62818):
        address = IMAGE_BASE + off
        cpu.hook_add(UC_HOOK_CODE, stub, begin=address, end=address)

    def run(offset, *args, end=RETURN):
        for reg, value in zip(ARGS, (*args, 0, 0, 0, 0)):
            cpu.reg_write(reg, value)
        cpu.reg_write(UC_ARM_REG_SP, STACK)
        cpu.reg_write(UC_ARM_REG_LR, RETURN)
        # The page-exit path clears ~213k framebuffer pixels (~1.3M instructions).
        cpu.emu_start(IMAGE_BASE + offset, end, count=2_000_000)
        assert cpu.reg_read(UC_ARM_REG_PC) == end
        assert cpu.reg_read(UC_ARM_REG_SP) == STACK
        return cpu.reg_read(UC_ARM_REG_R0)

    def refresh():
        calls.clear()
        run(0x438F4, end=IMAGE_BASE + 0x438F8)
        assert calls[0] == "stock worker"

    def hit(x, y):
        return run(0x2387C, x, y, STACK + 0x20)

    cpu.mem_write(UI, b"\x30")
    cpu.mem_write(UI + 0x13B, b"\x05\x01")
    run(0x3C51C, UI, 1)
    refresh()
    assert calls == ["stock worker", "bitmap", "FT8"]
    assert hit(240, 165) == 0x1121  # USB is still the stock event.
    assert hit(620, 375) == 0x112F  # PRESET is still the stock event.
    assert hit(480, 375) == 0x1133
    run(0x232E0, 1, 0x1133)
    run(0x232E0, 0, 0x1133)
    refresh()
    assert "FT8 RX" in calls
    if probe:
        assert "TAIL: PRESENT" in calls
        assert "FRAMES: 0" in calls
        audio = FRAME + 0x80000
        cpu.mem_write(audio, struct.pack("<HH", 1999, 0x1234))
        for _ in range(8):
            assert run(0x45170, audio, end=IMAGE_BASE + 0x45174) == 0x1234
        assert cpu.mem_read(0x607C401C, 4) == struct.pack("<I", audio)
        cpu.mem_write(IMAGE_BASE + TAIL_OFFSET, bytes(4))
        refresh()
        assert "FRAMES: 8" in calls and "HEADER COUNT: 1999" in calls
        assert "TAIL: MISSING" in calls
    else:
        assert "DECODER OFFLINE" in calls
    assert "stock touch" not in calls
    assert hit(240, 165) == 0x1135
    run(0x232E0, 1, 0x1135)
    run(0x232E0, 0, 0x1135)
    assert hit(610, 130) == 0x1134
    run(0x232E0, 1, 0x1134)
    run(0x232E0, 0, 0x1134)
    refresh()
    assert calls == ["stock worker", "stock popup", "bitmap", "FT8"]
    run(0x232E0, 1, 0x1121)
    assert calls[-1] == "stock touch"

    run(0x232E0, 1, 0x1133)
    cpu.mem_write(UI, b"\0")
    refresh()
    assert calls == ["stock worker"]
    cpu.mem_write(UI, b"\x30")
    refresh()
    assert calls == ["stock worker", "bitmap", "FT8"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--build-dir", type=Path, default=ROOT / "patch/build")
    parser.add_argument("sfl", nargs="?", type=Path)
    args = parser.parse_args()
    kind = "probe" if args.probe else "menu"
    image = args.sfl or ROOT / f"outputs/FTX-1_DISPLAY_V0110-ft8{kind}-TEST.sfl"
    exercise(check_image(image, (args.build_dir / f"ft8_{kind}.bin").read_bytes(), args.probe),
             args.probe)
    print("PASS: checked SFL and ARM MODE -> FT8 -> BACK, stock USB and PRESET preserved")
