"""Test 1: stock display.bin boots to the scheduler in the full-system VM."""
import sys
import time
from pathlib import Path

VM_DIR = Path(__file__).resolve().parent
ROOT = VM_DIR.parents[1]
sys.path.insert(0, str(VM_DIR))
sys.path.insert(0, str(VM_DIR.parent))

from unicorn.arm_const import UC_ARM_REG_PC     # noqa: E402
from ftx1vm import Board, addrs                 # noqa: E402

REQUIRED_MILESTONES = {
    "reset", "masterinit", "rtc-init", "scif5-pins+cyclic", "scif5-protocol-init",
    "task-uart", "task-uart-rx", "audio-init", "scheduler-start", "task-voice",
    "lcd-ui-init",
}


def main():
    image = (ROOT / "work/dec/display/display.bin").read_bytes()
    board = Board(image)
    board.core.uc.reg_write(UC_ARM_REG_PC, addrs.RESET_ENTRY)
    t0 = time.time()
    board.run(300)
    wall = time.time() - t0

    missing = REQUIRED_MILESTONES - set(board.reached)
    assert not missing, f"boot milestones missing: {sorted(missing)}"
    stats = board.irq_stats()
    assert stats["ostm0_ticks"] >= 25, f"kernel ticks too few: {stats}"
    assert stats["svc"] > 1000, f"syscalls too few: {stats}"
    assert stats["iar"], "no interrupts delivered through the GIC"
    assert board.main.replies, "MainSim never pushed a datetime frame"
    print(f"PASS: stock boot in {wall:.1f}s wall — {stats['ostm0_ticks']} ticks, "
          f"{stats['svc']} syscalls, IAR={stats['iar']}")


if __name__ == "__main__":
    main()
