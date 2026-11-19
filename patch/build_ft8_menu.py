"""Build a DISPLAY V01-10 FT8 menu, probe, or integrated lab image."""

import argparse
import hashlib
import re
import struct
import subprocess
import sys
from pathlib import Path

from elftools.elf.elffile import ELFFile


PATCH = Path(__file__).resolve().parent
ROOT = PATCH.parent
PAYLOAD = PATCH / "payload"
ZIG = ROOT / "work/tools/zig-x86_64-windows-0.14.1/zig.exe"
IMAGE_BASE = 0x60400000
HOLE_OFFSET = 0x12C670
TAIL_OFFSET = 0x2C2FC0
VECTOR_OFFSET = 0x80
STOCK_HASH = "ba4a2fb2b1e7b00f3dd7353efd1548629caa339b77eab0900bed92204d57ceeb"

# Each tuple names the exact original instruction, branch type, and entry symbol.
FUNC_TILE_HOOK = (0x038868, "eaa700eb", True, "func_menu_tile")
HOOKS = (
    FUNC_TILE_HOOK,
    (0x0232E0, "f0472de9", False, "ft8_touch"),
    (0x0438F4, "bff9ffeb", True, "ft8_ui_worker"),
    (0x043AE8, "2fb401fa", True, "ft8_pre_swap"),
    (0x012A38, "f70700eb", True, "ft8_key_send_hook"),
)
PROBE_HOOK = (0x045170, "cfffffeb", True, "ft8_audio_probe")
LIVE_HOOK = (*PROBE_HOOK[:3], "ft8_live_capture")
RADIO_HOOKS = (
    (0x02387C, "578a02ea", False, "ft8_panel_hit"),
    (0x07C448, "040084e5", False, "ft8_radio_heap_hook"),
    (0x05FD48, "bb5c00eb", True, "ft8_radio_pool_hook"),
)
TX_HOOKS = (
    (0x0452B4, "c00086e5", False, "ft8_radio_source_hook"),
    (0x063DBC, "000081e5", False, "ft8_radio_done_hook"),
    (0x0C9D00, "55feffeb", True, "ft8_radio_readback_hook"),
    (0x024D80, "2ab2ffeb", True, "ft8_radio_gps_hook"),
    (0x011E78, "410051e3", True, "ft8_radio_gps_status_hook"),
)


def run(*args):
    subprocess.run([str(arg) for arg in args], check=True)


