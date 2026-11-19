"""Integration tests for sq9pd + FT8/CW_DEC MAIN V01-13 firmware build."""

import argparse
import hashlib
import re
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

from elftools.elf.elffile import ELFFile

PATCH_DIR = Path(__file__).resolve().parent
ROOT = PATCH_DIR.parent
sys.path.insert(0, str(PATCH_DIR))

from build_ft8_main import (  # noqa: E402
    C2_CODE, C2_LIMIT, MAIN_APP_LIMIT, MAIN_CODE, MAIN_HEADER_LINE,
    SFL_CRC_MAGIC, compile_payload, pack_image, read_main, sfl_codec,
)
from sq9pd_apply import (  # noqa: E402
    apply_sq9pd_display_payload, apply_sq9pd_main_records,
    apply_sq9pd_main_rom, load_sq9pd_data,
)
from test_ft8_main_updater import Reader  # noqa: E402

STOCK_MAIN = ROOT / "work/fw/FTX-1_MAIN_V0113.SFL"
STOCK_DISPLAY = ROOT / "work/fw/FTX-1_DISPLAY_V0110.SFL"
DISPLAY_BIN = ROOT / "work/dec/display/display.bin"
DEFAULT_TOOLCHAIN = Path(tempfile.gettempdir()) / "ftx1-gnurx/selected/bin"
SQ9PD_REPO = ROOT / "work/tools/Yaesu-FTX-1-mod"


def build_flat_rom(records):
    rom = bytearray(b"\xff" * 0x180000)
    for kind, addr, data, valid in records:
        assert valid
        if kind == "3" and 0xFFE80000 <= addr < 0x100000000:
            off = addr - 0xFFE80000
            rom[off:off + len(data)] = data
    return rom


