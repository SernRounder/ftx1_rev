"""Boot experiment: stock display.bin from the reset vector.

Usage: python run_boot.py [ms] [verbose]
"""

import sys
import time
from pathlib import Path

from unicorn.arm_const import UC_ARM_REG_PC

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from ftx1vm import Board
from ftx1vm import addrs

ROOT = Path(__file__).resolve().parents[2]


def main():
    ms = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    verbose = len(sys.argv) > 2 and sys.argv[2] == "verbose"
    image = (ROOT / "work/dec/display/display.bin").read_bytes()
    board = Board(image, verbose=verbose)
    # Start at the reset vector: firmware does its own stack/MMU/scatter-load.
    board.core.uc.reg_write(UC_ARM_REG_PC, addrs.RESET_ENTRY)
    t0 = time.time()
    board.run(ms)
    wall = time.time() - t0
    print(f"\n--- wall {wall:.1f}s for {ms} ms virtual ---")
    print("milestones:", " ".join(board.reached) or "(none)")
    stats = board.irq_stats()
    print("stats:", stats)
    print("invalid insns:", {hex(k): v for k, v in board.core.invalid_insns.items()})
    print("unmapped reads:", {hex(k): v for k, v in board.bus.unmapped_reads.items()})
    print("unmapped writes:", {hex(k): v for k, v in board.bus.unmapped_writes.items()})
    print("regs:", board.regs())


if __name__ == "__main__":
    main()
