"""Full-system FT8 session: boot ft8live-LAB, enter the FT8 RX page, replay
a WAV through the patched DMA completion path, decode on-screen.

This mirrors preview_ft8.LivePanel but everything — boot, µITRON scheduling,
UI workers, font rendering — runs as real firmware inside the VM.
"""
import struct
import sys
import time
from pathlib import Path

VM_DIR = Path(__file__).resolve().parent
ROOT = VM_DIR.parents[1]
sys.path.insert(0, str(VM_DIR))
sys.path.insert(0, str(VM_DIR.parent))

from unicorn import UC_HOOK_CODE                       # noqa: E402
from unicorn.arm_const import UC_ARM_REG_PC            # noqa: E402
from ftx1vm import Board, addrs                        # noqa: E402
from test_ft8_menu import read_display_sfl             # noqa: E402
from test_ft8_arm import recording_16k                 # noqa: E402

IMAGE_BASE = addrs.IMAGE_BASE
HOLE_OFFSET = 0x12C670
UI = 0x60935BB4
WORK = 0x61100000
DMA_FRAME = 0x61200000
STACK_TOP = 0x61300000                 # 64 KiB worker stack for poll/sync


def parse_live_api(image):
    fields = struct.unpack_from("<4s11I", image, HOLE_OFFSET)
    magic, version, work, stack = fields[:4]
    if magic != b"FT8L":
        raise ValueError(f"no FT8L API in image (magic={magic!r})")
    return {"version": version, "work": work, "stack": stack,
            "entries": [v - IMAGE_BASE for v in fields[4:]]}


def main():
    wav = ROOT / "downloads/210703_133430.wav"
    image = read_display_sfl(ROOT / "outputs/FTX-1_DISPLAY_V0110-ft8live-LAB.sfl")
    api = parse_live_api(image)
    bind, next_sequence, sync, poll = api["entries"][:4]
    print(f"FT8L v{api['version']} work={api['work']:#x} stack={api['stack']:#x}")

    board = Board(image)
    uc = board.core.uc
    board.core.map_ram(WORK, api["work"] + 0x1000, quiet=True)
    board.core.map_ram(DMA_FRAME, 0x1000, quiet=True)
    board.core.map_ram(STACK_TOP - 0x10000, 0x10000, quiet=True)
    uc.reg_write(UC_ARM_REG_PC, addrs.RESET_ENTRY)

    t0 = time.time()
    board.run(300)
    print(f"boot 300ms wall={time.time()-t0:.1f}s svc={board.core.svc_count}")

    # bind the RX workspace (returns 1 on success — payload ft8_live.c)
    assert board.call_debug(bind, WORK, api["work"]) == 1, "bind rejected"
    # stage1 epoch (0x6052ED70) gates sync/poll; set_active(1) equivalent.
    # (Normally ft8_ui_worker sets it; the stock UI task is parked waiting
    # for the MAIN handshake in this VM, so we drive it directly.)
    uc.mem_write(0x6052ED70, struct.pack("<I", 1))

    # enter the MODE popup, request the FT8 page (OPEN event through the
    # patched touch entry), and drive the patched worker once: stage1 then
    # activates the RX session itself (ft8_live_set_active).
    board.show_mode_debug()
    board.run(50)
    board.call_debug(0x232E0, 1, 0x1133)        # press MODE key (OPEN)
    board.call_debug(0x12C670, budget=20_000_000)   # worker consumes it
    board.run(50)
    print("after FT8 request — screen saved")
    out = ROOT / "outputs/ftx1vm"
    out.mkdir(parents=True, exist_ok=True)
    board.screen().save(out / "ft8-rx-enter.png")

    samples = recording_16k(wav)
    seq = board.call_debug(next_sequence)
    assert board.call_debug(sync, seq, 0, stack=STACK_TOP) == 1, "sync failed"
    print(f"slot synced at frame {seq}")

    t0 = time.time()
    pos = 0
    frames = 0
    while pos < len(samples):
        chunk = samples[pos:pos + 1999]
        frame = struct.pack("<HH", len(chunk), 0) + chunk.tobytes()
        uc.mem_write(DMA_FRAME, frame)
        # deliver via the patched stock DMA completion BL, stopping right
        # after it (0x45174) like preview_ft8 does
        board.call_debug(0x45170, DMA_FRAME, end=0x45174)
        # worker poll on the VM-provided 64 KiB stack (same as LivePanel)
        board.call_debug(poll, stack=STACK_TOP, budget=50_000_000)
        pos += 1999
        frames += 1
        if frames % 10 == 0:
            board.call_debug(0x12C670, budget=20_000_000)   # worker refresh
            board.run(10)
    board.run(100)
    print(f"replayed {frames} frames, wall={time.time()-t0:.1f}s")
    board.screen().save(out / "ft8-decoded.png")
    nz = sum(1 for b in bytes(uc.mem_read(addrs.FRAMEBUFFER, 800*480*2)) if b)
    print("framebuffer nonzero:", nz)


if __name__ == "__main__":
    main()