def arm_branch(source, target, link):
    displacement = target - (source + 8)
    if displacement % 4 or not -(1 << 25) <= displacement < (1 << 25):
        raise ValueError(f"Invalid ARM branch {source:#x} -> {target:#x}")
    opcode = 0xEB000000 if link else 0xEA000000
    return struct.pack("<I", opcode | ((displacement // 4) & 0xFFFFFF))


def branch_hooks(elf, patches, *, vectors=False):
    section = elf.get_section_by_name(".payload")
    symtab = elf.get_section_by_name(".symtab")
    hooks = []
    for index, (offset, expected, link, name) in enumerate(patches):
        symbol = symtab.get_symbol_by_name(f"vector_{name}" if vectors else name)[0]
        address = symbol["st_value"]
        if not section["sh_addr"] <= address < section["sh_addr"] + section["sh_size"]:
            raise ValueError(f"{name} outside the payload")
        if vectors:
            if address != IMAGE_BASE + TAIL_OFFSET + VECTOR_OFFSET + 4 * index or symbol["st_size"] != 4:
                raise ValueError(f"Unexpected vector slot for {name}")
            handler = symtab.get_symbol_by_name(name)[0]["st_value"]
            # A linker-generated interworking veneer can sit behind the slot.
            word, = struct.unpack_from("<I", section.data(), address - section["sh_addr"])
            if word >> 24 != 0xEA or not handler:
                raise ValueError(f"Invalid tail branch for {name}")
        branch = arm_branch(IMAGE_BASE + offset, address, link)
        hooks.extend(("--hook", f"{offset:#x}:{expected}:{branch.hex()}"))
    return hooks


def label_hooks(elf):
    symtab = elf.get_section_by_name(".symtab")
    address = symtab.get_symbol_by_name("ft8_custom_label")[0]["st_value"]
    trampoline = bytes.fromhex("dff800f0") + struct.pack("<I", address)
    return [
        "--hook", "0xc04d6:092b:0f2b",
        "--hook", f"0x1f3a8:bcf1080f03d80349:{trampoline.hex()}",
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zig", type=Path, default=ZIG)
    parser.add_argument("--build-dir", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--probe", action="store_true", help="Experimental audio and tail probe")
    mode.add_argument("--live", action="store_true", help="Integrated receiver lab image")
    mode.add_argument("--radio", action="store_true", help="Native DISPLAY development image for the VM")
    parser.add_argument("--tx-hooks", action="store_true", help="Wire the native TX DMA hooks for the VM")
    parser.add_argument("--custom-modes", action="store_true", help="Include the combined FT8 and CW menu")
    parser.add_argument("--sd-plugin", action="store_true", help="Enable the experimental SD queue formatter")
    parser.add_argument("--vfp", action="store_true", help="Enable worker-only FT8 FFT acceleration")
    parser.add_argument("--vfp-only", action="store_true", help="Require VFP for native FT8 receive")
    parser.add_argument("--cw-debounce", action="store_true", help="Use consecutive hops for CW key detection")
    parser.add_argument("--profile", action="store_true", help="Log native decoder timing to SD")
    parser.add_argument("--grid", help="Fallback Maidenhead locator for the integrated firmware")
    parser.add_argument("-o", "--out", type=Path)
    args = parser.parse_args()
    if args.profile and not args.vfp_only:
        parser.error("--profile requires --vfp-only")
    if args.tx_hooks and not args.radio:
        parser.error("--tx-hooks requires --radio")
    if args.custom_modes and not args.tx_hooks:
        parser.error("--custom-modes requires --radio --tx-hooks")
    if args.sd_plugin and not args.radio:
        parser.error("--sd-plugin requires --radio")
    args.vfp |= args.vfp_only
    if args.cw_debounce and not (args.custom_modes and args.vfp):
        parser.error("--cw-debounce requires --custom-modes and --vfp")
    if args.vfp and (not args.radio or args.sd_plugin):
        parser.error("--vfp requires --radio and the built-in queue formatter")
    if args.radio and args.out is None:
        parser.error("--radio is for VM development and requires an explicit --out path")
    live = args.live or args.radio
    if args.grid and (not live or not re.fullmatch("[A-Ra-r]{2}[0-9]{2}([A-Xa-x]{2})?", args.grid)):
        parser.error("--grid requires --live or --radio and a valid Maidenhead locator")
    kind = "radio" if args.radio else "live" if args.live else "probe" if args.probe else "menu"
    suffix = "LAB" if args.live else "TEST"
    out = args.out or ROOT / f"outputs/FTX-1_DISPLAY_V0110-ft8{kind}-{suffix}.sfl"
    if args.build_dir is None:
        args.build_dir = PATCH / "build" / "radio" if args.radio else PATCH / "build"
    stock = (ROOT / "work/dec/display/display.bin").read_bytes()
    if hashlib.sha256(stock).hexdigest() != STOCK_HASH:
        parser.error("Expected the stock DISPLAY V01-10 payload from the 20260828 JP package")

    args.build_dir.mkdir(parents=True, exist_ok=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.radio:
        build_radio(args, stock, out)
        return
    elf_path = args.build_dir / f"ft8_{kind}.elf"
    bin_path = args.build_dir / f"ft8_{kind}.bin"
    cflags = ["-DFT8_RX_PROBE"] if args.probe else []
    sources = [PAYLOAD / "ft8_menu.c", PAYLOAD / "ft8_touch.S", PAYLOAD / "func_menu_tile.S"]
    capture_hooks = (PROBE_HOOK,) if args.probe else ()
    if live:
        cflags = ["-DFT8_LIVE"]
        if args.grid:
            cflags.append(f'-DFT8_DEFAULT_GRID="{args.grid}"')
        sources.extend((PAYLOAD / "ft8_live.c", PAYLOAD / "ft8_locator.c"))
        capture_hooks = (LIVE_HOOK,)
    run(args.zig, "cc", "-target", "arm-freestanding-eabi", "-mcpu=cortex_a9",
        "-marm", "-Oz", "-g", "-ffreestanding", "-fno-builtin", "-fno-stack-protector",
        "-fno-unwind-tables", "-nostdlib", "-Wall", "-Wextra", "-Werror",
        f"-Wl,-T,{PAYLOAD / 'ft8_menu.ld'}", "-Wl,-e,ft8_ui_worker", "-Wl,--no-undefined",
        "-Wl,--gc-sections",
        *cflags, *sources, "-o", elf_path)
    run(args.zig, "objcopy", "-O", "binary", elf_path, bin_path)

    with elf_path.open("rb") as f:
        elf = ELFFile(f)
        section = elf.get_section_by_name(".payload")
        if section["sh_addr"] != IMAGE_BASE + HOLE_OFFSET or section.data() != bin_path.read_bytes():
            raise ValueError("Unexpected payload layout")
        hooks = branch_hooks(elf, HOOKS + capture_hooks) + label_hooks(elf)

    extra = []
    if args.probe:
        tail = args.build_dir / "ft8_probe_tail.bin"
        tail.write_bytes(bytes(TAIL_OFFSET - len(stock)) + b"FT8P")
        extra = ["--s2", tail]
    elif live:
        run(sys.executable, "-B", PATCH / "build_ft8_rx.py", "--zig", args.zig, "--build-dir", args.build_dir)
        tail = args.build_dir / f"ft8_{kind}_tail.bin"
        decoder = (args.build_dir / "ft8_rx.bin").read_bytes()
        tail.write_bytes(bytes(TAIL_OFFSET - len(stock)) + decoder)
        extra = ["--s2", tail]
    run(sys.executable, "-I", PATCH / "merge_display.py",
        "--payload", f"{bin_path}@{HOLE_OFFSET:#x}", *extra, *hooks, "-o", out)
    if live:
        # merge_display may zero-pad the image tail until the container round-trips;
        # keep the tail file in sync with the produced SFL.
        from test_ft8_menu import read_display_sfl
        image = read_display_sfl(out)
        tail.write_bytes(image[len(stock):])


# Confirmed application copy regions in the stock DISPLAY V01-10 image.
TRACE_REGIONS = (
    ("watchdog", 0x81c9c, 0x820d0), ("release", 0x010ec, 0x011f4),
    ("start", 0x0ff3c, 0x100f8), ("scan", 0x104f8, 0x10734),
    ("log", 0x22320, 0x224e8),
)


def build_radio(args, stock, out):
    build = args.build_dir
    flags = ["--radio", "--vectors"]
    if args.tx_hooks:
        flags.append("--tx-hooks")
    if args.custom_modes:
        flags.append("--custom-modes")
    if args.sd_plugin:
        flags.append("--sd-plugin")
    if args.vfp:
        flags.append("--vfp")
    if args.vfp_only:
        flags.append("--vfp-only")
    if args.cw_debounce:
        flags.append("--cw-debounce")
    if args.profile:
        flags.append("--profile")
    if args.grid:
        flags.extend(("--grid", args.grid))
    run(sys.executable, "-B", PATCH / "build_ft8_rx.py", "--zig", args.zig, "--build-dir", build, *flags)
    patches = HOOKS + (LIVE_HOOK,) + RADIO_HOOKS
    if args.tx_hooks:
        patches += TX_HOOKS
    with (build / "ft8_rx.elf").open("rb") as f:
        elf = ELFFile(f)
        hooks = branch_hooks(elf, patches, vectors=True) + label_hooks(elf)
        if args.profile:
            for name, start, limit in TRACE_REGIONS:
                section = elf.get_section_by_name(f".trace_{name}")
                if section is None or not section["sh_size"]:
                    continue  # A profile without native TX can omit unused TX code.
                data = section.data()
                if section["sh_addr"] != IMAGE_BASE + start or len(data) > limit - start:
                    raise ValueError(f"Invalid FT8 trace section {name}")
                original = stock[start:start + len(data)]
                hooks.extend(("--hook", f"{start:#x}:{original.hex()}:{data.hex()}"))
    hole = build / "ft8_radio.bin"
    tail = build / "ft8_radio_tail.bin"
    tail.write_bytes(bytes(TAIL_OFFSET - len(stock)) + (build / "ft8_rx.bin").read_bytes())
    run(sys.executable, "-I", PATCH / "merge_display.py", "--payload", f"{hole}@{HOLE_OFFSET:#x}",
        "--s2", tail, *hooks, "-o", out)
    from test_ft8_menu import read_display_sfl
    tail.write_bytes(read_display_sfl(out)[len(stock):])


if __name__ == "__main__":
    main()
