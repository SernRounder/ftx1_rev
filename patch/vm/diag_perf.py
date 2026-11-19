"""Per-ms performance/profile of the boot."""
import sys
import time
from pathlib import Path

VM_DIR = Path(__file__).resolve().parent
ROOT = VM_DIR.parents[1]
sys.path.insert(0, str(VM_DIR))

from unicorn.arm_const import UC_ARM_REG_PC   # noqa: E402
from ftx1vm import Board, addrs               # noqa: E402


def main():
    ms = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    image = (ROOT / "work/dec/display/display.bin").read_bytes()
    board = Board(image)
    uc = board.core.uc
    uc.reg_write(UC_ARM_REG_PC, addrs.RESET_ENTRY)
    clock = board.core.clock
    t0 = time.time()
    last_ns, last_fired = 0, 0
    while clock.now_ns < ms * 1_000_000 and time.time() - t0 < 100:
        board.run(1)
        now = time.time()
        print(f"vt={clock.now_ns/1e6:7.2f}ms wall={now-t0:6.2f}s pc={uc.reg_read(UC_ARM_REG_PC):#010x} "
              f"svc={board.core.svc_count} irq={board.core.irq_injected} fired={clock.fired-last_fired} "
              f"evq={len(clock._events)} ticks0={board.ostm0.ticks} ocr0={board.ostm0.ocr:#x} "
              f"ticks1={board.ostm1.ticks} ocr1={board.ostm1.ocr:#x}", flush=True)
        last_fired = clock.fired
    print("milestones:", list(board.reached))
    print("invalid:", {hex(k): v for k, v in board.core.invalid_insns.items()})


if __name__ == "__main__":
    main()
