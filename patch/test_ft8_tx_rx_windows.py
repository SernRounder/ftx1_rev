"""Replay full RX, a TX slot with 2 s of RX remaining, and another full RX."""

import argparse
import struct
from pathlib import Path

from elftools.elf.elffile import ELFFile
from unicorn import UC_HOOK_CODE

from test_custom_modes import CombinedBoard
from test_ft8_arm import recording_16k
from test_ft8_menu import read_display_sfl
from test_ft8_radio_dma import symbol


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--build-dir", type=Path, required=True, help="Directory containing the matching ft8_rx.elf")
    parser.add_argument("--wav", type=Path, default=Path("downloads/210703_133430.wav"),
                        help="Replay audio with a decodable FT8 burst in its first slot")
    args = parser.parse_args()
    elf = args.build_dir / "ft8_rx.elf"
    image = read_display_sfl(args.image)
    b = CombinedBoard(image, elf)
    b.choose(cw=False)
    b.cpu.mem_map(0xE8200000, 0x1000)
    b.cpu.mem_write(0xE82000E4, struct.pack("<I", 0x60))
    b.cpu.mem_write(0x607C4012, struct.pack("<H", 500))
    clock = symbol(elf, "ft8_clock")
    b.cpu.mem_write(clock, struct.pack("<6I", 0, 0, 1, 0, 1, 0))
    work = b.word(symbol(elf, "workspace"))

    def members(name):
        with elf.open("rb") as stream:
            for unit in ELFFile(stream).get_dwarf_info().iter_CUs():
                for entry in unit.iter_DIEs():
                    if entry.tag != "DW_TAG_structure_type":
                        continue
                    entry_name = entry.attributes.get("DW_AT_name")
                    if entry_name is None or entry_name.value != name.encode():
                        continue
                    return {
                        member.attributes["DW_AT_name"].value.decode():
                            member.attributes["DW_AT_data_member_location"].value
                        for member in entry.iter_children() if member.tag == "DW_TAG_member"
                    }
        raise ValueError(name)

    wm, vm = members("workspace"), members("ft8_live_view")
    live = 0x6052C670
    poll, arm, sync_time = (b.word(live + i) for i in (28, 44, 52))
    watchdog, dma_source, dma_done, report = (
        symbol(elf, name) for name in (
            "watchdog_step", "ft8_radio_dma_source", "ft8_radio_dma_done", "ft8_radio_report_packet"))
    wav = recording_16k(args.wav)
    assert len(wav) >= 240000, "the replay needs at least 15 seconds of audio"
    pause_count = 0

    def delay():
        nonlocal pause_count
        pause_count += 1
        b.clock += 6000
        return 0

    b.stubs[0x797C8] = delay
    b.cpu.hook_add(UC_HOOK_CODE, b.stub, begin=0x604797C8, end=0x604797C8)

    def field(name):
        return b.word(work + wm[name])

    def view(name):
        return work + wm["view"] + vm[name]

    def main_status(value):
        msg = bytearray(0x13c)
        msg[0], msg[9] = 0x20, value
        struct.pack_into(">I", msg, 14, 7074000)
        msg[-1] = sum(msg) & 255
        b.cpu.mem_write(b.pcm, bytes(msg))
        b.call(report, b.pcm, len(msg))

    def input_frame(samples):
        b.cpu.mem_write(b.pcm, struct.pack("<HH", len(samples), 0x1234) + samples.tobytes())
        b.call(0x60445170, b.pcm, end=0x60445174)

    def worker(edge_us, deadline_us):
        b.clock = edge_us
        b.state(worker_polling=1, decode_timed=1, decode_deadline=deadline_us)
        b.call(poll, budget=400_000_000)
        b.state(worker_polling=0)

    def input_rx(samples, edge_ms, end_ms):
        b.clock = edge_ms * 1000
        input_frame(samples)
        worker(b.clock, end_ms * 1000)

    def drive_audio(start_ms, stop_ms, slot_start, clip_ms):
        p = (start_ms - slot_start) * 16
        while p < (stop_ms - slot_start) * 16:
            end = min(p + 1600, (stop_ms - slot_start) * 16)
            if p < clip_ms * 16 < end:
                end = clip_ms * 16
            input_rx(wav[p:end], slot_start + end // 16, slot_start + 14500)
            p = end

    def history():
        return b.word(view("rx_scans")), tuple(b.cpu.mem_read(view("slot_total"), 2))

    def decoded_at(batch):
        counts = bytes(b.cpu.mem_read(view("slot_total"), 2))
        batches = struct.unpack("<2H", b.cpu.mem_read(view("slot_batch"), 4))
        rows = []
        for i, (number, count) in enumerate(zip(batches, counts)):
            if number != batch:
                continue
            for j in range(count):
                raw = bytes(b.cpu.mem_read(work + wm["results"] + (i * 24 + j) * 44, 35))
                rows.append(raw.split(b"\0", 1)[0].decode())
        return sorted(rows)

    drive_audio(0, 15000, 0, 13450)
    first_scan, initial_counts = history()
    first_rows = decoded_at(first_scan)
    assert first_scan == 1 and first_rows
    first_pcm, first_yields = field("captured_samples"), pause_count
    assert first_pcm == 215200, first_pcm
    print("window 1:", first_pcm, "PCM,", len(first_rows), "messages,", first_yields, "delay(1)", flush=True)

    b.clock = 15_000_000
    main_status(0x84)
    b.cpu.mem_write(b.pcm, b"CQ W9XYZ FN31\0")
    assert b.call(arm, b.pcm, 1000)
    b.call(poll)
    assert b.call(sync_time, 15000) == 1
    b.state(last_heartbeat=b.clock)
    b.call(watchdog)
    assert b.commands[-1] == b"\xe8\xf8FT8\x01\x02\x8a\0"
    sent_blocks = 0
    for ms in range(15050, 28000, 50):
        b.clock = ms * 1000
        b.state(last_heartbeat=b.clock)
        main_status(0x89)
        b.call(watchdog)
        p = (ms - 15000) * 16
        input_frame(wav[p - 800:p])  # A real sample tries to enter even while TX is active.
        b.call(poll)
        emitted = b.call(dma_source, 0x6095C500)
        if emitted != 0x6095C500:
            assert b.word(emitted) == 0x12340320
            sent_blocks += 1
            b.call(dma_done)
        b.call(watchdog)
    assert sent_blocks == 253, sent_blocks
    assert field("captured_samples") == first_pcm
    assert b.commands[-1] == b"\xe8\xf8FT8\0\x02\0\0", b.commands[-1].hex()
    b.clock = 28_000_000
    main_status(0x88)
    b.call(watchdog)
    b.call(poll)
    assert field("tx_phase") == 0, field("tx_phase")

    drive_audio(28000, 29900, 15000, 13450)
    middle_pcm = field("captured_samples") - first_pcm
    assert middle_pcm == 7200 and history() == (first_scan, initial_counts)
    print("window 2: TX at 15 s, RX at 28 s, 253 TX blocks;",
          middle_pcm, "PCM, 0 new messages", flush=True)

    mixed = wav[239200:240000] + wav[:800]
    input_rx(mixed, 30050, 44500)
    third_first = field("samples")
    assert third_first == 800, third_first
    drive_audio(30050, 45000, 30000, 13450)
    third_pcm = field("captured_samples") - first_pcm - middle_pcm
    third_scan, _ = history()
    third_rows = decoded_at(third_scan)
    assert third_scan == first_scan + 1
    assert third_pcm == first_pcm
    assert first_rows == third_rows, (first_rows, third_rows)
    print("window 3:", third_pcm, "PCM,", len(third_rows), "messages,",
          pause_count - first_yields, "delay(1); exact match", flush=True)
    for row in third_rows:
        print(row, flush=True)


if __name__ == "__main__":
    main()
