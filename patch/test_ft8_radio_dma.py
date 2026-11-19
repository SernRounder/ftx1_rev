"""Exercise the patched DISPLAY DMA entry points with simulated CH3 registers."""

import argparse
import struct
from array import array
from pathlib import Path

from elftools.elf.elffile import ELFFile
from unicorn import UC_ARCH_ARM, UC_HOOK_CODE, UC_MODE_ARM, Uc
from unicorn.arm_const import (
    UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
    UC_ARM_REG_R3, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_SP,
)

from test_ft8_menu import read_display_sfl


def radio_layout(path):
    with path.open("rb") as file:
        elf = ELFFile(file)
        table = elf.get_section_by_name(".symtab")
        radio = table.get_symbol_by_name("radio")[0]["st_value"]
        io = table.get_symbol_by_name("io")[0]["st_value"]
        watchdog = table.get_symbol_by_name("watchdog_step")[0]["st_value"]
        for unit in elf.get_dwarf_info().iter_CUs():
            for die in unit.iter_DIEs():
                if die.tag == "DW_TAG_variable" and die.attributes.get("DW_AT_name"):
                    if die.attributes["DW_AT_name"].value == b"radio":
                        layout = die.get_DIE_from_attribute("DW_AT_type")
                        fields = {member.attributes["DW_AT_name"].value.decode():
                                  member.attributes["DW_AT_data_member_location"].value
                                  for member in layout.iter_children() if member.tag == "DW_TAG_member"}
                        return radio, io, watchdog, fields
    raise AssertionError("Missing radio layout")


def symbol(path, name):
    with path.open("rb") as file:
        return ELFFile(file).get_section_by_name(".symtab").get_symbol_by_name(name)[0]["st_value"]


