"""Build the standalone CW decoder for JP DISPLAY V01-10."""

import argparse
import hashlib
import sys
from pathlib import Path

from elftools.elf.elffile import ELFFile

from build_ft8_menu import (
    FUNC_TILE_HOOK, HOLE_OFFSET, IMAGE_BASE, PATCH, PAYLOAD, ROOT, STOCK_HASH, ZIG,
    branch_hooks, label_hooks, run,
)
from sq9pd_apply import apply_sq9pd_display
from test_ft8_menu import read_display_sfl


HOOKS = (
    FUNC_TILE_HOOK,
    (0x0232E0, "f0472de9", False, "cw_touch"),
    (0x02387C, "578a02ea", False, "cw_panel_hit"),
    (0x0438F4, "bff9ffeb", True, "cw_ui_worker"),
    (0x043AE8, "2fb401fa", True, "cw_pre_swap"),
    (0x012A38, "f70700eb", True, "cw_key_send_hook"),
    (0x0C9D00, "55feffeb", True, "cw_readback_hook"),
    (0x045170, "cfffffeb", True, "cw_capture"),
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zig", type=Path, default=ZIG)
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("-o", "--out", type=Path, required=True)
    args = parser.parse_args()
    stock = (ROOT / "work/dec/display/display.bin").read_bytes()
    if hashlib.sha256(stock).hexdigest() != STOCK_HASH:
        parser.error("Expected the stock DISPLAY V01-10 payload from the JP package")

    args.build_dir.mkdir(parents=True, exist_ok=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    elf = args.build_dir / "cw.elf"
    binary = args.build_dir / "cw.bin"
    run(args.zig, "cc", "-target", "arm-freestanding-eabi", "-mcpu=cortex_a9",
        "-marm", "-Oz", "-g", "-ffreestanding", "-fno-builtin", "-fno-stack-protector",
        "-fno-unwind-tables", "-nostdlib", "-Wall", "-Wextra", "-Werror",
        f"-Wl,-T,{PAYLOAD / 'ft8_menu.ld'}", "-Wl,-e,cw_ui_worker", "-Wl,--no-undefined",
        "-Wl,--gc-sections", PAYLOAD / "cw_panel.c", PAYLOAD / "cw_decode.c",
        PAYLOAD / "cw_touch.S", PAYLOAD / "func_menu_tile.S", "-o", elf)
    run(args.zig, "objcopy", "-O", "binary", elf, binary)
    payload = binary.read_bytes()
    with elf.open("rb") as file:
        linked = ELFFile(file)
        section = linked.get_section_by_name(".payload")
        if section["sh_addr"] != IMAGE_BASE + HOLE_OFFSET or section.data() != payload:
            raise ValueError("Unexpected CW payload layout")
        hooks = branch_hooks(linked, HOOKS) + label_hooks(linked)
    run(sys.executable, "-I", PATCH / "merge_display.py",
        "--payload", f"{binary}@{HOLE_OFFSET:#x}", *hooks, "-o", args.out)

    base = bytes(apply_sq9pd_display(bytearray(stock)))
    image = read_display_sfl(args.out)
    allowed = {offset + i for offset, *_ in HOOKS for i in range(4)}
    allowed.update((0xC04D6, 0xC04D7))
    allowed.update(range(0x1F3A8, 0x1F3B0))
    allowed.update(range(HOLE_OFFSET, HOLE_OFFSET + len(payload)))
    if (image[HOLE_OFFSET:HOLE_OFFSET + len(payload)] != payload or len(image) != len(base)
            or any(a != b and i not in allowed for i, (a, b) in enumerate(zip(image, base)))):
        raise ValueError("Packaged CW firmware differs outside the approved patch sites")
    print(f"CW payload {len(payload)} / 10970 B. Stock image size preserved.")


if __name__ == "__main__":
    main()
