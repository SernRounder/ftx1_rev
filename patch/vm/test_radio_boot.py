"""Exercise the packaged native image with the stock DISPLAY scheduler."""

import argparse
from collections import Counter
import struct
import sys
from pathlib import Path

from elftools.elf.elffile import ELFFile
from keystone import KS_ARCH_ARM, KS_MODE_ARM, Ks
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R1, UC_ARM_REG_SP

from ftx1vm import Board, addrs
from ftx1vm.devices.stubs import StubDevice

PATCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PATCH))
from test_ft8_menu import read_display_sfl
from test_ft8_arm import recording_16k
from test_ft8_radio_dma import workspace_tx_phase

SHIM = 0x61080000
RESULT = SHIM + 0x800
PCM = 0x61100000


def symbols(path, *names):
    with path.open("rb") as file:
        table = ELFFile(file).get_section_by_name(".symtab")
        return [table.get_symbol_by_name(name)[0]["st_value"] for name in names]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--build-dir", type=Path, default=PATCH / "build/radio")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--replay", action="store_true", help="Also test WAV replay under the stock scheduler")
    mode.add_argument("--contention", action="store_true", help="Feed PCM while a priority-7 task stays runnable")
    parser.add_argument("--expect-starved", action="store_true", help="Verify the old full-ring symptom")
    parser.add_argument("--gaps", action="store_true", help="After WAV replay, force short and long DMA overruns")
    args = parser.parse_args()
    if args.expect_starved and not args.contention:
        parser.error("--expect-starved requires --contention")
    if args.gaps and not args.replay:
        parser.error("--gaps requires --replay")
    image = bytearray(read_display_sfl(args.image))
    has_native_tx = image[0xc9d00:0xc9d04] != bytes.fromhex("55feffeb")
    version, = struct.unpack_from("<I", image, 0x12C674)
    live_elf = args.build_dir / ("ft8_rx.elf" if version >= 28 else "ft8_radio.elf")
    if version >= 28:
        ui, capture, report = symbols(live_elf, "vector_ft8_ui_worker", "vector_ft8_live_capture", "ft8_radio_report_packet")
    else:
        ui, capture = symbols(live_elf, "ft8_ui_worker", "ft8_live_capture")
        report = 0
    workspace, epoch = symbols(live_elf, "workspace", "epoch")
    worker, watchdog = symbols(args.build_dir / "ft8_rx.elf", "ft8_radio_worker_entry", "ft8_radio_watchdog_entry")
    stock_task = 0x60415FC8
    assert struct.unpack_from("<I", image, 0xD1428)[0] == stock_task
    struct.pack_into("<I", image, 0xD1428, SHIM)
    board = Board(bytes(image), log=lambda _: None)
    cpu = board.core.uc
    with (args.build_dir / "ft8_rx.elf").open("rb") as file:
        table = ELFFile(file).get_section_by_name(".symtab")
        vfp_required = bool(table.get_symbol_by_name("ft8_vfp_candidate"))
        entries = table.get_symbol_by_name("finish_native")
    if vfp_required:
        cpu.cpr_write(15, 0, 1, 1, 2, 3, False, 3 << 10)
    decode_yields = []
    if args.replay:
        finish_start, finish_size = ((entries[0]["st_value"] & ~1, entries[0]["st_size"])
                                     if entries else (0, 0))

        def observe_decode_delay(uc, _address, _size, _data):
            caller = uc.reg_read(UC_ARM_REG_LR) & ~1
            if finish_start <= caller < finish_start + finish_size:
                decode_yields.append(caller)

        cpu.hook_add(UC_HOOK_CODE, observe_decode_delay, begin=0x604797c8, end=0x604797c8)
    assert addrs.IMAGE_BASE + len(image) <= SHIM
    board.core.map_ram(SHIM, 0x3000, quiet=True)
    block_size = 1600
    replay = ""
    view_offset = None
    if args.replay or args.contention:
        # The VM has no SDHI transport. Keep the active-low card-detect input
        # in the no-card state so stock does not wait for nonexistent SD I/O.
        board.bus.attach(StubDevice("sd-card-detect", 0xFCFE322C, 2, 0x10))
    if args.replay:
        samples = recording_16k(PATCH.parent / "downloads/210703_133430.wav")
        frames = b"".join(struct.pack("<HH", block_size, 0) + samples[i:i + block_size].tobytes()
                          for i in range(0, len(samples), block_size))
        board.core.map_ram(PCM, len(frames) + (0x1000 if args.gaps else 0), quiet=True)
        cpu.mem_write(PCM, frames)
        replay = f"""
            ldr r9,={PCM}
            ldr r10,={PCM + len(frames)}
            ldr r11,={capture}
        replay:
            mov r0,r9
            blx r11
            movw r0,#{block_size * 2 + 4}
            add r9,r9,r0
        wait_for_reader:
            mov r0,#1
            blx r4
            ldr r0,[r8]
            ldm r0,{{r1,r2}}
            sub r1,r1,r2
            cmp r1,#6
            bhs wait_for_reader
            str r9,[r5,#28]
            cmp r9,r10
            blo replay
            mov r0,#200
            blx r4
            mov r0,#1
            str r0,[r5,#24]
        """
        if args.gaps:
            view_offset = workspace_tx_phase(live_elf, b"view", structure=b"workspace")
            scan_offset = workspace_tx_phase(live_elf, b"rx_scans")
            rows_offset = workspace_tx_phase(live_elf, b"rows")
            samples_offset = workspace_tx_phase(live_elf, b"samples", structure=b"workspace")
            silence = (PCM + len(frames) + 31) & ~31
            cpu.mem_write(silence, struct.pack("<HH", block_size, 0) + bytes(2 * block_size))
            replay += f"""
                ldr r10,={silence}
                blx r7
                ldr r3,[r8]
                ldr r2,={view_offset + scan_offset}
                ldr r0,[r3,r2]
                str r0,[r5,#60]
                mov r11,#10
                bl burst
                mov r0,#60
                blx r4
                mov r11,#10
            quiet:
                mov r0,r10
                ldr r3,={capture}
                blx r3
                mov r0,#5
                blx r4
                subs r11,r11,#1
                bne quiet
                mov r0,#50
                blx r4
                blx r7
                ldr r3,[r8]
                ldr r2,={view_offset + scan_offset}
                ldr r0,[r3,r2]
                str r0,[r5,#64]
                ldr r2,={samples_offset}
                ldr r0,[r3,r2]
                str r0,[r5,#76]
                mov r0,#1
                str r0,[r5,#72]
                mov r11,#14
                bl burst
                mov r0,#60
                blx r4
                mov r11,#2
                bl burst
                mov r0,#20
                blx r4
                blx r7
                ldr r3,[r8]
                ldr r2,={samples_offset}
                ldr r0,[r3,r2]
                str r0,[r5,#80]
                mov r0,#1
                str r0,[r5,#68]
                b after_gaps
            burst:
                push {{r9,lr}}
                mrs r9,cpsr
                cpsid i
            send:
                mov r0,r10
                ldr r3,={capture}
                blx r3
                subs r11,r11,#1
                bne send
                msr cpsr_c,r9
                pop {{r9,pc}}
            after_gaps:
            """
    elif args.contention:
        board.core.map_ram(PCM, 0x1000, quiet=True)
        cpu.mem_write(PCM, struct.pack("<2H", 800, 0) + bytes(1600))
        replay = f"""
            mov r0,#0
            ldr r1,={SHIM + 0xA00}
            ldr r2,=0x60478fb0
            blx r2
            str r0,[r5,#44]
            mov r9,#24
            ldr r10,={PCM}
            ldr r11,={capture}
        stress:
            mov r0,r10
            blx r11
            mov r0,#2
            blx r4
            subs r9,r9,#1
            bne stress
            ldr r0,[r8]
            ldm r0,{{r1,r2}}
            str r1,[r5,#48]
            str r2,[r5,#52]
        """
    asm = Ks(KS_ARCH_ARM, KS_MODE_ARM)

    def assemble(address, program):
        data, _ = asm.asm(program, address, as_bytes=True)
        cpu.mem_write(address, data)

    if args.contention:
        assemble(SHIM + 0x400, f"""
            ldr r0,={RESULT + 56}
            mov r1,#1
            str r1,[r0]
        busy:
            b busy
        """)
        cpu.mem_write(SHIM + 0xA00, struct.pack("<7I", 2, 0, SHIM + 0x400, 7, 0x100, SHIM + 0xB00, 0))

    assemble(SHIM, f"""
        push {{r0,lr}}
        mov r0,#0
        ldr r1,={SHIM + 0x700}
        ldr r2,=0x60478fb0
        blx r2
        ldr r1,={RESULT}
        str r0,[r1,#12]
        pop {{r0,lr}}
        ldr pc,={stock_task}
    """)
    pkt = bytearray(0x13c)
    pkt[0], pkt[9], pkt[33] = 0x20, 0x80, 0x8a
    pkt[-1] = sum(pkt) & 0xFF
    pkt_addr = SHIM + 0x480
    cpu.mem_write(pkt_addr, bytes(pkt))
    assemble(SHIM + 0x100, f"""
        ldr r4,=0x604797c8
        ldr r5,={RESULT}
        str sp,[r5,#16]
        mov r0,#30
        blx r4
        ldr r0,=0x60935bb4
        mov r1,#0x20
        strb r1,[r0]
        ldr r9,={report}
        ldr r0,={pkt_addr}
        movw r1,#0x13c
        blx r9
        ldr r7,={ui}
        blx r7
        ldr r8,={workspace}
        ldr r0,[r8]
        str r0,[r5]
        ldr r3,=0x6042387c
        movw r0,#24
        movw r1,#260
        add r2,r5,#32
        blx r3
        str r0,[r5,#36]
        blx r7
        ldr r0,[r8]
        str r0,[r5,#20]
        {replay}
        mov r0,#10
        blx r4
        ldr r3,=0x6042387c
        mov r0,#65
        movw r1,#450
        add r2,r5,#32
        blx r3
        str r0,[r5,#40]
        mov r1,r0
        ldr r6,=0x604232e0
        mov r0,#1
        blx r6
        blx r7
        mov r0,#10
        blx r4
        blx r7
        ldr r0,[r8]
        str r0,[r5,#4]
        mov r0,#1
        str r0,[r5,#8]
    wait:
        mov r0,#100
        blx r4
        b wait
    """)
    fixture_priority = 6 if args.contention else 7
    cpu.mem_write(SHIM + 0x700, struct.pack("<7I", 2, 0, SHIM + 0x100, fixture_priority,
                                           0x1400, SHIM + 0xC00, 0))
    stacks = {}

    def observe(uc, address, _size, _data):
        stacks[address] = uc.reg_read(UC_ARM_REG_SP)

    for address in (worker & ~1, watchdog & ~1):
        cpu.hook_add(UC_HOOK_CODE, observe, begin=address, end=address)

    def complete_display_io(uc, _address, _size, _data):
        # Display hardware is absent in this VM. Complete the stock wait
        # without stubbing task creation, scheduling, allocation or the FT8 code.
        uc.mem_write(uc.reg_read(UC_ARM_REG_R1) + 0x10, b"\0" * 4)

    cpu.hook_add(UC_HOOK_CODE, complete_display_io, begin=0x60444F84, end=0x60444F84)
    cpu.reg_write(UC_ARM_REG_PC, addrs.RESET_ENTRY)
    paths = Counter()
    decoded = None
    after_gaps = None
    before_resync = None

    def inspect(vm):
        nonlocal decoded, after_gaps, before_resync
        pc = vm.regs()["pc"]
        if pc != addrs.IRQ_ENTRY:
            paths[hex(pc)] += 1
        if decoded is None and vm.read_mem(RESULT + 24, 4) == b"\1\0\0\0":
            opened, = struct.unpack("<I", vm.read_mem(RESULT, 4))
            decoded = vm.read_mem(opened, 2300)
        if view_offset is not None:
            view = struct.unpack("<I", vm.read_mem(RESULT, 4))[0] + view_offset
            if after_gaps is None and vm.read_mem(RESULT + 68, 4) == b"\1\0\0\0":
                after_gaps = vm.read_mem(view, rows_offset + 6 * 44)
            if before_resync is None and vm.read_mem(RESULT + 72, 4) == b"\1\0\0\0":
                before_resync = vm.read_mem(view, rows_offset + 6 * 44)
        if vm.read_mem(RESULT + 8, 4) == b"\1\0\0\0":
            vm.stop()

    if args.replay:
        board.run(9500 if args.gaps else 7000, inspect)
        assert decoded is not None, (board.core.stop_reason, board.regs(), board.irq_stats(),
                                     board.read_mem(RESULT, 32).hex(), paths.most_common(8))
        for message in (b"K1JT HA0DU KN07", b"CQ F5RXL IN94", b"XE2X HA2NP RR73"):
            assert message in decoded, message
        print("PASS: decoded 3 WAV messages on the native worker")
        if decode_yields:
            print(f"PASS: {len(decode_yields)} calls to the stock RTOS delay inside decoding")
        if args.gaps:
            before, after = struct.unpack("<2I", board.read_mem(RESULT + 60, 8))
            assert 0 < before <= after, (before, after)
            short_window, long_window = struct.unpack("<2I", board.read_mem(RESULT + 76, 8))
            # Ten frames in the eight-frame production ring lose 200 ms.
            # A window larger than the 20 new frames retains older PCM.
            assert short_window > 20 * block_size and 0 < long_window <= 12 * block_size, (
                short_window, long_window,
            )
            assert after_gaps and before_resync
            count, = struct.unpack_from("<I", after_gaps, 8)
            assert 0 < count <= 8
            assert struct.unpack_from("<I", before_resync, 8)[0] == count
            row_bytes = slice(rows_offset, rows_offset + 6 * 44)
            assert after_gaps[row_bytes] == before_resync[row_bytes]
            print(f"PASS: short overrun retained {short_window} PCM; long overrun rebuilt {long_window} PCM and kept decoded rows")
    else:
        board.run(1600 if args.contention else 1400)
    assert not board.core.stop_reason, board.core.stop_reason
    assert {"scheduler-start", "lcd-ui-init", "task-voice"} <= board.reached.keys()
    opened, closed, finished, created, test_stack = struct.unpack("<3IiI", board.read_mem(RESULT, 20))
    assert 0x606E0000 <= opened < 0x607C0000, (
        hex(opened), hex(closed), finished, created, hex(test_stack), board.regs(),
        stacks, board.core.invalid_sites,
    )
    assert finished == 1 and closed == 0, (
        hex(opened), hex(closed), finished, stacks, board.regs(), board.read_mem(epoch, 4).hex(),
        board.read_mem(workspace, 4).hex(), board.irq_stats(),
    )
    assert struct.unpack("<I", board.read_mem(epoch, 4))[0] == 2
    assert struct.unpack("<I", board.read_mem(RESULT + 20, 4))[0] == opened
    assert struct.unpack("<2I", board.read_mem(RESULT + 36, 8)) == (0x1135, 0x1134)
    expected_stacks = {} if args.expect_starved else {worker & ~1: 0x606D8000}
    if version < 10 or has_native_tx:
        expected_stacks[watchdog & ~1] = 0x606D9000
    assert stacks == expected_stacks, stacks
    if args.contention:
        busy_id, queued, read, busy_ran = struct.unpack("<4I", board.read_mem(RESULT + 44, 16))
        assert 1 <= busy_id <= 64 and busy_ran == 1
        if args.expect_starved:
            assert (queued, read) == (10, 0), (queued, read)
        else:
            assert queued > 10 and read > 10, (queued, read)
        print(f"PASS: under priority-7 contention, RX={queued}, OUT={read}")
    assert struct.unpack("<I", board.read_mem(0x607C50BC, 4))[0] > 0
    assert all(cmd not in (0xE7, 0xE8) or (cmd, data) == (0xE8, b"\xf8FT8\x02\x8a\0\0")
               for cmd, data in board.main.frames)
    print(f"PASS: FT8 survived stock popup dismissal and released {opened:#x} after BACK")


if __name__ == "__main__":
    main()
