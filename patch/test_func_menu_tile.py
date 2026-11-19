"""Compare the original FUNC-menu bitmap call against patched DISPLAY images."""

import argparse
from pathlib import Path

from unicorn import UC_ARCH_ARM, UC_MODE_ARM, Uc
from unicorn.arm_const import UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP

from test_ft8_menu import read_display_sfl


def draw_tile(image):
    base, frame, stack = 0x60400000, 0x60000000, 0x60100000
    start, end = base + 0x38868, base + 0x3886C
    cpu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    cpu.mem_map(frame, 0x200000)
    cpu.mem_map(base, 0x2D0000)
    cpu.mem_write(base, image)
    background = b"\x96\x29" * (800 * 480)
    cpu.mem_write(frame, background)
    for y, x in ((142, 0), (430, 690)):
        for register, value in ((UC_ARM_REG_R0, frame), (UC_ARM_REG_R1, y),
                                (UC_ARM_REG_R2, x), (UC_ARM_REG_R3, 0x604D97A4),
                                (UC_ARM_REG_SP, stack)):
            cpu.reg_write(register, value)
        cpu.emu_start(start, end, count=3_000_000)
        assert cpu.reg_read(UC_ARM_REG_PC) == end
    return background, bytes(cpu.mem_read(frame, len(background)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="+", type=Path)
    args = parser.parse_args()
    stock = Path(__file__).resolve().parents[1] / "work/dec/display/display.bin"
    background, expected = draw_tile(stock.read_bytes())
    assert expected.count(b"\xff\xff") == 2 * 5488
    assert expected != background
    for path in args.images:
        _, actual = draw_tile(read_display_sfl(path))
        assert actual == expected, f"{path}: FUNC background differs from stock"
        print(f"PASS: {path.name} FUNC background matches stock pixel for pixel")


if __name__ == "__main__":
    main()
