"""Boot the ft8menu image in the full-system VM, inject the MODE key,
watch the FT8 menu render, save a screenshot."""
import sys
import time
from pathlib import Path

VM_DIR = Path(__file__).resolve().parent
ROOT = VM_DIR.parents[1]
sys.path.insert(0, str(VM_DIR))
sys.path.insert(0, str(VM_DIR.parent))

from unicorn import UC_HOOK_CODE                      # noqa: E402
from unicorn.arm_const import UC_ARM_REG_PC           # noqa: E402
from ftx1vm import Board, addrs                       # noqa: E402
from test_ft8_menu import read_display_sfl            # noqa: E402


def main():
    sfl = ROOT / "outputs/FTX-1_DISPLAY_V0110-ft8menu-TEST.sfl"
    image = read_display_sfl(sfl)
    board = Board(image)
    uc = board.core.uc
    uc.reg_write(UC_ARM_REG_PC, addrs.RESET_ENTRY)
    t0 = time.time()
    board.run(300)
    print(f"boot 300ms wall={time.time()-t0:.1f}s ticks={board.ostm0.ticks} svc={board.core.svc_count}")
    print("milestones:", list(board.reached))

    counts = {}
    for off, name in ((0x23D64, "draw_text"), (0x625A0, "fill"), (0x62818, "bitmap"),
                      (0x3BD3C, "popup"), (0x3C51C, "ft8_mode_draw"), (0x448B8, "get_frame")):
        def mk(nm):
            def h(u, a, s, ud):
                counts[nm] = counts.get(nm, 0) + 1
            return h
        uc.hook_add(UC_HOOK_CODE, mk(name), begin=addrs.IMAGE_BASE + off, end=addrs.IMAGE_BASE + off)

    # MODE key press: stock event path FUN_000232E0(down, event=0x1133)
    board.call_debug(0x232E0, 1, 0x1133)
    board.run(100)
    board.call_debug(0x232E0, 0, 0x1133)      # release
    board.run(100)
    print("after MODE key event:", counts)
    if not counts.get("ft8_mode_draw"):
        # fall back to the preview-harness-proven direct draw: set UI page 0x30
        # (MODE popup page) and call the hooked entry 0x3C51C(UI, 1)
        UI = 0x60935BB4
        uc.mem_write(UI, b"\x30")
        uc.mem_write(UI + 0x13B, b"\x05\x01")     # popup=5, selection=1
        board.call_debug(0x3C51C, UI, 1)
        board.run(150)
        print("after direct mode draw:", counts)
    out = ROOT / "outputs/ftx1vm"
    out.mkdir(parents=True, exist_ok=True)
    board.screen().save(out / "mode-menu.png")
    pixels = bytes(uc.mem_read(addrs.FRAMEBUFFER, 800 * 480 * 2))
    print("framebuffer nonzero:", sum(1 for b in pixels if b))


if __name__ == "__main__":
    main()
