"""Start the real CW worker under the stock DISPLAY scheduler."""

import argparse
import struct
import sys
from pathlib import Path

from elftools.elf.elffile import ELFFile
from keystone import KS_ARCH_ARM, KS_MODE_ARM, Ks
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_PC, UC_ARM_REG_R1, UC_ARM_REG_SP

from ftx1vm import Board, addrs
from ftx1vm.devices.stubs import StubDevice

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_ft8_menu import read_display_sfl


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--build-dir", type=Path, required=True)
    args = parser.parse_args()
    image = bytearray(read_display_sfl(args.image))
    with (args.build_dir / "cw.elf").open("rb") as elf:
        symbols = ELFFile(elf).get_section_by_name(".symtab")
        worker = symbols.get_symbol_by_name("cw_worker")[0]["st_value"]
        poll = symbols.get_symbol_by_name("cw_worker_step")[0]["st_value"]
        ui = symbols.get_symbol_by_name("cw_ui_worker")[0]["st_value"]
        report = symbols.get_symbol_by_name("cw_report_packet")[0]["st_value"]
    shim, fixture, descriptor, pkt_addr = 0x606ce000, 0x606ce100, 0x606ce700, 0x606ce800
    assert struct.unpack_from("<I", image, 0xd1428)[0] == 0x60415fc8
    struct.pack_into("<I", image, 0xd1428, shim)
    board = Board(bytes(image), log=lambda _: None)
    board.bus.attach(StubDevice("sd-card-detect", 0xfcfe322c, 2, 0x10))
    cpu = board.core.uc
    asm = Ks(KS_ARCH_ARM, KS_MODE_ARM)

    def write(address, body):
        code, _ = asm.asm(body, address, as_bytes=True)
        cpu.mem_write(address, code)

    write(shim, f"""
        push {{r0,lr}}
        mov r0,#0
        ldr r1,={descriptor}
        ldr r2,=0x60478fb0
        blx r2
        pop {{r0,lr}}
        ldr pc,=0x60415fc8
    """)
    pkt = bytearray(0x13c)
    pkt[0], pkt[9], pkt[33] = 0x20, 0x80, 0x8c
    pkt[-1] = sum(pkt) & 0xFF
    cpu.mem_write(pkt_addr, bytes(pkt))
    write(fixture, f"""
        ldr r4,=0x604797c8
        mov r0,#30
        blx r4
        ldr r5,=0x60935bb4
        mov r1,#0x20
        strb r1,[r5]
        ldr r6,={report}
        ldr r0,={pkt_addr}
        movw r1,#0x13c
        blx r6
        ldr r7,={ui}
        blx r7
        loop:
        mov r0,#100
        blx r4
        b loop
    """)
    cpu.mem_write(descriptor, struct.pack("<7I", 2, 0, fixture, 7, 0x1400, 0x606cec00, 0))

    visited = []
    ticks = []

    def start(uc, _address, _size, _data):
        visited.append(uc.reg_read(UC_ARM_REG_SP))

    def tick(_uc, _address, _size, _data):
        ticks.append(board.core.clock.now_ns)

    def complete_display_io(uc, _address, _size, _data):
        uc.mem_write(uc.reg_read(UC_ARM_REG_R1) + 0x10, bytes(4))

    for address, callback in ((worker, start), (poll, tick), (0x60444f84, complete_display_io)):
        cpu.hook_add(UC_HOOK_CODE, callback, begin=address, end=address)
    cpu.reg_write(UC_ARM_REG_PC, addrs.RESET_ENTRY)
    board.run(1500, lambda vm: vm.stop() if len(ticks) >= 8 else None)
    assert not board.core.stop_reason, board.core.stop_reason
    assert {"scheduler-start", "lcd-ui-init", "task-voice"} <= board.reached.keys()
    assert visited == [0x606d1000] and len(ticks) >= 8 and ticks[-1] > ticks[0], (visited, ticks)
    print("PASS: stock reset, LCD initialization and scheduled native CW worker on its 4 KiB stack")


if __name__ == "__main__":
    main()
