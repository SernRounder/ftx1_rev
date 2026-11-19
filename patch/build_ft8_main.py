"""Build the MAIN V01-13 counterpart for native FT8 transmission."""

import argparse
import hashlib
import importlib.util
import re
import struct
import subprocess
import zlib
from pathlib import Path

from elftools.elf.elffile import ELFFile

from build_ft8_menu import ROOT, PAYLOAD
from sq9pd_apply import apply_sq9pd_main_records, load_sq9pd_data

BASES = {
    "de02ce415b37ca6621ed0bac2f8e7bd63d45f3022a62868598950502ed033f5c",
}
MAIN_CODE = 0xFFF87DC2
MAIN_APP_LIMIT = 0xFFF88000
C2_CODE = 0xFFF68BA0
C2_LIMIT = 0xFFF69165
FT8_RAM_LIMIT = 0x3F880
STOCK_ZERO_END = 0xFFE9B7E0
SFL_CRC_MAGIC = bytes.fromhex("8f93c635")
MAIN_HEADER_LINE = re.compile(rb"(?m)^(MC +)(\d+)( +)([0-9A-F]{8})( +\r\n)$")
HOOKS = (
    # Chain sq9pd's ISR hook (0xFFEA1E41 -> bsr.a 0xFFF0CC47) into _ft8_main_timer.
    (0xFFF0CC47, "05e983f9", True, "_ft8_main_timer"),
    (0xFFEA12FB, "05c2630b", True, "_ft8_main_service"),
    (0xFFED60CB, "399b082e22", False, "ft8_main_command_hook"),
    (0xFFED7AF1, "fecef16c41", True, "ft8_main_voice_status_hook"),
    # This reserved write is inside the common 0x20/0x60/0x62 packet builder.
    (0xFFED7F3F, "b981fbe27cb40100660ffe0e1f", True, "ft8_main_status_hook"),
    (0xFFF0D076, "05a223ff", True, "_ft8_main_swr_open_hook"),
    # R2 custom button dispatch & softkey formatting/enable hooks for 0xEE (FT8) & 0xEF (CW_DEC).
    (0xFFF0ED42, "0414efff", False, "ft8_custom_key_by_id_hook"),
    (0xFFF0EDC5, "0451daff", False, "ft8_custom_key_by_code_hook"),
    (0xFFF004F3, "04c5db00", False, "ft8_custom_softkey_enable_hook"),
    (0xFFF0F1CE, "04dff0ff", False, "ft8_custom_softkey_fmt_hook"),
)
BTN_COUNT_EDITS = (
    (0xFFF0C7F6, "755346", "755348"),  # BTN1 validator: cmp #70, r3 -> cmp #72, r3
    (0xFFF0CFEE, "755146", "755148"),  # softkey slot resolver: cmp #70, r1 -> cmp #72, r1
    (0xFFF0D03E, "755446", "755448"),  # menu display callback: cmp #70, r4 -> cmp #72, r4
    (0xFFF0D0B7, "754245", "754247"),  # menu stepper max: mov.l #69, r2 -> mov.l #71, r2
)


def branch(src, dst, link, span):
    displacement = dst - src
    if not -(1 << 23) <= displacement < (1 << 23) or span < 4:
        raise ValueError(f"Invalid RX branch {src:#x} -> {dst:#x}")
    return bytes((0x05 if link else 0x04,)) + displacement.to_bytes(3, "little", signed=True) + b"\x03" * (span - 4)


