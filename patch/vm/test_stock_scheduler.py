"""Verify the native task ABI and OSTM tick with the stock reset code in RAM."""

import struct
from pathlib import Path

from keystone import KS_ARCH_ARM, KS_MODE_ARM, Ks
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_CPSR, UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_SP

from ftx1vm import Board, addrs


def main():
    root = Path(__file__).resolve().parents[2]
    image = bytearray((root / "work/dec/display/display.bin").read_bytes())
    bootstrap = 0x6052C670
    worker = bootstrap + 0x100
    descriptor = bootstrap + 0x180
    data = bootstrap + 0x200
    asm = Ks(KS_ARCH_ARM, KS_MODE_ARM)

    def assemble(address, program):
        code, _ = asm.asm(program, address, as_bytes=True)
        offset = address - addrs.IMAGE_BASE
        assert image[offset:offset + len(code)] == b"\xff" * len(code)
        image[offset:offset + len(code)] = code

    assemble(bootstrap, f"""
        push {{r4,lr}}
        mov r0,#0
        ldr r1,={descriptor}
        bl 0x60478fb0
        ldr r1,={data}
        str r0,[r1]
        pop {{r4,lr}}
        bx lr
    """)
    assemble(worker, f"""
        ldr r4,={data + 4}
        ldr r5,[r4]
        add r5,r5,#1
        str r5,[r4]
        bl 0x6041669c
        str r0,[r4,#4]
        mov r0,#1
        bl 0x604797c8
        b {worker}
    """)
    # This private test stack lives in VM memory. The test does not reserve this
    # address on the actual radio or run the stock LCD/audio tasks concurrently.
    stack = 0x60760000
    struct.pack_into("<7I", image, descriptor - addrs.IMAGE_BASE,
                     2, 0x1234, worker, 7, 0x10000, stack, 0)
    struct.pack_into("<3I", image, data - addrs.IMAGE_BASE, 0, 0, 0)
    assert struct.unpack_from("<I", image, 0xD1428)[0] == 0x60415FC8
    struct.pack_into("<I", image, 0xD1428, bootstrap)

    board = Board(bytes(image), log=lambda _: None)
    cpu = board.core.uc
    visits = []

    def observe(uc, _address, _size, _data):
        visits.append((uc.reg_read(UC_ARM_REG_R0), uc.reg_read(UC_ARM_REG_SP),
                       uc.reg_read(UC_ARM_REG_CPSR) & 31))

    cpu.hook_add(UC_HOOK_CODE, observe, begin=worker, end=worker)
    cpu.reg_write(UC_ARM_REG_PC, addrs.RESET_ENTRY)
    board.run(110)
    task, calls, now_us = struct.unpack("<3I", board.read_mem(data, 12))
    assert 1 <= task <= 64
    assert visits[0] == (0x1234, stack + 0x10000, 0x1F)
    assert calls == len(visits) >= 10 and now_us >= 90_000
    assert board.irq_stats()["iar"].get(134, 0) >= 10
    assert not board.core.stop_reason
    print(f"PASS: stock µITRON worker {task}, {calls} wakes, OSTM {now_us} us")


if __name__ == "__main__":
    main()