def objdump_disasm(toolchain: Path, rom_path: Path, start: int, stop: int) -> str:
    objdump = toolchain / "rx-elf-objdump.exe"
    res = subprocess.run(
        [
            str(objdump), "-D", "-b", "binary", "-m", "rx",
            "--adjust-vma=0xFFE80000",
            f"--start-address={start:#x}",
            f"--stop-address={stop:#x}",
            str(rom_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return res.stdout


def test_sq9pd_apply_parity_and_guards(sfl):
    data = load_sq9pd_data()
    assert len(data["main"]["runs"]) == 322
    assert sum(len(bytes.fromhex(o)) for _, o, _ in data["main"]["runs"]) == 10573
    assert len(data["display"]["runs"]) == 47
    assert sum(len(bytes.fromhex(o)) for _, o, _ in data["display"]["runs"]) == 4117
    assert sum(
        1 for _, o, n in data["display"]["runs"]
        for a, b in zip(bytes.fromhex(o), bytes.fromhex(n)) if a != b
    ) == 4031

    stock_main_bytes = STOCK_MAIN.read_bytes()
    hdr, recs = read_main(sfl, stock_main_bytes)
    patched_recs = apply_sq9pd_main_records(recs, data=data)
    pt = "".join(sfl.format_srecord(*r[:3]) + "\r\n" for r in patched_recs).encode("ascii")
    assert hashlib.sha256(pt).hexdigest() == data["main"]["decoded_output_sha256"]

    enc = sfl.encode_bytes(pt, 0)
    crc = zlib.crc32(enc + SFL_CRC_MAGIC)
    hdr_new = MAIN_HEADER_LINE.sub(
        lambda m: m[1] + str(len(hdr) + len(enc)).encode("ascii") + m[3] + f"{crc:08X}".encode("ascii") + m[5],
        hdr, count=1,
    )
    standalone_main_sfl = hdr_new + enc

    rom = build_flat_rom(recs)
    apply_sq9pd_main_rom(rom, 0xFFE80000, data=data)
    assert bytes(rom) == bytes(build_flat_rom(patched_recs))

    # Mismatch guard on MAIN ROM (must raise without mutating)
    bad_rom = build_flat_rom(recs)
    first_addr = int(data["main"]["runs"][0][0], 16)
    bad_rom[first_addr - 0xFFE80000] ^= 0xFF
    snap_rom = bytes(bad_rom)
    try:
        apply_sq9pd_main_rom(bad_rom, 0xFFE80000, data=data)
    except ValueError:
        assert bytes(bad_rom) == snap_rom
    else:
        raise AssertionError("apply_sq9pd_main_rom failed to reject mismatched byte")

    # DISPLAY payload parity + mismatch guard
    key = bytes.fromhex(
        "1e271b12111619172425291c0d0b060403010205070c0e0f"
        "181d20222a2b08090a101314151a1f21282326"
    )
    stock_disp_bytes = STOCK_DISPLAY.read_bytes()
    disp_plain = bytearray((v - key[i % len(key)]) & 0xFF for i, v in enumerate(stock_disp_bytes[576:]))
    assert hashlib.sha256(disp_plain).hexdigest() == data["display"]["stock_sha256"]
    apply_sq9pd_display_payload(disp_plain, data=data)
    assert hashlib.sha256(disp_plain).hexdigest() == data["display"]["patched_sha256"]

    bad_disp = bytearray((v - key[i % len(key)]) & 0xFF for i, v in enumerate(stock_disp_bytes[576:]))
    disp_pos0 = int(data["display"]["runs"][0][0], 16)
    bad_disp[disp_pos0] ^= 0xFF
    snap_disp = bytes(bad_disp)
    try:
        apply_sq9pd_display_payload(bad_disp, data=data)
    except ValueError:
        assert bytes(bad_disp) == snap_disp
    else:
        raise AssertionError("apply_sq9pd_display_payload failed to reject mismatched byte")

    if (SQ9PD_REPO / "patch.py").is_file():
        sys.path.insert(0, str(SQ9PD_REPO))
        import patch as sq_patch  # type: ignore

        _, sq_main_sfl = sq_patch.patch(stock_main_bytes)
        assert hashlib.sha256(standalone_main_sfl).hexdigest() == hashlib.sha256(sq_main_sfl).hexdigest()

        disp_enc = bytes((v + key[i % len(key)]) & 0xFF for i, v in enumerate(disp_plain))
        disp_crc = zlib.crc32(SFL_CRC_MAGIC, zlib.crc32(disp_enc)) & 0xFFFFFFFF
        disp_hdr = re.sub(
            rb"(?m)^(PC +)(\d+)( +)([0-9A-F]{8})( +\r\n)$",
            lambda m: m[1] + str(len(stock_disp_bytes)).encode("ascii") + m[3] + f"{disp_crc:08X}".encode("ascii") + m[5],
            stock_disp_bytes[:576], count=1,
        )
        _, sq_disp_sfl = sq_patch.patch(stock_disp_bytes)
        assert hashlib.sha256(disp_hdr + disp_enc).hexdigest() == hashlib.sha256(sq_disp_sfl).hexdigest()

    print("PASS: sq9pd_apply standalone SHA-256 parity and byte-mismatch guards")


def verify_built_image(sfl, toolchain: Path, baseline_path: Path, build_dir: Path, out_sfl: Path):
    build_dir.mkdir(parents=True, exist_ok=True)
    payload, c2_payload, edits = compile_payload(toolchain, build_dir)
    assert 0 < len(payload) <= MAIN_APP_LIMIT - MAIN_CODE
    assert 0 < len(c2_payload) <= C2_LIMIT - C2_CODE

    baseline_bytes = baseline_path.read_bytes()
    pack_image(baseline_bytes, out_sfl, payload, c2_payload, edits)
    built_bytes = out_sfl.read_bytes()
    _, recs = read_main(sfl, built_bytes)
    rom = build_flat_rom(recs)

    elf_path = build_dir / "ft8_main.elf"
    with elf_path.open("rb") as f:
        ef = ELFFile(f)
        syms = ef.get_section_by_name(".symtab")

        def sym(name):
            return syms.get_symbol_by_name(name)[0]["st_value"]

        timer_addr = sym("_ft8_main_timer")
        btn_table_addr = sym("_ft8_custom_btn_table")
        key_ft8_addr = sym("_ft8_custom_key_ft8")
        key_cw_addr = sym("_ft8_custom_key_cw")
        ft8_click_addr = sym("_ft8_custom_ft8_click")
        cw_click_addr = sym("_ft8_custom_cw_click")
        id_hook_addr = sym("ft8_custom_key_by_id_hook")
        code_hook_addr = sym("ft8_custom_key_by_code_hook")
        en_hook_addr = sym("ft8_custom_softkey_enable_hook")
        fmt_hook_addr = sym("ft8_custom_softkey_fmt_hook")
        status_hook_addr = sym("ft8_main_status_hook")
        key_fn_addr = sym("_key")

    rom_path = build_dir / "built_main.bin"
    rom_path.write_bytes(rom)

    # 1. Verify ISR timer chain: 0xFFEA1E41 -> 0xFFF0CC47 -> _ft8_main_timer -> _stock_timer_tick
    d_isr = objdump_disasm(toolchain, rom_path, 0xFFEA1E3D, 0xFFEA1E4B)
    assert "bsr.a\t0xfff0cc47" in d_isr, d_isr
    d_chain = objdump_disasm(toolchain, rom_path, 0xFFF0CC47, 0xFFF0CC71)
    assert f"bsr.a\t{timer_addr:#x}" in d_chain, d_chain
    d_timer = objdump_disasm(toolchain, rom_path, timer_addr, timer_addr + 0x20)
    assert "bsr.a\t0xffea5030" in d_timer, d_timer

    # 2. Verify 72-entry table and 4 bounds updates (70->72 / 69->71)
    data = load_sq9pd_data()
    expected_table = bytes.fromhex(data["main"]["button_table_70_hex"]) + b"\xee\xef"
    off_tbl = btn_table_addr - 0xFFE80000
    assert bytes(rom[off_tbl:off_tbl + 72]) == expected_table
    assert rom[off_tbl + 70] == 0xEE and rom[off_tbl + 71] == 0xEF

    assert "cmp\t#72, r3" in objdump_disasm(toolchain, rom_path, 0xFFF0C7F3, 0xFFF0C7FC)
    d_slot = objdump_disasm(toolchain, rom_path, 0xFFF0CFEE, 0xFFF0D000)
    assert "cmp\t#72, r1" in d_slot and f"mov.l\t#{btn_table_addr:#x}, r14" in d_slot, d_slot
    assert "cmp\t#72, r4" in objdump_disasm(toolchain, rom_path, 0xFFF0D03B, 0xFFF0D045)
    assert "mov.l\t#71, r2" in objdump_disasm(toolchain, rom_path, 0xFFF0D0B5, 0xFFF0D0BF)
    d_tag = objdump_disasm(toolchain, rom_path, 0xFFF0D295, 0xFFF0D2A3)
    assert f"mov.l\t#{btn_table_addr:#x}, r14" in d_tag, d_tag

    # 3. Verify C2 dispatch & softkey hooks
    assert f"bra.a\t{id_hook_addr:#x}" in objdump_disasm(toolchain, rom_path, 0xFFF0ED3F, 0xFFF0ED48)
    assert f"bra.a\t{code_hook_addr:#x}" in objdump_disasm(toolchain, rom_path, 0xFFF0EDC1, 0xFFF0EDC9)
    assert f"bra.a\t{en_hook_addr:#x}" in objdump_disasm(toolchain, rom_path, 0xFFF004F3, 0xFFF004F8)
    assert f"bra.a\t{fmt_hook_addr:#x}" in objdump_disasm(toolchain, rom_path, 0xFFF0F1CE, 0xFFF0F1D3)

    off_k1 = key_ft8_addr - 0xFFE80000
    off_k2 = key_cw_addr - 0xFFE80000
    assert struct.unpack("<HBBII", rom[off_k1:off_k1 + 12]) == (0x0596, 0, 0, 0xEE, ft8_click_addr)
    assert struct.unpack("<HBBII", rom[off_k2:off_k2 + 12]) == (0x0597, 0, 0, 0xEF, cw_click_addr)

    # 4. Verify the common header hook and preserve the stock byte-34 writer.
    d_common = objdump_disasm(toolchain, rom_path, 0xFFED7F3F, 0xFFED7F65)
    assert f"bsr.a\t{status_hook_addr:#x}" in d_common and "bsr.w\t0xffedad91" in d_common
    for caller in (0xFFED7996, 0xFFEE4019, 0xFFEDCC3A):
        assert "0xffed7a49" in objdump_disasm(toolchain, rom_path, caller, caller + 4)
    for caller in (0xFFEE4071, 0xFFEE43E3):
        assert "0xffedcc3a" in objdump_disasm(toolchain, rom_path, caller, caller + 3)
    d_status = objdump_disasm(toolchain, rom_path, status_hook_addr, status_hook_addr + 0x90)
    assert "0x1b485" in d_status and "0x1b49c" in d_status and "15[r5]" in d_status, d_status
    for address in ("0xffee401d", "0xffed7999", "0xffedcc3d", "0xffee4074", "0xffee43e6"):
        assert address in d_status
    d_key = objdump_disasm(toolchain, rom_path, key_fn_addr, key_fn_addr + 0x30)
    assert "0x84c6" in d_key, d_key

    # 6. Verify stock DISPLAY SFL/S-record updater accepts the built image
    if DISPLAY_BIN.is_file():
        display = DISPLAY_BIN.read_bytes()
        expected_tail = b"".join(
            d for k, addr, d, _ in recs if k == "3" and MAIN_CODE <= addr < MAIN_APP_LIMIT
        )
        reader = Reader(display, built_bytes)
        assert reader.tail() == len(expected_tail)
        assert reader.crc_ok and reader.bad_record is None

    print(
        f"PASS: verified {baseline_path.parent.name} -> {out_sfl.name} "
        f"(MAIN {len(payload)}/574 B, C2 {len(c2_payload)}/1477 B)"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--toolchain", type=Path, default=DEFAULT_TOOLCHAIN)
    args = parser.parse_args()
    sfl = sfl_codec()
    test_sq9pd_apply_parity_and_guards(sfl)
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        verify_built_image(
            sfl, args.toolchain, STOCK_MAIN,
            td_path / "build_stock", td_path / "main_stock.sfl",
        )



if __name__ == "__main__":
    main()