def workspace_tx_phase(path, member=b"tx_phase", *, structure=None):
    with path.open("rb") as file:
        elf = ELFFile(file)
        for unit in elf.get_dwarf_info().iter_CUs():
            for die in unit.iter_DIEs():
                if die.tag != "DW_TAG_member" or "DW_AT_name" not in die.attributes:
                    continue
                if die.attributes["DW_AT_name"].value != member:
                    continue
                if structure is not None:
                    name = die.get_parent().attributes.get("DW_AT_name")
                    if name is None or name.value != structure:
                        continue
                return die.attributes["DW_AT_data_member_location"].value
    raise AssertionError(f"Missing workspace member {member!r}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--plugin", type=Path, help="Exercise the separately built queue module")
    args = parser.parse_args()
    image = read_display_sfl(args.image)
    radio, io, watchdog, fields = radio_layout(args.build_dir / "ft8_rx.elf")
    base, regs = 0x60400000, 0xE8200000
    stack, stop, pcm, synth = 0x61110000, 0x61110000, 0x61116000, 0x61117000
    hann_start, dma = 0x603D0880, 0x603D5880
    cpu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    cpu.mem_map(0x60000000, 0xA00000)
    cpu.mem_map(regs, 0x1000)
    cpu.mem_map(0x61100000, 0x18000)
    cpu.mem_write(base, image)
    # This isolated harness has no stock interrupt controller or kernel.
    for address in (0x604BFA8C, 0x604BFAAC):
        cpu.mem_write(address, struct.pack("<I", 0xE12FFF1E))

    def write(address, value):
        cpu.mem_write(address, struct.pack("<I", value))

    def read(address):
        return struct.unpack("<I", cpu.mem_read(address, 4))[0]

    def state(name, value):
        write(radio + fields[name], value)

    def call(address, *params, end=stop, instruction_budget=20_000_000):
        for reg, value in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3), params):
            cpu.reg_write(reg, value)
        cpu.reg_write(UC_ARM_REG_R6, regs)
        cpu.reg_write(UC_ARM_REG_SP, stack)
        cpu.reg_write(UC_ARM_REG_LR, stop)
        cpu.emu_start(address, end, count=instruction_budget)
        assert cpu.reg_read(UC_ARM_REG_PC) == end, (hex(address), hex(cpu.reg_read(UC_ARM_REG_PC)))
        return cpu.reg_read(UC_ARM_REG_R0)

    def select(source=0x6095C500):
        call(0x604452B4, source, end=0x604452B8)
        return read(regs + 0xC0)

    silence, dma_size, completion_flag = 0x6095C500, 0x2260, 0x607C500C
    stock_source = 0x6095E760
    assert select() == silence
    assert select(stock_source) == stock_source

    # Open the receiver first so the DMA queue is overlaid on its actual arena.
    elf = args.build_dir / "ft8_rx.elf"
    with elf.open("rb") as file:
        required = ELFFile(file).get_section_by_name(".symtab").get_symbol_by_name("ft8_vfp_candidate")
    if required:
        from unicorn.arm_const import UC_ARM_REG_CPSR
        cpu.reg_write(UC_ARM_REG_CPSR, 0x1f)
        cpu.cpr_write(15, 0, 12, 0, 0, 0, False, base)
        cpu.cpr_write(15, 0, 1, 1, 2, 3, False, 3 << 10)
        for address in (0x60402fa8, 0x60402efc):
            write(address, 0xe12fff1e)
        call(symbol(elf, "ft8_fft_prepare"))
    open_rx = read(0x606C2FC0 + 16)
    assert call(open_rx, 0x609EBE30, 0x141D0, instruction_budget=200_000_000)
    hann = bytes(cpu.mem_read(hann_start, dma - hann_start))
    assert any(hann)
    cpu.mem_write(dma, b"\xA5" * 17632)

    # Emulate MAIN status packets at the validated stock packet entry point.
    timestamp, packet = 0x61111000, 0x61111010
    cpu.mem_write(0x6041669C, struct.pack("<4I", 0xE59F0004, 0xE5900000, 0xE12FFF1E, timestamp))
    write(timestamp, 1000)
    sent = []

    def send(uc, address, size, user):
        ptr, length = uc.reg_read(UC_ARM_REG_R0), uc.reg_read(UC_ARM_REG_R1)
        sent.append(bytes(uc.mem_read(ptr, length)))

    cpu.mem_write(0x60414A1C, struct.pack("<I", 0xE12FFF1E))
    cpu.hook_add(UC_HOOK_CODE, send, begin=0x60414A1C, end=0x60414A1C)
    cpu.mem_write(0x604C965C, struct.pack("<I", 0xE12FFF1E))

    def status(value, tx_frequency=0, power=0, spa=0):
        frame = bytearray(0x13c)
        frame[0] = 0x20
        frame[9] = value
        struct.pack_into(">I", frame, 14, tx_frequency)
        frame[30:34] = bytes((0x8c, 0x32, power, spa))
        frame[-1] = sum(frame) & 0xff
        cpu.mem_write(packet, bytes(frame))
        call(0x604C9D00, 0, packet, len(frame), end=0x604C9D04)
        expected = frame[:]
        expected[9] = 0
        expected[32:34] = b"\0\0"
        expected[-1] = (frame[-1] - value - power - spa) & 255
        assert bytes(cpu.mem_read(packet, len(frame))) == expected

    state("dma", dma)
    start, submit, stop_tx = (read(io + offset) for offset in (4, 8, 16))
    state("active", 1)
    assert call(start, 13500) == 0
    status(0)
    assert call(start, 13500) == 0  # stock MAIN never advertises this protocol
    status(0x80)
    state("active", 0)
    assert call(start, 13500) == 0
    # Opening FT8 suffices even when the original MODE popup has dismissed.
    state("active", 1)
    state("last_heartbeat", 1000)
    assert call(start, 13500) == 1
    call(watchdog)
    assert sent == [b"\xe8\xf8FT8\x01\x01\0\0"]
    status(0x81)
    call(watchdog)
    assert read(radio + fields["lease"]) == 2
    # A valid confirmation may arrive after the freshness window measured
    # from START. Its age is measured from receipt, not from START.
    write(timestamp, 201000)
    state("last_heartbeat", 201000)
    status(0xA5)
    call(watchdog)
    assert read(radio + fields["lease"]) == 3
    for _ in range(6):
        assert call(submit, pcm, 800) == 1
    assert select() == silence
    encode, tx_open, tx_next = (read(0x606C2FC0 + offset) for offset in (40, 48, 52))
    cpu.mem_write(pcm, b"CQ W9XYZ FN31\0")
    assert call(encode, pcm, pcm + 0x800) == 1
    assert call(tx_open, synth, 0x1000, pcm + 0x800, 1000) == synth
    expected = bytearray()
    actual = bytearray()
    remaining = 202240
    completed_status = 0x60  # CHSTAT.END | CHSTAT.TC from the preceding stock transfer.
    for index in range(253):
        count = call(tx_next, synth, pcm, 800)
        assert count == min(800, remaining)
        remaining -= count
        block = bytes(cpu.mem_read(pcm, count * 2))
        expected.extend(block)
        cpu.mem_write(pcm + count * 2, bytes(1600 - count * 2))
        assert call(submit, pcm, 800) == 1
        if index == 0:
            assert select() == silence  # no DSP credit yet
            cpu.mem_write(0x607C4012, struct.pack("<H", 500))
            write(regs + 0xE4, completed_status | 4)
            assert select() == silence  # previous transfer still active
            write(regs + 0xE4, completed_status | 0x10)
            assert select() == silence  # channel error still blocks a new source
            write(regs + 0xE4, completed_status)
            assert select(stock_source) == stock_source
        # Run the original selection logic before reaching the patched store.
        cpu.reg_write(UC_ARM_REG_R5, 0x607C4010)
        call(0x60445288, end=0x604452B8)
        frame = read(regs + 0xC0)
        assert frame == dma + (index % 2) * dma_size
        assert struct.unpack("<2H", cpu.mem_read(frame, 4)) == (800, 0x1234)
        actual.extend(cpu.mem_read(frame + 4, count * 2))
        assert not any(cpu.mem_read(frame + 4 + count * 2, dma_size - 4 - count * 2))
        assert select() == silence  # in-flight descriptor cannot be selected again
        write(completion_flag, 0)
        call(0x60463DB4)
        assert read(completion_flag) == 1
    assert not remaining and actual == expected
    assert select() == silence

    assert call(submit, pcm, 800) == 1
    pending = select()
    assert pending != silence
    assert call(submit, pcm, 800) == 1
    assert call(stop_tx) == 0  # simulated MAIN still owns the lease
    call(watchdog)
    assert sent[-1] == b"\xe8\xf8FT8\0\x01\0\0"
    assert read(radio + fields["borrowed"]) == pending
    assert select() == silence
    write(regs + 0xE4, 4)
    call(0x60463DB4)
    assert read(radio + fields["borrowed"]) == pending
    write(regs + 0xE4, 0)
    call(0x60463DB4)
    assert not read(radio + fields["borrowed"])
    assert select() == silence
    assert bytes(cpu.mem_read(hann_start, dma - hann_start)) == hann
    print("PASS: 202240 samples through CH3 with END/TC set; busy and error still block a new source")

    # Exercise the live worker with a modeled RTC slot and MAIN.
    live = 0x6052C670
    timing = read(live + 4) >= 32
    stage1 = args.build_dir / ("ft8_rx.elf" if read(live + 4) >= 28 else "ft8_radio.elf")
    bind, sync, poll, arm, attach, slot = (read(live + offset) for offset in (16, 24, 28, 44, 48, 52))
    write(timestamp, 251000)
    status(0x84)
    call(watchdog)
    assert call(stop_tx) == 1
    assert call(bind, 0x61100000, read(live + 8)) == 1
    assert call(attach, io) == 1
    write(symbol(stage1, "epoch"), 1)
    assert call(sync, 0, 0, instruction_budget=200_000_000) == 1
    cpu.mem_write(pcm, b"CQ W9XYZ FN31\0")
    if timing:
        assert call(arm, pcm, 1000) == 0
        zero = pcm + 64
        cpu.mem_write(zero, b"0\0")
        assert call(symbol(args.build_dir / "ft8_rx.elf", "ft8_radio_set_offset"), zero, 1) == 1
    assert call(arm, pcm, 1000) == 1
    call(poll)
    uses_slot_poll = read(live + 4) >= 14
    if uses_slot_poll:
        step = symbol(args.build_dir / "ft8_rx.elf", "poll_slot")
        last, previous = 0x61111500, 0x61111504
        rtc_reads = []
        bcd_second = 0x14

        def rtc(uc, _address, _size, _data):
            rtc_reads.append(read(timestamp))
            uc.mem_write(uc.reg_read(UC_ARM_REG_R0),
                         bytes([0x26, 0x11, 0x12, 0, 0x16, 0x42, bcd_second]))

        cpu.mem_write(0x604135D4, struct.pack("<I", 0xE12FFF1E))
        cpu.hook_add(UC_HOOK_CODE, rtc, begin=0x604135D4, end=0x604135D4)
        write(previous, 0xFFFFFFFF)
        if timing:
            call(symbol(args.build_dir / "ft8_rx.elf", "toggle_tx_slot"))
        write(timestamp, 900_000)
        call(step, 900_000, last, previous)
        assert read(radio + fields["tx_wait_s"]) == (0 if timing else 1)
        assert read(radio + fields["lease"]) == 0
        bcd_second = 0x15
        write(timestamp, 1_000_000)
        state("last_heartbeat", 1_000_000)
        status(0x84)
        call(step, 1_000_000, last, previous)
        assert rtc_reads == [900_000, 1_000_000]
        assert read(radio + fields["lease"]) == 1
        if timing:
            elf = args.build_dir / "ft8_rx.elf"
            delta = symbol(elf, "ft8_radio_delta")
            offset = symbol(elf, "ft8_radio_set_offset")
            assert call(delta, 14150, pcm) == 2**32 - 1800 and read(pcm) == 0
            cpu.mem_write(pcm, b"-1.8\0")
            assert call(offset, pcm, 4) == 1
            assert call(delta, 14150, pcm) == 0 and read(pcm) == 0
            assert call(delta, 29150, pcm) == 0 and read(pcm) == 1
            cpu.mem_write(pcm, b"0\0")
            assert call(offset, pcm, 1) == 1
            print("PASS: a -1.8 s offset cancels -1.8 s residual and preserves the RTC slot labels")
    else:
        write(timestamp, 1_000_000)
        state("last_heartbeat", 1_000_000)
        status(0x84)
        assert call(slot, 1000) == 1
    call(watchdog)
    assert sent[-1] == b"\xe8\xf8FT8\x01\x02\0\0"
    status(0x89)
    call(watchdog)

    cpu.mem_write(0x604450B4, struct.pack("<I", 0xE12FFF1E))
    rx_frame = 0x61112500
    cpu.mem_write(rx_frame, struct.pack("<HH", 768, 0x1234) + bytes(1536))
    actual = bytearray()
    next_sequence = read(live + 20)
    rx_sequence = call(next_sequence)
    write(regs + 0xE4, completed_status)
    for block in range(1, 259):
        instant = 1_000_000 + block * 50_000
        write(timestamp, instant)
        state("last_heartbeat", instant)
        status(0x89 | (0x20 if block % 2 else 0))
        call(watchdog)
        call(0x60445170, rx_frame, end=0x60445174)
        call(poll)
        frame = select()
        if block < 6:
            assert frame == silence
        else:
            assert frame != silence
            actual.extend(cpu.mem_read(frame + 4, 1600))
            call(0x60463DB4)
    assert actual[:len(expected)] == expected and not any(actual[len(expected):])
    if read(live + 4) >= 21:
        assert call(next_sequence) == rx_sequence
    write(timestamp, 13_950_000)
    state("last_heartbeat", 13_950_000)
    status(0x89)
    call(poll)
    call(watchdog)
    assert sent[-1] == b"\xe8\xf8FT8\0\x02\0\0"
    write(timestamp, 14_000_000)
    status(0x88)
    call(watchdog)
    call(poll)
    call(0x60445170, rx_frame, end=0x60445174)
    if read(live + 4) >= 21:
        assert call(next_sequence) == rx_sequence + 1
    assert call(poll) == 1
    assert call(read(live + 60)) == 1  # rolling RX synchronized after DMA release
    print("PASS: staged TX NEXT, all 253 PCM blocks, confirmed STOP, and return to rolling RX")

    if uses_slot_poll:
        phase = read(symbol(stage1, "workspace")) + workspace_tx_phase(stage1)
        before = len(sent)
        assert call(arm, pcm, 1000) == 1
        call(poll)
        timeout = 46_000_000 if timing else 31_000_000
        write(timestamp, timeout - 1000)
        call(step, timeout - 1000, last, previous)
        call(poll)
        assert read(phase) == 1
        write(timestamp, timeout)
        call(poll)
        assert read(phase) == 7
        call(watchdog)
        assert len(sent) == before
        assert call(arm, pcm, 1000) == 1
        call(poll)
        assert read(phase) == 1
        print("PASS: RTC edge starts TX, frozen RTC times out, and TX NEXT retries")

        if read(live + 4) >= 16:
            # Replay a keyed transmitter whose DSP frames grant no TX credit.
            # Two blocks fit in the queue. The third fails at 400 ms.
            start_at = timeout
            state("last_heartbeat", start_at)
            status(0x88)
            assert call(slot, start_at // 1000)
            call(watchdog)
            assert sent[-1] == b"\xe8\xf8FT8\x01\x03\0\0"
            status(0x8D)
            call(watchdog)
            cpu.mem_write(0x607C4012, b"\0\0")
            for block in range(1, 9):
                instant = start_at + block * 50_000
                write(timestamp, instant)
                state("last_heartbeat", instant)
                status(0x8D)
                call(watchdog)
                call(poll)
                assert select() == silence
            call(watchdog)
            assert sent[-1] == b"\xe8\xf8FT8\0\x03\0\0"
            write(timestamp, start_at + 450_000)
            status(0x8C)
            call(watchdog)
            call(poll)
            assert read(phase) == 5
            fault = symbol(args.build_dir / "ft8_rx.elf", "tx_fault")
            assert call(fault) == 8  # FT8_RADIO_NO_CREDIT
            call(0x60445170, rx_frame, end=0x60445174)
            assert call(poll) == 1
            assert call(read(live + 60)) == 1
            assert read(phase) == 5 and call(fault) == 8
            assert call(arm, pcm, 1000) == 1
            call(poll)
            assert read(phase) == 1
            print("PASS: reports a DMA credit stall after returning to RX and permits TX NEXT retry")

            start_at += 15_000_000
            write(timestamp, start_at)
            state("last_heartbeat", start_at)
            status(0x8C)
            assert call(slot, start_at // 1000) == 1
            call(watchdog)
            write(timestamp, start_at + 275_000)
            state("last_heartbeat", start_at + 275_000)
            status(0x91)
            call(watchdog)
            call(watchdog)
            assert sent[-2:] == [b"\xe8\xf8FT8\x01\x04\0\0", b"\xe8\xf8FT8\0\x04\0\0"]
            assert call(fault) == 2  # FT8_RADIO_KEY_TIMEOUT
            print("PASS: 200 ms KEYED accepted and 275 ms KEYED still triggers the key timeout")

            status(0x4C)
            assert call(fault) == 2  # A diagnostic from the prior token is ignored.
            status(0x53)
            assert call(fault) == 14
            status(0x70)
            assert call(fault) == 14  # MAIN preserves the report after returning to RX.
            status(0xD0)
            assert call(fault) == 15
            print("PASS: MAIN PTT and RF diagnostic tags survive return to RX for the active token")

            if "tx_frequency" in fields:
                qso = symbol(args.build_dir / "ft8_rx.elf", "qso_event")
                write(symbol(args.build_dir / "ft8_rx.elf", "worked"), 0x60760000)
                cpu.mem_write(0x607C01C4, b"\x28")  # Local time UTC+08:00.
                records = []
                history = bytearray()
                log_position = 0
                log_fail = False
                file_handle = 0x60764000

                def file_io(uc, _address, _size, operation):
                    nonlocal log_position
                    first = uc.reg_read(UC_ARM_REG_R0)
                    second = uc.reg_read(UC_ARM_REG_R1)
                    if operation == "open":
                        path = b"I:\\FTX-1\\FT8LOG.ADI\0"
                        assert bytes(uc.mem_read(first, len(path))) == path
                        mode = bytes(uc.mem_read(second, 3))
                        assert mode in (b"ab\0", b"rb\0")
                        if mode == b"rb\0":
                            log_position = 0
                            write(file_handle + 0x28, 0)
                            write(file_handle + 0x2c, len(history) + sum(map(len, records)))
                        result = file_handle
                    elif operation == "write":
                        assert second == 1 and uc.reg_read(UC_ARM_REG_R3) == file_handle
                        result = uc.reg_read(UC_ARM_REG_R2)
                        records.append(bytes(uc.mem_read(first, result)))
                    elif operation == "read":
                        assert second == 1 and uc.reg_read(UC_ARM_REG_R3) == file_handle
                        data = history + b"".join(records)
                        chunk = b"" if log_fail else data[log_position:log_position + uc.reg_read(UC_ARM_REG_R2)]
                        if chunk:
                            uc.mem_write(first, bytes(chunk))
                        result = len(chunk)
                        log_position += result
                        write(file_handle + 0x28, log_position)
                    else:
                        assert first == file_handle
                        result = 0
                    uc.reg_write(UC_ARM_REG_R0, result)

                file_hooks = {}
                for address, operation in ((0x6046995C, "open"), (0x6046B51C, "write"),
                                           (0x6046A8F8, "read"), (0x60469E90, "close")):
                    cpu.mem_write(address, struct.pack("<I", 0xE12FFF1E))
                    file_hooks[address] = cpu.hook_add(UC_HOOK_CODE, file_io, operation, begin=address, end=address)

                def message(text, received=0):
                    cpu.mem_write(pcm, text + b"\0")
                    call(qso, pcm, 0, received, 1500)

                def capture_tx(power, spa=0):
                    now = read(timestamp)
                    state("lease", 2)
                    state("requested_at", now)
                    state("last_heartbeat", now)
                    state("stop_requested", 0)
                    state("lease_us", 13_500_000)
                    state("lease_start", now)
                    status(0x91, 7_074_000, power, spa)
                    call(watchdog)
                    assert read(radio + fields["lease"]) == 3
                    state("lease", 0)
                    status(0x90)

                capture_tx(37)
                message(b"CQ W1AW FN31")
                message(b"W1AW W9XYZ 73", 1)
                assert not records
                message(b"W9XYZ W1AW 73")
                message(b"W9XYZ W1AW 73")
                assert len(records) == 1
                assert b"<CALL:5>W9XYZ<QSO_DATE:8>20261112" in records[0]
                assert b"<FREQ:8>7.075500<TX_PWR:3>3.7<STATION_CALLSIGN:4>W1AW<eor>\n" in records[0]
                capture_tx(50, spa=1)
                message(b"K1ABC W1AW RRR")
                message(b"K1ABC W1AW RR73", 1)
                assert len(records) == 1
                message(b"W1AW K1ABC RR73", 1)
                message(b"W1AW K1ABC RR73", 1)
                assert len(records) == 2 and records[1].startswith(b"<CALL:5>K1ABC")
                assert b"<TX_PWR:4>50.0" in records[1]
                recent = symbol(args.build_dir / "ft8_rx.elf", "ft8_radio_recent_qsos")
                call(recent, pcm)
                assert bytes(cpu.mem_read(pcm, 6)) == b"W9XYZ\0"
                assert bytes(cpu.mem_read(pcm + 34, 6)) == b"K1ABC\0"
                utc = bytes(cpu.mem_read(pcm + 14, 19))
                assert utc == b"2026-11-12 08:42:15"
                print("PASS: completed 73 and matching RRR/RR73 append ADIF; CQ and duplicate endings do not")

            if "audio_boundary" in fields:
                measure = symbol(args.build_dir / "ft8_rx.elf", "ft8_radio_audio_slot")
                rows = bytearray(5 * 44)
                for i, offset in enumerate((2600, 1000, 920, 1080, 2520)):
                    struct.pack_into("<h", rows, i * 44 + 38, offset)
                cpu.mem_write(pcm, bytes(rows))
                call(measure, pcm, 5, 65500)
                if timing:
                    assert read(radio + fields["audio_votes"]) == 0
                    print("PASS: manual offset disables audio-based slot adjustment")
                else:
                    assert read(radio + fields["audio_votes"]) == 3
                    assert read(radio + fields["audio_boundary"]) == 51000
                    call(measure, pcm, 0, 80000)
                    assert read(radio + fields["audio_votes"]) == 0
                    call(measure, pcm, 5, 82000)
                    assert read(radio + fields["audio_votes"]) == 3
                    assert read(radio + fields["audio_boundary"]) == 67500
                    call(measure, pcm, 5, 65500)

            if "audio_boundary" in fields and not timing:
                write(timestamp, 80_800_000)
                state("last_heartbeat", read(timestamp))
                state("stop_requested", 0)
                status(0x90)
                call(poll)
                call(0x60445170, rx_frame, end=0x60445174)
                assert call(poll) == 1
                cpu.mem_write(pcm, b"CQ W9XYZ FN31\0")
                assert call(arm, pcm, 1000) == 1
                call(poll)
                bcd_second = 0x99  # An invalid RTC cannot schedule this transmission.
                reads = len(rtc_reads)
                call(step, read(timestamp), last, previous)
                assert read(radio + fields["lease"]) == 0
                assert read(radio + fields["tx_wait_s"]) == 1
                write(timestamp, 81_020_000)
                state("last_heartbeat", read(timestamp))
                status(0x90)
                call(step, read(timestamp), last, previous)
                assert len(rtc_reads) == reads and read(radio + fields["lease"]) == 1
                call(watchdog)
                assert sent[-1] == b"\xe8\xf8FT8\x01\x05\0\0"
                write(timestamp, 126_020_000)
                call(step, read(timestamp), last, previous)
                assert len(rtc_reads) == reads
                assert read(radio + fields["audio_boundary"]) == 126000
                print("PASS: busiest decode cluster wins; later frames cannot steer the locked audio edge")

            if read(live + 4) >= 24:
                tail = args.build_dir / "ft8_rx.elf"
                event = symbol(tail, "auto_event")
                options = symbol(tail, "ft8_auto_options")
                automatic = symbol(tail, "auto_state")
                service = symbol(tail, "auto_service")
                receive = symbol(tail, "ft8_radio_auto_rx")
                key = symbol(tail, "auto_key")
                tx_phase = symbol(stage1, "tx_phase")
                work = read(symbol(stage1, "workspace"))
                tx_text = work + workspace_tx_phase(stage1, b"tx_text")
                ui = bytearray(128)
                ui[:5], ui[14:19] = b"W1AW\0", b"K4ABC"
                ui[workspace_tx_phase(stage1, b"tx_report")] = 56
                cpu.mem_write(synth, bytes(ui))

                def row(text, sender, recipient=0, offset=1900):
                    frame = bytearray(44)
                    frame[:len(text)] = text
                    struct.pack_into("<bHhBBH", frame, 35, -8, 1000, offset,
                                     recipient, sender, 0xffff)
                    cpu.mem_write(pcm, bytes(frame))

                def ready_to_arm():
                    state("lease", 0)
                    state("stop_requested", 0)
                    call(tx_phase, work, 0)
                    call(poll)
                    call(0x60445170, rx_frame, end=0x60445174)
                    call(poll)
                    status(0x90, 7_074_000, 37)

                def expect_tx(expected, boundary):
                    call(service)
                    call(poll)
                    actual_text = bytes(cpu.mem_read(tx_text, 35)).split(b"\0", 1)[0]
                    assert actual_text == expected, (actual_text, expected, boundary, call(automatic), read(phase))
                    if not timing:
                        assert call(key, boundary - 15000) == 0
                    assert call(key, boundary) == 1
                    message(expected)
                    ready_to_arm()

                write(timestamp, 165_600_000)
                ready_to_arm()
                row(b"CQ K4ABC FM19", 4)
                assert bytes(cpu.mem_read(options, 3)) == bytes((1, 5, 3))
                cpu.mem_write(options, b"\0")  # Simulate OFF in this isolated worker fixture.
                assert call(event, 2, pcm, synth, 164600) == 0
                assert call(event, 1, 0, 0, 0) == 1
                assert call(event, 2, pcm, synth, 164600) == 1
                expect_tx(b"K4ABC W1AW -08", 166000)  # No local grid in this harness.
                assert call(automatic) == 3

                write(timestamp, 194_600_000)
                row(b"W1AW W9XYZ R-12", 6, 1)
                call(receive, pcm, 1, 194600)
                assert call(automatic) == 3
                row(b"W1AW K4ABC R-12", 6, 1)
                call(receive, pcm, 1, 194600)
                assert call(automatic) == 2
                expect_tx(b"K4ABC W1AW RRR", 196000)
                assert call(automatic) == 3

                write(timestamp, 224_600_000)
                row(b"W1AW K4ABC 73", 6, 1)
                call(receive, pcm, 1, 224600)
                assert call(automatic) == 1
                print("PASS: AUTO ignores other callers and stops after a complete QSO")

                write(timestamp, 225_600_000)
                ready_to_arm()
                row(b"CQ K4ABC FM19", 4)
                assert call(event, 2, pcm, synth, 224600)
                cpu.mem_write(options + 1, b"\x02")
                for attempt in range(3):
                    boundary = 226000 + attempt * 30000
                    write(timestamp, (boundary - 200) * 1000)
                    status(0x90)
                    expect_tx(b"K4ABC W1AW -08", boundary)
                    write(timestamp, (boundary + 29499) * 1000)
                    call(service)
                    assert call(automatic) == 3
                    write(timestamp, (boundary + 29500) * 1000)
                    call(service)
                    assert call(automatic) == (2 if attempt < 2 else 1)
                cpu.mem_write(options + 1, b"\x05")
                print("PASS: AUTO uses the configured two retries, then returns to READY")

                # AUTO still checks the callsign when choosing a reply, but
                # neither decoding pass hides other callers or shifted signals.
                signals = ((b"W1AW K4ABC R-12", 1030), (b"W1AW W9XYZ R-08", 965),
                           (b"W1AW K4ABC R-10", 1800))
                samples = [0] * 240_000
                for text, hz in signals:
                    cpu.mem_write(pcm, text + b"\0")
                    assert call(encode, pcm, pcm + 0x800) == 1
                    assert call(tx_open, synth, 0x1000, pcm + 0x800, hz) == synth
                    start = 8000
                    while size := call(tx_next, synth, pcm, 1600):
                        for index, sample in enumerate(array("h", cpu.mem_read(pcm, size * 2)), start):
                            samples[index] += sample // len(signals)
                        start += size

                begin, push, finish = (read(0x606C2FC0 + offset) for offset in (20, 24, 32))
                rx, result = 0x609EBE30, 0x61114000
                call(begin, rx)
                for start in range(0, len(samples), 1600):
                    chunk = array("h", samples[start:start + 1600])
                    cpu.mem_write(pcm, chunk.tobytes())
                    assert call(push, rx, pcm, len(chunk), instruction_budget=200_000_000) == len(chunk)

                def decoded_messages():
                    count = call(finish, rx, result, 24, 224600, instruction_budget=750_000_000)
                    return {bytes(cpu.mem_read(result + index * 44, 35)).split(b"\0", 1)[0]
                            for index in range(count)}

                full_band = {text for text, _ in signals}
                write(timestamp, 225_600_000)
                assert decoded_messages() == full_band
                cpu.mem_write(synth, bytes(ui))
                row(b"CQ K4ABC FM19", 4)
                assert call(event, 2, pcm, synth, 224600) == 1
                assert decoded_messages() == full_band
                call(event, 0, 0, 0, 0)
                assert decoded_messages() == full_band
                call(service)
                assert call(event, 2, pcm, synth, 224600) == 1
                write(timestamp, 269_600_000)
                call(service)
                assert decoded_messages() == full_band
                call(event, 0, 0, 0, 0)
                call(service)
                print("PASS: AUTO decodes other callers and the shifted peer")

                if read(0x606C2FC0 + 4) >= 26:
                    bcd_second = 0x00  # ADIF uses a valid wall-clock time even when TX follows audio.
                    # The adapter uses the radio heap on target. These private
                    # arenas stand in for the two objects allocated by menu().
                    write(symbol(tail, "worked"), 0x60760000)
                    write(symbol(tail, "full"), 0x60762000)
                    load_log = symbol(tail, "load_worked_step")
                    full_view = symbol(tail, "ft8_radio_full_view")
                    history.extend(b"<CALL:5>K1OLD<eor>\n")
                    for index in range(530):
                        history.extend(f"<CALL:5>N4{index:03d}<eor>\n".encode())

                    def queue_view():
                        assert call(full_view, result) == 1
                        data = bytes(cpu.mem_read(result, 152))
                        count, done, cq, checking = struct.unpack_from("<4I", data)
                        current = data[16:30].split(b"\0", 1)[0]
                        names = [data[30 + i * 20:44 + i * 20].split(b"\0", 1)[0]
                                 for i in range(min(6, count))]
                        return count, done, cq, checking, current, names

                    def slot_rows(end, *entries):
                        write(timestamp, end * 1000)
                        status(0x90, 7_074_000, 37)
                        rows = bytearray(44 * len(entries))
                        for index, (text, hz, db, km) in enumerate(entries):
                            start = index * 44
                            rows[start:start + len(text)] = text
                            struct.pack_into("<bHhBBH", rows, start + 35,
                                             db, hz, 1900, 1, text.index(b" ") + 2, km)
                        cpu.mem_write(result, bytes(rows))
                        call(receive, result, len(entries), end)

                    def full_tx(expected, boundary, first=False):
                        write(timestamp, (boundary - 200) * 1000)
                        status(0x90, 7_074_000, 37)
                        call(service)
                        call(poll)
                        assert bytes(cpu.mem_read(tx_text, 35)).split(b"\0", 1)[0] == expected
                        if not first and not timing:
                            assert call(key, boundary - 15000) == 0
                        assert call(key, boundary) == 1
                        write(timestamp, (boundary + 13000) * 1000)
                        message(expected)
                        ready_to_arm()

                    write(timestamp, 300_000_000)
                    ready_to_arm()
                    cpu.mem_write(pcm, b"FN31\0")
                    assert call(read(live + 36), pcm) == 1
                    assert call(event, 3, 0, synth, 0) == 1
                    assert queue_view() == (0, 0, 3, 0, b"", [])
                    full_tx(b"CQ W1AW FN31", 301000, first=True)
                    slot_rows(329600, (b"W1AW W9XYZ EM10", 900, -5, 30),
                              (b"W1AW K1OLD FM19", 950, -3, 50),
                              (b"W1AW K5ABC EM15", 1400, -5, 900),
                              (b"W1AW K4ABC FM19", 1030, -15, 300),
                              (b"W1AW K4ABC FM19", 1040, -8, 300),
                              (b"W1AW K6ABC DM14", 1800, -1, 1500),
                              (b"W1AW K7ABC -03", 2000, -3, 0xffff),
                              (b"W9XYZ W1AAA FM19", 1100, 0, 10))
                    assert queue_view() == (0, 0, 2, 1, b"", [])
                    for _ in range(1 + (len(history) + sum(map(len, records))) // 512):
                        call(load_log)
                    assert queue_view() == (3, 0, 2, 0, b"K4ABC", [b"K5ABC", b"K6ABC", b"K7ABC"])
                    full_tx(b"K4ABC W1AW -08", 331000)
                    slot_rows(359600, (b"W1AW K4ABC R-12", 1050, -9, 0xffff))
                    full_tx(b"K4ABC W1AW RR73", 361000)
                    assert queue_view() == (2, 1, 2, 0, b"K5ABC", [b"K6ABC", b"K7ABC"])
                    assert len(records) == 3 and records[-1].startswith(b"<CALL:5>K4ABC"), records
                    full_tx(b"K5ABC W1AW -05", 391000)
                    for attempt in range(6):
                        boundary = 391000 + 30000 * attempt
                        slot_rows(boundary + 28600)
                        write(timestamp, (boundary + 29500) * 1000)
                        call(service)
                        if attempt < 5:
                            full_tx(b"K5ABC W1AW -05", boundary + 30000)
                    shift = 120000
                    assert queue_view() == (1, 1, 2, 0, b"K6ABC", [b"K7ABC"])
                    full_tx(b"K6ABC W1AW -01", 451000 + shift)
                    slot_rows(479600 + shift, (b"W9XYZ K6ABC R-06", 1800, -4, 0xffff))
                    assert queue_view()[4] == b"K6ABC"
                    for attempt in range(6):
                        boundary = 451000 + shift + 30000 * attempt
                        write(timestamp, (boundary + 29500) * 1000)
                        call(service)
                        if attempt < 5:
                            full_tx(b"K6ABC W1AW -01", boundary + 30000)
                    shift += 150000
                    assert queue_view() == (0, 1, 2, 0, b"K7ABC", [])
                    full_tx(b"K7ABC W1AW R-03", 481000 + shift)
                    slot_rows(509600 + shift, (b"W1AW K7ABC RR73", 2000, -4, 0xffff))
                    full_tx(b"K7ABC W1AW 73", 511000 + shift)
                    assert queue_view() == (0, 2, 2, 0, b"", [])
                    assert len(records) == 4 and records[-1].startswith(b"<CALL:5>K7ABC"), records
                    full_tx(b"CQ W1AW FN31", 541000 + shift)
                    slot_rows(569600 + shift, (b"W1AW K4ABC FM19", 1040, -8, 300))
                    if timing:
                        write(timestamp, (570700 + shift) * 1000)
                        call(service)
                    assert queue_view() == (0, 2, 1, 0, b"", [])
                    full_tx(b"CQ W1AW FN31", 571000 + shift)
                    slot_rows(599600 + shift)
                    if timing:
                        write(timestamp, (600700 + shift) * 1000)
                        call(service)
                    assert call(full_view, result) == 0 and call(automatic) == 1
                    call(service)
                    assert call(event, 3, 0, synth, 0) == 1
                    boundary = 601000 + shift
                    full_tx(b"CQ W1AW FN31", boundary, first=True)
                    slot_rows(boundary + 28600, (b"W1AW K1OLD FM19", 950, -3, 50))
                    assert queue_view() == (0, 0, 2, 1, b"", [])
                    log_fail = True
                    call(load_log)
                    assert call(full_view, result) == 0 and call(automatic) == 1
                    call(service)
                    assert call(event, 3, 0, synth, 0) == 1
                    call(event, 0, 0, 0, 0)
                    call(service)
                    assert call(full_view, result) == 0 and call(automatic) == 1
                    print("PASS: FULL AUTO retries five times before advancing, checks ADIF, and stops after three CQs")
                    print("PASS: short SD read before EOF aborts FULL AUTO; STOP also disarms it")
                    if timing:
                        log_fail = False
                        cpu.mem_write(options + 2, b"\x01")
                        boundary += 30000
                        assert call(event, 3, 0, synth, 0) == 1
                        full_tx(b"CQ W1AW FN31", boundary, first=True)
                        assert queue_view()[2] == 0
                        write(timestamp, (boundary + 29500) * 1000)
                        call(service)
                        assert call(full_view, result) == 0
                        call(service)

                        cpu.mem_write(options + 2, b"\xff")
                        assert call(event, 3, 0, synth, 0) == 1
                        for attempt in range(5):
                            boundary += 30000
                            full_tx(b"CQ W1AW FN31", boundary, first=attempt == 0)
                            assert queue_view()[2] == 255
                            write(timestamp, (boundary + 29500) * 1000)
                            call(service)
                        call(event, 0, 0, 0, 0)
                        call(service)
                        assert call(full_view, result) == 0 and call(automatic) == 1
                        print("PASS: one-round CQ expires, unlimited CQ survives five rounds, STOP returns to AUTO READY")

                if read(live + 4) >= 24 and not timing:
                    log_fail = False
                    state("audio_votes", 0)
                    write(timestamp, 630_000_000)
                    ready_to_arm()
                    assert call(event, 3, 0, synth, 0) == 1
                    full_tx(b"CQ W1AW FN31", 631000, first=True)
                    # A first reply can establish an audio clock 1.7 seconds
                    # ahead of the RTC boundary used for CQ. The next real
                    # transmit edge has already passed when this scan ends.
                    write(timestamp, 659_600_000)
                    status(0x90, 7_074_000, 37)
                    row(b"W1AW K8ABC FM19", 6, 1, offset=200)
                    call(measure, pcm, 1, 659600)
                    call(receive, pcm, 1, 659600)
                    for _ in range(1 + (len(history) + sum(map(len, records))) // 512):
                        call(load_log)
                    call(service)
                    call(poll)
                    assert read(work + workspace_tx_phase(stage1)) == 0
                    full_tx(b"K8ABC W1AW -08", 689300)
                    call(event, 0, 0, 0, 0)
                    call(service)
                    print("PASS: FULL AUTO keeps the CQ parity after the first audio clock correction")

                if args.plugin:
                    # Run the real loader with the stock filesystem/heap ABI
                    # stubbed, then execute its relocated Thumb entry twice.
                    request = symbol(tail, "ft8_plugin_request")
                    load = symbol(tail, "ft8_plugin_load")
                    entry = symbol(tail, "ft8_plugin_queue")
                    handle, heap = 0x60765000, 0x60768004
                    blob = args.plugin.read_bytes()
                    data = None
                    calls = {name: 0 for name in ("open", "alloc", "free", "clean", "invalidate")}

                    def plugin_io(uc, _address, _size, operation):
                        a, b, c = (uc.reg_read(reg) for reg in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2))
                        result = 0
                        if operation in calls:
                            calls[operation] += 1
                        if operation == "open":
                            path = b"I:\\FTX-1\\FT8QUEUE.BIN\0"
                            assert bytes(uc.mem_read(a, len(path))) == path
                            if data is not None:
                                write(handle + 0x28, 0)
                                write(handle + 0x2c, len(data))
                                result = handle
                        elif operation == "read":
                            assert b == 1 and uc.reg_read(UC_ARM_REG_R3) == handle
                            pos = read(handle + 0x28)
                            chunk = data[pos:pos + c]
                            if chunk:
                                uc.mem_write(a, chunk)
                            result = len(chunk)
                            write(handle + 0x28, pos + result)
                        elif operation == "alloc":
                            assert a == len(blob) - 20 + 31
                            result = heap
                        elif operation == "free":
                            assert a == heap and b == len(blob) - 20 + 31
                        elif operation in ("clean", "invalidate"):
                            assert a == (heap + 31) & ~31 and b == len(blob) - 20
                            if operation == "invalidate":
                                assert calls["clean"] == 1
                        elif operation == "close":
                            assert a == handle
                        uc.reg_write(UC_ARM_REG_R0, result)

                    for address, operation in ((0x6046995C, "open"), (0x6046A8F8, "read"),
                                               (0x60469E90, "close"), (0x6047D9E0, "alloc"),
                                               (0x6047D9EC, "free"), (0x60402FA8, "clean"),
                                               (0x60402EFC, "invalidate")):
                        cpu.mem_write(address, struct.pack("<I", 0xE12FFF1E))
                        # The existing ADIF fixture also observes the shared functions.
                        if operation in ("open", "read", "close"):
                            cpu.hook_del(file_hooks[address])
                        cpu.hook_add(UC_HOOK_CODE, plugin_io, operation, begin=address, end=address)

                    call(load)
                    assert calls["open"] == 0 and call(entry) == 0
                    bad_entry = blob[:12] + struct.pack("<I", struct.unpack_from("<I", blob, 12)[0] ^ 2) + blob[16:]
                    for data in (None, blob[:4] + b"\x02\x00\x00\x00" + blob[8:],
                                 blob[:-1], bad_entry, blob[:-1] + bytes([blob[-1] ^ 1])):
                        call(request)
                        call(load)
                        assert call(entry) == 0 and calls["clean"] == 0
                    assert calls["free"] == 2 and calls["alloc"] == 2
                    data = blob
                    call(request)
                    call(load)
                    loaded = call(entry)
                    assert loaded == ((heap + 31) & ~31) + struct.unpack_from("<I", blob, 12)[0]
                    assert calls["clean"] == calls["invalidate"] == 1
                    call(request)
                    call(load)
                    assert calls["open"] == 6 and call(entry) == loaded

                    peer, line = 0x61113100, 0x61113200
                    host = symbol(tail, "draw_next_tx.host")
                    for km, expected in ((300, b"K4ABC -08 1040Hz 300km\0"),
                                         (0xffff, b"K4ABC -08 1040Hz\0")):
                        cpu.mem_write(peer, struct.pack("<14sHHbB", b"K4ABC", 1040, km, -8, 1))
                        call(loaded, host, peer, line)
                        assert bytes(cpu.mem_read(line, len(expected))) == expected
                    print("PASS: SD plugin is loaded on request once, rejects invalid files, and runs from allocated RAM")


if __name__ == "__main__":
    main()
