"""FTX-1 DISPLAY full-system VM CLI.

Usage:
  python run_vm.py --boot-ms 500                      # stock boot + stats
  python run_vm.py --sfl <ft8live.sfl> --wav <15s.wav> --screenshots out/
  python run_vm.py --sfl <ft8menu.sfl> --show-mode --screenshots out/
"""
import argparse
import struct
import sys
import time
from pathlib import Path

VM_DIR = Path(__file__).resolve().parent
ROOT = VM_DIR.parents[1]
sys.path.insert(0, str(VM_DIR))
sys.path.insert(0, str(VM_DIR.parent))

from unicorn.arm_const import UC_ARM_REG_PC     # noqa: E402
from ftx1vm import Board, addrs                 # noqa: E402

WORK = 0x61100000
DMA_FRAME = 0x61200000
STACK_TOP = 0x61300000
EPOCH_ADDR = 0x6052ED70         # stage1 session epoch (ft8_live.c)
HOLE_OFFSET = 0x12C670


def load_image(args):
    if args.sfl:
        from test_ft8_menu import read_display_sfl
        return read_display_sfl(Path(args.sfl))
    return (Path(args.image) if args.image else ROOT / "work/dec/display/display.bin").read_bytes()


def ft8_session(board, wav_path, api):
    uc = board.core.uc
    bind, next_seq, sync, poll = api["entries"][:4]
    board.core.map_ram(WORK, api["work"] + 0x1000, quiet=True)
    board.core.map_ram(DMA_FRAME, 0x1000, quiet=True)
    board.core.map_ram(STACK_TOP - 0x10000, 0x10000, quiet=True)
    from test_ft8_arm import recording_16k
    samples = recording_16k(Path(wav_path))

    assert board.call_debug(bind, WORK, api["work"]) == 1, "bind rejected"
    uc.mem_write(EPOCH_ADDR, struct.pack("<I", 1))     # set_active(1)
    board.show_mode_debug()
    board.run(50)
    board.call_debug(0x232E0, 1, 0x1133)               # MODE key (OPEN)
    board.call_debug(0x12C670, budget=20_000_000)      # worker consumes
    board.run(50)

    seq = board.call_debug(next_seq)
    assert board.call_debug(sync, seq, 0, stack=STACK_TOP) == 1, "sync failed"
    pos, frames = 0, 0
    while pos < len(samples):
        chunk = samples[pos:pos + 1999]
        uc.mem_write(DMA_FRAME, struct.pack("<HH", len(chunk), 0) + chunk.tobytes())
        board.call_debug(0x45170, DMA_FRAME, end=0x45174)
        board.call_debug(poll, stack=STACK_TOP, budget=800_000_000)
        pos += 1999
        frames += 1
        if frames % 10 == 0:
            board.call_debug(0x12C670, budget=20_000_000)
            board.run(10)
    board.call_debug(0x12C670, budget=20_000_000)
    board.run(50)
    return frames


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", help="raw display.bin path")
    parser.add_argument("--sfl", help="SFL image (extracted automatically)")
    parser.add_argument("--boot-ms", type=int, default=300)
    parser.add_argument("--wav", help="15-second slot WAV for the FT8 session")
    parser.add_argument("--show-mode", action="store_true", help="open the MODE popup and screenshot")
    parser.add_argument("--screenshots", type=Path, help="output directory for PNGs")
    args = parser.parse_args()

    image = load_image(args)
    board = Board(image)
    uc = board.core.uc
    uc.reg_write(UC_ARM_REG_PC, addrs.RESET_ENTRY)

    t0 = time.time()
    board.run(args.boot_ms)
    print(f"boot {args.boot_ms} ms virtual in {time.time()-t0:.1f}s wall")
    print("milestones:", list(board.reached))
    print("stats:", board.irq_stats())

    out = args.screenshots
    if out:
        out.mkdir(parents=True, exist_ok=True)
    api = None
    if len(image) > HOLE_OFFSET + 4 and image[HOLE_OFFSET:HOLE_OFFSET+4] == b"FT8L":
        fields = struct.unpack_from("<4s11I", image, HOLE_OFFSET)
        api = {"work": fields[2], "entries": [v - addrs.IMAGE_BASE for v in fields[4:]]}
        print(f"FT8L v{fields[1]} detected (work={fields[2]:#x})")

    if args.show_mode:
        board.show_mode_debug()
        board.run(80)
    if args.wav:
        if not api:
            parser.error("--wav needs an integrated (ft8live) image")
        frames = ft8_session(board, args.wav, api)
        print(f"replayed {frames} frames")
    if out:
        board.screen().save(out / "screen.png")
        print("saved", out / "screen.png")


if __name__ == "__main__":
    main()
