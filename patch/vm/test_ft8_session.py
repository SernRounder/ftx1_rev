"""Test 2: full-system FT8 session — boot ft8live-LAB, replay a WAV slot
through the patched DMA path, assert decoded messages in the workspace.

Known limitation: the stock UI task stays parked waiting for the MAIN
handshake (real capture of the boot command stream is pending), so the
decoded list is asserted from the stage1 workspace instead of pixels.
"""
import re
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
from test_ft8_menu import read_display_sfl      # noqa: E402

WORK = 0x61100000
DMA_FRAME = 0x61200000
STACK_TOP = 0x61300000
EPOCH_ADDR = 0x6052ED70
HOLE_OFFSET = 0x12C670

# Expected decodes from downloads/210703_133430.wav (matches test_ft8_live).
EXPECTED = {"K1JT HA0DU KN07", "CQ F5RXL IN94", "XE2X HA2NP RR73"}


def main():
    from test_ft8_arm import recording_16k
    image = read_display_sfl(ROOT / "outputs/FTX-1_DISPLAY_V0110-ft8live-LAB.sfl")
    fields = struct.unpack_from("<4s11I", image, HOLE_OFFSET)
    assert fields[0] == b"FT8L", "integrated image lacks the FT8L API"
    bind, next_seq, sync, poll = [v - addrs.IMAGE_BASE for v in fields[4:8]]

    board = Board(image)
    uc = board.core.uc
    board.core.map_ram(WORK, fields[2] + 0x1000, quiet=True)
    board.core.map_ram(DMA_FRAME, 0x1000, quiet=True)
    board.core.map_ram(STACK_TOP - 0x10000, 0x10000, quiet=True)
    uc.reg_write(UC_ARM_REG_PC, addrs.RESET_ENTRY)

    t0 = time.time()
    board.run(300)
    assert "scheduler-start" in board.reached, "boot incomplete"

    assert board.call_debug(bind, WORK, fields[2]) == 1, "bind rejected"
    uc.mem_write(EPOCH_ADDR, struct.pack("<I", 1))
    board.show_mode_debug()
    board.run(50)
    board.call_debug(0x232E0, 1, 0x1133)
    board.call_debug(0x12C670, budget=20_000_000)
    board.run(50)

    samples = recording_16k(ROOT / "downloads/210703_133430.wav")
    seq = board.call_debug(next_seq)
    assert board.call_debug(sync, seq, 0, stack=STACK_TOP) == 1, "sync failed"

    pos = 0
    while pos < len(samples):
        chunk = samples[pos:pos + 1999]
        uc.mem_write(DMA_FRAME, struct.pack("<HH", len(chunk), 0) + chunk.tobytes())
        board.call_debug(0x45170, DMA_FRAME, end=0x45174)
        board.call_debug(poll, stack=STACK_TOP, budget=800_000_000)
        pos += 1999
    board.call_debug(0x12C670, budget=20_000_000)

    work = bytes(uc.mem_read(WORK, 0x2000))
    texts = {t.decode() for t in re.findall(rb"[ -~]{10,}", work)}
    found = EXPECTED & texts
    assert len(found) == len(EXPECTED), f"decodes missing: {EXPECTED - found} (got {sorted(texts)[:8]})"

    out = ROOT / "outputs/ftx1vm"
    out.mkdir(parents=True, exist_ok=True)
    board.screen().save(out / "ft8-session.png")
    print(f"PASS: full-system FT8 session in {time.time()-t0:.1f}s wall — "
          f"decoded {len(found)}/{len(EXPECTED)} expected messages")


if __name__ == "__main__":
    main()
