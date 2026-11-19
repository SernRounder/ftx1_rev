"""Verify the softkey-menu MAIN V01-13 SFL images against the stock DISPLAY updater and RX disassembly."""

import argparse
import subprocess
import tempfile
from pathlib import Path

from test_ft8_main_updater import BASE as DISP_BASE, Reader
from build_ft8_main import MAIN_APP_LIMIT, MAIN_CODE, ROOT, read_main, sfl_codec
from build_softkey_main import C2_CODE, C2_LIMIT

def verify_updater_range(display: bytes, image: bytes, lo: int, hi: int, name: str):
    from unicorn.arm_const import UC_ARM_REG_LR, UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP
    from test_ft8_main_updater import FILE, STACK, STOP, TAIL
    import struct

    codec = sfl_codec()
    _, records = read_main(codec, image)
    expected = bytearray()
    for kind, addr, data, _ in records:
        if kind != "3":
            continue
        start = max(addr, lo)
        end = min(addr + len(data), hi)
        if start < end:
            expected.extend(data[start - addr : end - addr])

    reader = Reader(display, image)
    for reg, val in ((UC_ARM_REG_R0, FILE), (UC_ARM_REG_R1, lo),
                     (UC_ARM_REG_R2, hi - 1), (UC_ARM_REG_R3, TAIL),
                     (UC_ARM_REG_SP, STACK), (UC_ARM_REG_LR, STOP)):
        reader.cpu.reg_write(reg, val)
    reader.cpu.mem_write(STACK, struct.pack("<I", 1))
    reader.cpu.emu_start(DISP_BASE + 0xABC4, STOP, count=900_000_000)
    assert reader.crc_ok and reader.bad_record is None, f"{name}: CRC/record failed"
    assert reader.cpu.reg_read(UC_ARM_REG_R0) == len(expected), f"{name}: copied len mismatch"
    assert bytes(reader.cpu.mem_read(TAIL, len(expected))) == bytes(expected), f"{name}: copied bytes mismatch"
    print(f"PASS: stock DISPLAY updater accepted {name} and copied {len(expected)} B in [{lo:#x}, {hi:#x})")


def verify_hooks_disasm(image: bytes, name: str, objdump: Path):
    codec = sfl_codec()
    _, records = read_main(codec, image)
    base = 0xFFE80000
    flat = bytearray([0xFF] * 0x110000)
    for kind, addr, data, _ in records:
        if kind == "3" and base <= addr and addr + len(data) <= base + len(flat):
            flat[addr - base : addr - base + len(data)] = data

    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tf:
        tf.write(flat)
        tmp_path = Path(tf.name)
    try:
        def dis(addr, span):
            out = subprocess.check_output(
                [str(objdump), "-D", "-b", "binary", "-m", "rx", f"--adjust-vma={base:#x}",
                 f"--start-address={addr:#x}", f"--stop-address={addr + span:#x}", str(tmp_path)],
                text=True,
            )
            return [l.strip() for l in out.splitlines() if ":\t" in l]

        checks = [
            (0xFFF1ABD3, 4, "bra.a", "0xfff68ba"),
            (0xFFEE4E46, 6, "bra.a", "0xfff6"),
            (0xFFEE4E72, 4, "bra.a", "0xfff6"),
            (0xFFED8CB3, 4, "bsr.a", "0xfff6"),
            (0xFFF01906, 5, "bra.a", "0xfff6"),
            (0xFFF00566, 4, "bra.a", "0xfff6"),
            (0xFFEC9E4B, 13, "movu.b\t5[r0], r1", None),
            (0xFFEC9E4D, 4, "bsr.a", "0xfff6"),
            (0xFFEF2A05, 5, "bra.a", "0xfff6"),
            (0xFFF2C864, 5, "bra.a", "0xfff6"),
            (0xFFEFEC81, 4, "movu.b\t202[r14], r14", None),  # stock FUNC long-press preserved
        ]
        for addr, span, op, tgt_prefix in checks:
            lines = dis(addr, span)
            assert lines, f"{name}: empty disasm at {addr:#x}"
            joined = " | ".join(lines)
            assert op in lines[0], f"{name} @ {addr:#x}: expected {op!r} in {joined!r}"
            if tgt_prefix:
                assert tgt_prefix in lines[0], f"{name} @ {addr:#x}: expected target {tgt_prefix!r} in {joined!r}"
        print(f"PASS: all 9 MAIN softkey hooks + stock FUNC long-press verified in {name}")
    finally:
        tmp_path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--toolchain", type=Path, required=True, help="GNURX bin directory")
    parser.add_argument("image", type=Path, help="Standalone softkey MAIN test image")
    args = parser.parse_args()
    objdump = args.toolchain / "rx-elf-objdump.exe"
    display = (ROOT / "work/dec/display/display.bin").read_bytes()
    image = args.image.read_bytes()
    verify_updater_range(display, image, C2_CODE, C2_LIMIT, str(args.image))
    verify_hooks_disasm(image, str(args.image), objdump)


if __name__ == "__main__":
    main()