def compile_payload(toolchain, work):
    work.mkdir(parents=True, exist_ok=True)

    def run(program, *args):
        executable = toolchain / f"rx-elf-{program}.exe"
        subprocess.run([str(executable), *map(str, args)], check=True)

    asm, obj, hooks, elf = (work / name for name in ("main.s", "main.o", "hooks.o", "ft8_main.elf"))
    run("gcc", "-S", "-Os", "-fno-tree-tail-merge", "-fno-tree-dominator-opts", "-fno-tree-reassoc",
        "-Wall", "-Wextra", "-Werror", "-ffreestanding",
        "-fno-unwind-tables", PAYLOAD / "ft8_main.c", "-o", asm)
    run("as", asm, "-o", obj)
    run("as", PAYLOAD / "ft8_main_hooks.S", "-o", hooks)
    run("ld", "--relax", "-T", PAYLOAD / "ft8_main.ld", hooks, obj, "-o", elf)
    with elf.open("rb") as f:
        file = ELFFile(f)
        payload = file.get_section_by_name(".payload")
        c2 = file.get_section_by_name(".c2")
        if payload["sh_addr"] != MAIN_CODE:
            raise ValueError("Unexpected MAIN payload address")
        if not payload["sh_size"] or MAIN_CODE + payload["sh_size"] > MAIN_APP_LIMIT:
            raise ValueError("FT8 MAIN payload exceeds the stock application erase block")
        if not c2 or c2["sh_addr"] != C2_CODE:
            raise ValueError("Unexpected C2 payload address")
        if not c2["sh_size"] or C2_CODE + c2["sh_size"] > C2_LIMIT:
            raise ValueError("FT8 C2 payload exceeds the C2 dead-code hole")
        for section in file.iter_sections():
            if section.name not in (".payload", ".c2") and section["sh_flags"] & 2 and section["sh_size"]:
                raise ValueError(f"Unexpected loadable section {section.name}")
        payload_data = payload.data()
        c2_data = c2.data()
        symbols = file.get_section_by_name(".symtab")
        # The stock startup routine zeros BSS before copying its initialized
        # data, so that data is restored when the zero pass also covers the
        # new session at 0x3f870. Keep the reset vector and reset code intact.
        edits = {STOCK_ZERO_END: (struct.pack("<I", 0x3F440), struct.pack("<I", FT8_RAM_LIMIT))}
        for address, expected, link, symbol in HOOKS:
            original = bytes.fromhex(expected)
            target = symbols.get_symbol_by_name(symbol)[0]["st_value"]
            in_main = MAIN_CODE <= target < MAIN_CODE + len(payload_data)
            in_c2 = C2_CODE <= target < C2_CODE + len(c2_data)
            if not (in_main or in_c2):
                raise ValueError(f"{symbol} ({target:#x}) lies outside MAIN and C2 payloads")
            edits[address] = (original, branch(address, target, link, len(original)))

        btn_table = symbols.get_symbol_by_name("_ft8_custom_btn_table")[0]["st_value"]
        if not C2_CODE <= btn_table <= C2_CODE + len(c2_data) - 72:
            raise ValueError(f"_ft8_custom_btn_table ({btn_table:#x}) lies outside C2 payload")
        expected_table = bytes.fromhex(load_sq9pd_data()["main"]["button_table_70_hex"]) + b"\xee\xef"
        actual_table = c2_data[btn_table - C2_CODE:btn_table - C2_CODE + 72]
        if actual_table != expected_table:
            raise ValueError("Unexpected 72-entry custom button table contents")
        if btn_table < 0xFF800000:
            raise ValueError(f"C2 table address {btn_table:#x} cannot be sign-extended from 24 bits")
        edits[0xFFF0CFF5] = (
            bytes.fromhex("fbe22ae6f0ff"),
            b"\xfb\xe2" + struct.pack("<I", btn_table),
        )
        edits[0xFFF0D297] = (
            bytes.fromhex("fbee2ae6f0"),
            b"\xfb\xee" + btn_table.to_bytes(4, "little")[:3],
        )
        for address, old_hex, new_hex in BTN_COUNT_EDITS:
            edits[address] = (bytes.fromhex(old_hex), bytes.fromhex(new_hex))
        return payload_data, c2_data, edits


def sfl_codec():
    spec = importlib.util.spec_from_file_location(
        "decode_sfl", ROOT / "work/tools/ft710-internals/decode_sfl.py",
    )
    sfl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sfl)
    return sfl


def read_main(sfl, image):
    kind, _, offset, header = sfl.detect_format(image)
    tag = MAIN_HEADER_LINE.search(header) if kind == "main" else None
    if not tag or tag.end() != offset or int(tag[2]) != len(image):
        raise ValueError("Invalid MAIN SFL header")
    encrypted = image[offset:]
    if int(tag[4], 16) != zlib.crc32(encrypted + SFL_CRC_MAGIC):
        raise ValueError("Invalid MAIN SFL CRC")
    # The stock updater carries the cipher position across the entire stream.
    # A literal CR can appear inside that encrypted stream. It does not reset
    # the cipher or necessarily correspond to a plaintext record boundary.
    lines = sfl.decode_bytes(encrypted, 0).decode("ascii").split("\r\n")
    if lines.pop() != "":
        raise ValueError("Unterminated MAIN S-record stream")
    records = []
    for line in lines:
        record = sfl.parse_srecord(line)
        if not record or not record[3] or sfl.format_srecord(*record[:3]) != line:
            raise ValueError("Invalid MAIN S-record")
        records.append(record)
    if not records or records[0][0] != "0" or records[-1][0] != "7":
        raise ValueError("Missing MAIN S-record header or entry")
    return header, records


