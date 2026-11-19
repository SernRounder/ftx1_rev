"""Build MAIN V01-13 with 4-page bottom softkeys, Setting Menu editor, and FUNC menu button."""

import argparse
import hashlib
import subprocess
import zlib
from pathlib import Path

from elftools.elf.elffile import ELFFile

from build_ft8_main import (
    BASES, MAIN_HEADER_LINE, SFL_CRC_MAGIC, branch,
    compile_payload as compile_ft8_payload, read_main, sfl_codec,
)
from build_ft8_menu import PAYLOAD, ROOT

C2_CODE = 0xFFF68BA0
C2_LIMIT = 0xFFF69165

SOFTKEY_HOOKS = (
    (0xFFF1ABD3, "05a7cf00", False, "softkey_menu_reg_hook"),
    (0xFFEE4E46, "fbe2ddb80100", False, "softkey_load_slots"),
    (0xFFEE4E72, "60408089", False, "softkey_get_slot"),
    (0xFFED8CB3, "05842401", True, "softkey_format_val"),
    (0xFFF01906, "7100f08389", False, "softkey_lookup_id"),
    (0xFFF00566, "6611ef12", False, "softkey_slot0_next_hook"),
    (0xFFEF2A05, "fe0ef56701", False, "softkey_menu_exit_hook"),
    (0xFFF2C864, "39f205670b", False, "softkey_func_dial_hook"),
)
TX_GATE_ADDR = 0xFFEC9E4B
TX_GATE_ORIG = bytes.fromhex("fbe251140000490e055aee083e")


def compile_softkey_payload(toolchain: Path, work: Path):
    def run(program, *args):
        exe = toolchain / f"rx-elf-{program}.exe"
        subprocess.run([str(exe), *map(str, args)], check=True)

    asm, obj, hooks, elf = (work / n for n in ("softkey.s", "softkey.o", "softkey_hooks.o", "softkey_main.elf"))
    run("gcc", "-S", "-Os", "-fno-tree-tail-merge", "-fno-tree-dominator-opts", "-fno-tree-reassoc",
        "-Wall", "-Wextra", "-Werror", "-ffreestanding", "-fno-unwind-tables",
        PAYLOAD / "softkey_main.c", "-o", asm)
    run("as", asm, "-o", obj)
    run("as", PAYLOAD / "softkey_main_hooks.S", "-o", hooks)
    run("ld", "--relax", "-T", PAYLOAD / "softkey_main.ld", hooks, obj, "-o", elf)

    with elf.open("rb") as f:
        ef = ELFFile(f)
        sec = ef.get_section_by_name(".payload")
        if sec["sh_addr"] != C2_CODE:
            raise ValueError(f"Unexpected C2 address {sec['sh_addr']:#x}")
        for s in ef.iter_sections():
            if s.name != ".payload" and s["sh_flags"] & 2 and s["sh_size"]:
                raise ValueError(f"Unexpected loadable section {s.name} ({s['sh_size']} B)")
        data = sec.data()
        if C2_CODE + len(data) > C2_LIMIT:
            raise ValueError(f"softkey payload {len(data)} B exceeds C2 limit {C2_LIMIT - C2_CODE} B")

        syms = ef.get_section_by_name(".symtab")

        def sym_addr(name):
            found = syms.get_symbol_by_name(name) or syms.get_symbol_by_name(f"_{name}")
            if not found:
                raise KeyError(name)
            return found[0]["st_value"]

        edits = {}
        for addr, expected, link, name in SOFTKEY_HOOKS:
            orig = bytes.fromhex(expected)
            tgt = sym_addr(name)
            if not C2_CODE <= tgt < C2_CODE + len(data):
                raise ValueError(f"{name} ({tgt:#x}) outside C2 payload")
            edits[addr] = (orig, branch(addr, tgt, link, len(orig)))

        get_slot = sym_addr("softkey_get_slot")
        tx_patch = b"\xb1\x09" + branch(TX_GATE_ADDR + 2, get_slot, True, 4) + b"\xef\x1e" + b"\x03" * 5
        assert len(tx_patch) == len(TX_GATE_ORIG)
        edits[TX_GATE_ADDR] = (TX_GATE_ORIG, tx_patch)
        return data, edits


