"""Boot stall diagnosis."""
import sys
import time
from pathlib import Path

VM_DIR = Path(__file__).resolve().parent
ROOT = VM_DIR.parents[1]
sys.path.insert(0, str(VM_DIR))

from ftx1vm import Board, addrs          # noqa: E402
from unicorn.arm_const import UC_ARM_REG_PC  # noqa: E402


def main():
    image = (ROOT / "work/dec/display/display.bin").read_bytes()
    board = Board(image)
    board.core.uc.reg_write(UC_ARM_REG_PC, addrs.RESET_ENTRY)
    clock = board.core.clock
    t0 = time.time()
    last = 0
    for i in range(4000):
        budget = 50_000
        ok = board.core.run(count=budget)
        clock.advance(budget)
        if not ok:
            print("STOP:", board.core.stop_reason)
            break
        if clock.now_ns - last >= 200_000:      # every 0.2 ms virtual
            last = clock.now_ns
            print(f"{clock.now_ns/1e6:8.3f}ms pc={board.core.uc.reg_read(UC_ARM_REG_PC):#010x}"
                  f" svc={board.core.svc_count} irq={board.core.irq_injected}"
                  f" ticks={board.ostm0.ticks} fired={clock.fired}"
                  f" ocr={board.ostm0.ocr} wall={time.time()-t0:.1f}s", flush=True)
        if board.gic.deliverable():
            board.core.inject_irq()
        if time.time() - t0 > 45:
            print("wall limit")
            break
    print("milestones:", list(board.reached))


if __name__ == "__main__":
    main()
