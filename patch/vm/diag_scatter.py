"""Trace the Thumb scatter loader with full board (bus fallbacks active)."""
import sys
from pathlib import Path

VM_DIR = Path(__file__).resolve().parent
ROOT = VM_DIR.parents[1]
sys.path.insert(0, str(VM_DIR))

from unicorn import UC_HOOK_CODE                              # noqa: E402
from unicorn.arm_const import (                               # noqa: E402
    UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
    UC_ARM_REG_R3, UC_ARM_REG_R7, UC_ARM_REG_R10, UC_ARM_REG_R11,
    UC_ARM_REG_LR,
)
from ftx1vm import Board, addrs                               # noqa: E402

REGS = (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3,
        UC_ARM_REG_R7, UC_ARM_REG_R10, UC_ARM_REG_R11, UC_ARM_REG_LR)


def main():
    image = (ROOT / "work/dec/display/display.bin").read_bytes()
    board = Board(image)
    uc = board.core.uc
    lines = []

    def hook(u, address, size, _user):
        if 0x60402b40 <= address <= 0x60402bd8:
            r0, r1, r2, r3, r7, r10, r11, lr = (u.reg_read(reg) for reg in REGS)
            lines.append(f"pc={address:#010x} r0={r0:#010x} r1={r1:#010x} r2={r2:#010x} "
                         f"r3={r3:#010x} r7={r7:#010x} r10={r10:#010x} r11={r11:#010x} lr={lr:#010x}")

    uc.hook_add(UC_HOOK_CODE, hook, begin=0x60402b40, end=0x60402bd8)
    uc.reg_write(UC_ARM_REG_PC, addrs.RESET_ENTRY)
    board.run(20)          # 20 ms virtual
    print("\n".join(lines[:60]))
    print(f"... total scatter-loader hits: {len(lines)}")


if __name__ == "__main__":
    main()