def pack_combined(baseline: bytes, output: Path, c2_payload: bytes, edits: dict,
                  ft8_payload: bytes | None = None):
    from build_ft8_main import MAIN_APP_LIMIT, MAIN_CODE

    sfl = sfl_codec()
    header, records = read_main(sfl, baseline)

    changed = {addr + i: pair for addr, (old, new) in edits.items()
               for i, pair in enumerate(zip(old, new, strict=True))}
    c2_end = C2_CODE + len(c2_payload)
    c2_seen = set()
    hook_seen = set()
    rebuilt = []

    for kind, address, data, _ in records:
        upd = bytearray(data)
        if kind == "3":
            for loc in changed.keys() & range(address, address + len(data)):
                old, new = changed[loc]
                if loc in hook_seen or data[loc - address] != old:
                    raise ValueError(f"Unexpected stock byte at {loc:#x}: got {data[loc - address]:#x}, want {old:#x}")
                upd[loc - address] = new
                hook_seen.add(loc)
            for loc in range(max(address, C2_CODE), min(address + len(data), c2_end)):
                if loc in changed:
                    raise ValueError(f"Hook overlaps C2 at {loc:#x}")
                upd[loc - address] = c2_payload[loc - C2_CODE]
                c2_seen.add(loc)
            if ft8_payload is not None and address < MAIN_CODE + len(ft8_payload) and address + len(data) > MAIN_CODE:
                raise ValueError("FT8 payload overlaps stock flash record")
        rebuilt.append((kind, address, bytes(upd), True))

    if hook_seen != changed.keys():
        raise ValueError(f"Missing hook addresses: {sorted(hex(a) for a in changed.keys() - hook_seen)}")
    if len(c2_seen) != len(c2_payload):
        raise ValueError(f"C2 bytes missed S3 coverage: {len(c2_seen)} != {len(c2_payload)}")

    if ft8_payload is not None:
        if not ft8_payload or MAIN_CODE + len(ft8_payload) > MAIN_APP_LIMIT:
            raise ValueError("FT8 MAIN payload exceeds erase block")
        insert_at = next(i for i, r in enumerate(rebuilt) if r[1] == 0xFFFFFF00)
        _, last_addr, last_data, _ = rebuilt[insert_at - 1]
        if last_addr + len(last_data) != MAIN_CODE:
            raise ValueError("Unexpected end of stock MAIN application")
        rebuilt[insert_at:insert_at] = [
            ("3", MAIN_CODE + off, ft8_payload[off:off + 16], True)
            for off in range(0, len(ft8_payload), 16)
        ]

    plaintext = "".join(sfl.format_srecord(*r[:3]) + "\r\n" for r in rebuilt)
    encrypted = sfl.encode_bytes(plaintext.encode("ascii"), 0)
    crc = zlib.crc32(encrypted + SFL_CRC_MAGIC)
    size = len(header) + len(encrypted)
    new_header = MAIN_HEADER_LINE.sub(
        lambda m: m[1] + str(size).encode("ascii") + m[3] + f"{crc:08X}".encode("ascii") + m[5],
        header, count=1,
    )
    if len(new_header) != len(header):
        raise ValueError("MAIN SFL header size changed")
    final = new_header + encrypted
    _, rt = read_main(sfl, final)
    if rt != rebuilt:
        raise ValueError("MAIN S-records did not round-trip")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(final)
    ft8_msg = f" + {len(ft8_payload)} B FT8" if ft8_payload is not None else ""
    print(f"{output.name}: {len(c2_payload)}/{C2_LIMIT - C2_CODE} B in C2{ft8_msg}, SHA-256 {hashlib.sha256(final).hexdigest()}")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--baseline", type=Path, default=ROOT / "work/fw/FTX-1_MAIN_V0113.SFL")
    p.add_argument("--toolchain", type=Path, required=True, help="GNURX bin directory")
    p.add_argument("--build-dir", type=Path, required=True)
    p.add_argument("--with-ft8", action="store_true", help="Also include FT8 MAIN TX hooks")
    p.add_argument("-o", "--out", type=Path, required=True)
    args = p.parse_args()

    baseline = args.baseline.read_bytes()
    if hashlib.sha256(baseline).hexdigest() not in BASES:
        p.error("Expected the supported JP MAIN V01-13 SFL")
    args.build_dir.mkdir(parents=True, exist_ok=True)

    c2_payload, edits = compile_softkey_payload(args.toolchain, args.build_dir)
    ft8_payload = None
    if args.with_ft8:
        ft8_payload, ft8_edits = compile_ft8_payload(args.toolchain, args.build_dir)
        overlap = edits.keys() & ft8_edits.keys()
        if overlap:
            raise ValueError(f"Hook collision with ft8_main: {overlap}")
        edits.update(ft8_edits)
    pack_combined(baseline, args.out, c2_payload, edits, ft8_payload)


if __name__ == "__main__":
    main()
