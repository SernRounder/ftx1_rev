"""Decode a 16 kHz resampled recording with the linked Cortex-A9 receiver in Unicorn."""

import argparse
import array
import random
import struct
import wave
from pathlib import Path

from unicorn import UC_ARCH_ARM, UC_MODE_ARM, Uc
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import (
    UC_CPU_ARM_CORTEX_A9,
    UC_ARM_REG_C1_C0_2, UC_ARM_REG_FPEXC, UC_ARM_REG_LR, UC_ARM_REG_PC,
    UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP,
    UC_ARM_REG_CPSR, UC_ARM_REG_SPSR,
)

from build_ft8_rx import ARM_ADDRESS, BUILD
from build_ft8_menu import HOLE_OFFSET, IMAGE_BASE
from test_ft8_rx import RECORDING


WORK = 0x61000000
STACK = 0x61110000
PCM = 0x61120000
RESULT = 0x61130000
RETURN = 0x61140000
TXSTATE = 0x61150000


def recording_16k(path):
    with wave.open(str(path)) as file:
        rate = file.getframerate()
        if rate not in (12000, 16000) or (file.getnchannels(), file.getsampwidth()) != (1, 2):
            raise ValueError("Expected 12 or 16 kHz mono 16-bit PCM")
        source = array.array("h", file.readframes(15 * rate))
    if len(source) != 15 * rate:
        raise ValueError("Expected at least one 15-second FT8 slot")
    if rate == 16000:
        return source
    output = array.array("h")
    for i in range(240000):
        p, remainder = divmod(i * 3, 4)
        output.append((source[p] * (4 - remainder) +
                       source[min(p + 1, len(source) - 1)] * remainder) // 4)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wav", nargs="?", type=Path, help="A slot-aligned WAV to decode")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--tx", action="store_true", help="Only run the TX round-trip")
    mode.add_argument("--rolling", action="store_true", help="Test clock-free decoding at an off-slot phase")
    parser.add_argument("--payload", type=Path, default=BUILD / "ft8_rx.bin")
    parser.add_argument("--without-vfp", action="store_true", help="Keep CP10/CP11 disabled")
    parser.add_argument("--vfp-probe", choices=("hardware", "fallback", "denied"),
                        help="Exercise native FFT dispatch, probe fault, or denied access")
    parser.add_argument("--noise-rms", type=int, default=0,
                        help="Add deterministic Gaussian noise at this PCM RMS (rolling mode)")
    args = parser.parse_args()
    payload = args.payload.read_bytes()
    (magic, version, work_bytes, stack_bytes, open_rx,
     begin, _, push_frame, finish, _, encode, encode_free, tx_open, tx_next,
     ui_draw, std_message, adif_record) = struct.unpack_from("<4s16I", payload)
    assert magic == b"FT8R" and (6 <= version <= 11 or version in (13, 15, 17, 19, 21, 22, 23) or 24 <= version <= 35)
    work = WORK if version == 6 else 0x609EBE30
    for address in (open_rx, begin, push_frame, finish, encode, tx_open, tx_next,
                    ui_draw, std_message, adif_record):
        assert address & 1 or address % 4 == 0
        assert ARM_ADDRESS <= (address & ~1) < ARM_ADDRESS + len(payload)

    cpu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    if args.vfp_probe:
        cpu.ctl_set_cpu_model(UC_CPU_ARM_CORTEX_A9)
    cpu.mem_map(ARM_ADDRESS & ~0xFFF, 0xE000)
    cpu.mem_write(ARM_ADDRESS, payload)
    if version >= 28:
        live = args.payload.with_name("ft8_radio.bin").read_bytes()
        address = IMAGE_BASE + HOLE_OFFSET
        base = address & ~0xfff
        cpu.mem_map(base, (address + len(live) - base + 0xfff) & ~0xfff)
        cpu.mem_write(address, live)
    work_base = work & ~0xFFF
    cpu.mem_map(work_base, (work + work_bytes - work_base + 0xFFF) & ~0xFFF)
    if version >= 7:
        cpu.mem_map(0x603D0000, 0x30000)
    cpu.mem_map(STACK - stack_bytes, stack_bytes)
    cpu.mem_write(STACK - stack_bytes, bytes([0xA5]) * stack_bytes)
    for address in (PCM, RESULT, RETURN):
        cpu.mem_map(address, 0x1000)
    cpu.mem_map(TXSTATE, 0x8000)
    if not args.without_vfp:
        cpu.reg_write(UC_ARM_REG_C1_C0_2, 0x00F00000)
        cpu.reg_write(UC_ARM_REG_FPEXC, 0x40000000)

    def call(address, a=0, b=0, c=0, d=0):
        for reg, value in ((UC_ARM_REG_R0, a), (UC_ARM_REG_R1, b), (UC_ARM_REG_R2, c),
                           (UC_ARM_REG_R3, d), (UC_ARM_REG_SP, STACK), (UC_ARM_REG_LR, RETURN)):
            cpu.reg_write(reg, value)
        cpu.emu_start(address, RETURN, count=1_000_000_000)
        pc = cpu.reg_read(UC_ARM_REG_PC)
        assert pc == RETURN, f"ARM call {address:#x} exceeded the emulator budget at PC={pc:#x}"
        assert cpu.reg_read(UC_ARM_REG_SP) == STACK
        return cpu.reg_read(UC_ARM_REG_R0)

    fft_calls = []
    candidate_calls = []
    vfp_required = False
    if args.vfp_probe:
        from elftools.elf.elffile import ELFFile
        from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM

        with args.payload.with_suffix(".elf").open("rb") as file:
            table = ELFFile(file).get_section_by_name(".symtab")
            prepare, backend, probe, fft = [table.get_symbol_by_name(name)[0]["st_value"] for name in
                                            ("ft8_fft_prepare", "backend", "ft8_vfp_probe", "ft8_vfp_fft")]
            candidates = table.get_symbol_by_name("ft8_vfp_candidate")
            vfp_required = bool(candidates)
            if candidates:
                candidate = candidates[0]["st_value"] & ~1
                cpu.hook_add(UC_HOOK_CODE, lambda *_: candidate_calls.append(1),
                             begin=candidate, end=candidate)
        cpu.mem_map(IMAGE_BASE, 0x4000)
        vector = IMAGE_BASE + 4
        cpu.cpr_write(15, 0, 12, 0, 0, 0, False, IMAGE_BASE)
        stock = struct.pack("<I", 0xea000078)
        cpu.mem_write(vector, stock)
        for address in (0x60402fa8, 0x60402efc):
            cpu.mem_write(address, struct.pack("<I", 0xe12fff1e))
        cpu.reg_write(UC_ARM_REG_CPSR, 0x1f)
        cpu.reg_write(UC_ARM_REG_C1_C0_2, 0)
        cpu.reg_write(UC_ARM_REG_FPEXC, 0)
        # Unicorn starts the Cortex-A9 in Non-secure state and masks CPACR
        # writes through NSACR. Model a board that grants CP10/11 access.
        if args.vfp_probe != "denied":
            cpu.cpr_write(15, 0, 1, 1, 2, 3, False, 3 << 10)

        faults = []
        if args.vfp_probe == "fallback":
            insns = Cs(CS_ARCH_ARM, CS_MODE_ARM).disasm(bytes(cpu.mem_read(probe, 192)), probe)
            fault = next(i.address for i in insns if i.mnemonic == "vmrs" and "fpexc" in i.op_str)

            def inject(uc, address, _size, _data):
                cpsr = uc.reg_read(UC_ARM_REG_CPSR)
                faults.append(address)
                uc.reg_write(UC_ARM_REG_CPSR, (cpsr & ~0x3f) | 0x1b | 0x80)
                uc.reg_write(UC_ARM_REG_SPSR, cpsr)
                uc.reg_write(UC_ARM_REG_LR, address + 4)
                uc.reg_write(UC_ARM_REG_PC, vector)

            cpu.hook_add(UC_HOOK_CODE, inject, begin=fault, end=fault)
        cpu.hook_add(UC_HOOK_CODE, lambda _, a, _s, _d: fft_calls.append(a), begin=fft, end=fft)
        call(prepare)
        expected_backend = 2 if args.vfp_probe == "hardware" else 1
        assert struct.unpack("<I", cpu.mem_read(backend, 4))[0] == expected_backend
        assert len(faults) == (args.vfp_probe == "fallback")
        assert cpu.mem_read(vector, 4) == stock
        assert cpu.reg_read(UC_ARM_REG_C1_C0_2) == cpu.reg_read(UC_ARM_REG_FPEXC) == 0
        assert cpu.reg_read(UC_ARM_REG_CPSR) & 0x1f == 0x1f
        print(f"PASS: VFP probe selected {args.vfp_probe} and restored vector and permissions")

    assert call(open_rx, work + 1, work_bytes) == 0
    assert call(open_rx, work, work_bytes - 1) == 0
    rx = call(open_rx, work, work_bytes)
    if vfp_required and args.vfp_probe != "hardware":
        assert rx == 0 and not fft_calls and not candidate_calls
        print("PASS: unavailable VFP leaves FT8 RX closed")
        return
    assert rx == work
    assert call(finish, rx, RESULT, 24) == 0
    cpu.mem_write(PCM, struct.pack("<HH", 2001, 0))
    assert call(push_frame, rx, PCM, 4) == 0
    call(begin, rx)

    if args.rolling:
        assert version >= 9, "rolling decode requires the native receiver ABI"
        from elftools.elf.elffile import ELFFile
        elf_path = args.payload.with_suffix(".elf")
        entries = None
        if elf_path.is_file():
            with elf_path.open("rb") as file:
                entries = ELFFile(file).get_section_by_name(".symtab").get_symbol_by_name("search")
        early_search = []
        scans = 0
        if entries:
            address = entries[0]["st_value"] & ~1
            cpu.hook_add(UC_HOOK_CODE, lambda *_: early_search.append(1) if not scans else None,
                         begin=address, end=address)
        roll, = struct.unpack_from("<I", payload, 18 * 4)
        assert ARM_ADDRESS <= (roll & ~1) < ARM_ADDRESS + len(payload)
        samples = array.array("h", [0]) * (7300 * 16) + recording_16k(args.wav or RECORDING)
        samples.extend(array.array("h", [0]) * 32000)
        if args.noise_rms:
            rng = random.Random(84015)
            samples = array.array("h", (max(-32768, min(32767, round(x + rng.gauss(0, args.noise_rms))))
                                         for x in samples))
        pos, remaining = 0, 240000
        messages = set()
        while pos < len(samples):
            take = min(remaining, 1999, len(samples) - pos)
            frame = struct.pack("<HH", take, 0) + samples[pos:pos + take].tobytes()
            cpu.mem_write(PCM, frame)
            assert call(push_frame, rx, PCM, len(frame)) == take
            pos += take
            remaining -= take
            if remaining == 0:
                scans += 1
                end_ms = pos // 16
                decoded = call(finish, rx, RESULT, 24, end_ms)
                for i in range(decoded):
                    line = cpu.mem_read(RESULT + 44 * i, 35)
                    messages.add(bytes(line).split(b"\0", 1)[0].decode())
                remaining = 240000 - call(roll, rx, end_ms)
                assert (0 < remaining <= 238080 and remaining % 2560 == 0
                        if version >= 24 and messages else remaining == 30720)
        assert scans >= 4
        expected = {"CQ R7IW LN35", "CQ DX R6WA LN32", "CQ TA6CQ KN70", "OH3NIV ZS6S -03"}
        assert (expected <= messages if args.wav is None else messages), messages
        if entries:
            assert early_search, "candidate search did not run during capture"
            print("PASS: candidate search ran before the first window closed")
        print(f"PASS: rolling ARM receiver decoded {len(messages)} messages with a 7.3 s slot offset")
        if args.vfp_probe:
            assert bool(fft_calls) == (args.vfp_probe == "hardware")
            assert cpu.reg_read(UC_ARM_REG_C1_C0_2) == cpu.reg_read(UC_ARM_REG_FPEXC) == 0
            print(f"VFP FFT calls: {len(fft_calls)}")
            if vfp_required:
                assert candidate_calls
                print(f"VFP likelihood calls: {len(candidate_calls)}")
        return

    def roundtrip_tx(text, frequency, *, free=False):
        cpu.mem_write(PCM, text.encode("ascii") + b"\0")
        assert call(encode_free if free else encode, PCM, RESULT) == 1
        assert call(tx_open, TXSTATE, 0x8000, RESULT, frequency) == TXSTATE
        assert call(tx_open, TXSTATE, 32, RESULT, frequency) == 0  # short storage
        assert call(tx_open, TXSTATE, 0x8000, RESULT, frequency) == TXSTATE
        waveform = array.array("h")
        while len(waveform) < 202240:
            produced = call(tx_next, TXSTATE, PCM, 1000)
            assert 0 < produced <= 1000
            waveform.extend(array.array("h", cpu.mem_read(PCM, produced * 2)))
        assert call(tx_next, TXSTATE, PCM, 1000) == 0
        call(begin, rx)
        slot = waveform.tobytes() + bytes(2 * (240000 - len(waveform)))
        for start in range(0, len(slot), 3998):
            piece = slot[start:start + 3998]
            frame = struct.pack("<HH", len(piece) // 2, 0) + piece
            cpu.mem_write(PCM, frame)
            assert call(push_frame, rx, PCM, len(frame)) == len(piece) // 2
        assert call(finish, rx, RESULT, 24) >= 1
        message = bytes(cpu.mem_read(RESULT, 35)).split(b"\0", 1)[0].decode()
        hz = struct.unpack_from("<H", cpu.mem_read(RESULT + 36, 2), 0)[0]
        assert message == text, (message, text)
        assert abs(hz - frequency) <= 44, (hz, frequency)
        print(f"{hz:4} Hz  TX round-trip: {message}")

    roundtrip_tx("CQ W9XYZ FN31", 1000)
    roundtrip_tx("K1ABC W9XYZ RRR", 440)
    roundtrip_tx("HELLO WORLD", 800, free=True)
    assert cpu.mem_write(PCM, b"THIS MESSAGE IS FAR TOO LONG\0") is None
    assert call(encode, PCM, RESULT) == 0
    print("PASS: ARM TX synthesizer round-trips through the ARM receiver")

    if not args.tx:
        call(begin, rx)
        samples = recording_16k(args.wav or RECORDING)
        for start in range(0, len(samples), 1999):
            chunk = samples[start:start + 1999]
            frame = struct.pack("<HH", len(chunk), 0) + chunk.tobytes()
            cpu.mem_write(PCM, frame)
            assert call(push_frame, rx, PCM, len(frame)) == len(chunk)

        decoded = call(finish, rx, RESULT, 24)
        messages = set()
        for i in range(decoded):
            line = cpu.mem_read(RESULT + 44 * i, 44)
            message = bytes(line[:35]).split(b"\0", 1)[0].decode()
            messages.add(message)
            hz, offset_ms, _ = struct.unpack_from("<Hhh", line, 36)
            print(f"{hz:4} Hz {offset_ms:+5} ms  {message}")
        if args.wav is None:
            assert {"CQ R7IW LN35", "CQ DX R6WA LN32", "CQ TA6CQ KN70", "OH3NIV ZS6S -03"} <= messages
            print(f"PASS: {decoded} messages decoded by the ARM receiver")
        else:
            print(f"{args.wav.name}: {decoded} messages decoded by the ARM receiver")
    stack = cpu.mem_read(STACK - stack_bytes, stack_bytes)
    untouched = next(i for i, byte in enumerate(stack) if byte != 0xA5)
    assert untouched >= 256
    print(f"Observed stack high-water mark {stack_bytes - untouched:,} bytes")


if __name__ == "__main__":
    main()