def pack_image(baseline, output, payload, c2_payload, edits):
    if not payload or MAIN_CODE + len(payload) > MAIN_APP_LIMIT:
        raise ValueError("FT8 MAIN payload exceeds the stock application erase block")
    if not c2_payload or C2_CODE + len(c2_payload) > C2_LIMIT:
        raise ValueError("FT8 C2 payload exceeds the C2 dead-code hole")
    sfl = sfl_codec()
    header, records = read_main(sfl, baseline)
    records = apply_sq9pd_main_records(records)

    changed = {address + i: pair for address, (old, new) in edits.items()
               for i, pair in enumerate(zip(old, new, strict=True))}
    c2_end = C2_CODE + len(c2_payload)
    seen = set()
    c2_seen = set()
    rebuilt = []
    for kind, address, data, _ in records:
        updated = bytearray(data)
        if kind == "3":
            for location in changed.keys() & range(address, address + len(data)):
                old, new = changed[location]
                if location in seen or data[location - address] != old:
                    raise ValueError(f"Unexpected byte at {location:#x}: got {data[location - address]:#04x}, want {old:#04x}")
                updated[location - address] = new
                seen.add(location)
            for location in range(max(address, C2_CODE), min(address + len(data), c2_end)):
                if location in changed:
                    raise ValueError(f"Hook overlaps C2 at {location:#x}")
                updated[location - address] = c2_payload[location - C2_CODE]
                c2_seen.add(location)
            if address < MAIN_CODE + len(payload) and address + len(data) > MAIN_CODE:
                raise ValueError("MAIN payload overlaps a stock flash record")
        rebuilt.append((kind, address, bytes(updated), True))
    if seen != changed.keys():
        missing = sorted(hex(a) for a in changed.keys() - seen)
        raise ValueError(f"MAIN hook address missing from baseline: {missing[0]}")
    if len(c2_seen) != len(c2_payload):
        raise ValueError(f"C2 bytes missed S3 coverage: {len(c2_seen)} != {len(c2_payload)}")

    insert_at = next(i for i, record in enumerate(rebuilt) if record[1] == 0xFFFFFF00)
    _, last_address, last_data, _ = rebuilt[insert_at - 1]
    if last_address + len(last_data) != MAIN_CODE:
        raise ValueError("Unexpected end of the stock MAIN application")
    new_records = [("3", MAIN_CODE + offset, payload[offset:offset + 16], True)
                   for offset in range(0, len(payload), 16)]
    rebuilt[insert_at:insert_at] = new_records
    plaintext = "".join(sfl.format_srecord(*record[:3]) + "\r\n" for record in rebuilt)
    encrypted = sfl.encode_bytes(plaintext.encode("ascii"), 0)
    crc = zlib.crc32(encrypted + SFL_CRC_MAGIC)
    size = len(header) + len(encrypted)
    new_header = MAIN_HEADER_LINE.sub(lambda m: m[1] + str(size).encode("ascii") + m[3] +
                                     f"{crc:08X}".encode("ascii") + m[5], header, count=1)
    if len(new_header) != len(header):
        raise ValueError("MAIN SFL header size changed")
    final = new_header + encrypted
    _, roundtrip = read_main(sfl, final)
    if roundtrip != rebuilt:
        raise ValueError("MAIN S-records did not round-trip")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(final)
    print(
        f"{output.name}: {len(payload)}/{MAIN_APP_LIMIT - MAIN_CODE} B in MAIN flash, "
        f"{len(c2_payload)}/{C2_LIMIT - C2_CODE} B in C2, "
        f"SHA-256 {hashlib.sha256(final).hexdigest()}"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=ROOT / "work/fw/FTX-1_MAIN_V0113.SFL")
    parser.add_argument("--toolchain", type=Path, required=True, help="GNURX bin directory")
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("-o", "--out", type=Path, required=True)
    args = parser.parse_args()
    baseline = args.baseline.read_bytes()
    if hashlib.sha256(baseline).hexdigest() not in BASES:
        parser.error("Expected the supported JP MAIN V01-13 SFL")
    args.build_dir.mkdir(parents=True, exist_ok=True)
    payload, c2_payload, edits = compile_payload(args.toolchain, args.build_dir)
    pack_image(baseline, args.out, payload, c2_payload, edits)


if __name__ == "__main__":
    main()
