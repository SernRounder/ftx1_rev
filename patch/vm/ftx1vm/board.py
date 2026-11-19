"""Board: assembles the FTX-1 DISPLAY virtual machine and runs it."""

import struct

from unicorn import UC_HOOK_CODE, UcError
from unicorn.arm_const import UC_ARM_REG_PC, UC_ARM_REG_SP, UC_ARM_REG_LR

from . import addrs
from .core import ArmCore
from .bus import Bus
from .devices.gic import GIC
from .devices.ostm import attach_ostms
from .devices.stubs import attach_stubs
from .devices.scif import attach_scif5
from .main_sim import MainSim


# Boot milestone offsets (file offsets into the image; work/an sources).
MILESTONES = {
    0x2C: "reset",
    0x80: "relocate-cont",
    0x15FC8: "masterinit",
    0x139A4: "rtc-init",
    0x131FC: "scif5-pins+cyclic",
    0x156BC: "scif5-protocol-init",
    0x45314: "audio-init",
    0x15A38: "scheduler-start",
    0x44CDC: "lcd-ui-init",
    0x145F0: "task-uart",
    0x156AC: "task-cmd-interval",
    0x5064: "task-touch",
    0xC9904: "task-uart-rx",
    0x829C: "task-voice",
}


class Board:
    def __init__(self, image, *, log=None, verbose=False, ostm_hz=32_000_000):
        self.log = log or (lambda msg: print(msg, flush=True))
        self.verbose = verbose
        self.core = ArmCore(image, log=(self.log if verbose else (lambda *_: None)))
        self.gic = GIC(log=(self.log if verbose else (lambda *_: None)))
        self.core.gic = self.gic
        self.bus = Bus(self.core, log=(self.log if verbose else (lambda *_: None)))
        self.bus.attach(self.gic)
        self.stubs = attach_stubs(self.bus)
        self.scif5 = attach_scif5(self.bus, self.core.clock, self.gic,
                                  log=(self.log if verbose else (lambda *_: None)))
        self.main = MainSim(self.scif5, self.core.clock,
                            log=(self.log if verbose else (lambda *_: None)))
        self.scif5.peer = self.main
        self.ostm0, self.ostm1 = attach_ostms(self.bus, self.core.clock, self.gic,
                                              log=(self.log if verbose else (lambda *_: None)),
                                              ostm_hz=ostm_hz)
        self.reached = {}
        self._install_milestone_trace()
        self._stop = False
        self.executed_insns = 0

    def _install_milestone_trace(self):
        uc = self.core.uc
        for off, name in MILESTONES.items():
            uc.hook_add(UC_HOOK_CODE, self._make_milestone(off, name),
                        begin=addrs.IMAGE_BASE + off, end=addrs.IMAGE_BASE + off)

    def _make_milestone(self, off, name):
        def hook(_uc, _address, _size, _user):
            if name not in self.reached:
                self.reached[name] = self.core.clock.now_ns
                self.log(f"[boot] {name:24s} @{self.core.clock.now_ns/1e6:10.3f} ms")
        return hook

    # --- main loop -----------------------------------------------------------
    MAX_SLICE = 1_000_000             # insns per emu call when nothing is due

    def run(self, milliseconds=1000, on_slice=None):
        """Advance virtual time by `milliseconds`, servicing events/IRQs.

        Slice model: each emu_start runs at most until the next scheduled
        event (or MAX_SLICE instructions); afterwards we advance the virtual
        clock by the executed count, fire events, and inject a pending IRQ.
        IRQ latency is therefore bounded by the gap to the next event —
        good enough for 1 ms kernel ticks and 29 µs UART bytes.
        """
        clock = self.core.clock
        deadline = clock.now_ns + milliseconds * 1_000_000
        while clock.now_ns < deadline and not self._stop:
            nxt = clock.next_due()
            limit = deadline if nxt is None else min(nxt, deadline)
            budget = min(self.MAX_SLICE, max((limit - clock.now_ns) // clock.ns_per_insn, 1))
            ok = self.core.run(count=int(budget))
            self.executed_insns += budget
            clock.advance(budget)          # slice executed `budget` insns
            if not ok:
                self.log(f"[vm] stopped: {self.core.stop_reason}")
                self._stop = True
                break
            if self.core.sleeping:
                self.core.sleeping = False
                if nxt is None:
                    clock.skip_to(min(clock.now_ns + 1_000_000, deadline))
                elif nxt > clock.now_ns:
                    clock.skip_to(min(nxt, deadline))
            if self.gic.deliverable():
                self.core.inject_irq()
            if on_slice:
                on_slice(self)

    def stop(self):
        self._stop = True

    # --- observation -----------------------------------------------------------
    CALL_SENTINEL = 0x61000000

    def call_debug(self, offset, *args, budget=5_000_000, stack=None, end=None):
        """Debug backdoor: borrow the current guest context to call a stock
        function at IMAGE_BASE+offset (args in r0-r3), restoring everything
        afterwards.  Uses a sentinel page as return address.  `stack` gives
        the call a fresh SP (VM-provided page) for deep callees like the FFT.
        `end` stops at a custom return address (relative offset), for calls
        into the middle of a stock function (e.g. the DMA completion BL)."""
        from unicorn import arm_const
        uc = self.core.uc
        self.core.map_ram(self.CALL_SENTINEL, 0x1000, quiet=True)
        stop = addrs.IMAGE_BASE + end if end is not None else self.CALL_SENTINEL
        gp = [getattr(arm_const, f"UC_ARM_REG_R{i}") for i in range(13)]
        saved = [uc.reg_read(r) for r in gp]
        saved_cpsr = uc.reg_read(arm_const.UC_ARM_REG_CPSR)
        saved_sp = uc.reg_read(arm_const.UC_ARM_REG_SP)
        saved_lr = uc.reg_read(UC_ARM_REG_LR)
        saved_pc = uc.reg_read(UC_ARM_REG_PC)
        for reg, arg in zip(gp[:4], (*args, 0, 0, 0)):
            uc.reg_write(reg, arg & 0xFFFFFFFF)
        if stack is not None:
            uc.reg_write(arm_const.UC_ARM_REG_SP, stack)
        uc.reg_write(UC_ARM_REG_LR, self.CALL_SENTINEL)
        result = None
        try:
            uc.emu_start(addrs.IMAGE_BASE + offset, stop, count=budget)
            result = uc.reg_read(gp[0])
        finally:
            for reg, value in zip(gp, saved):
                uc.reg_write(reg, value)
            uc.reg_write(arm_const.UC_ARM_REG_SP, saved_sp)
            uc.reg_write(UC_ARM_REG_LR, saved_lr)
            uc.reg_write(UC_ARM_REG_PC, saved_pc)
            uc.reg_write(arm_const.UC_ARM_REG_CPSR, saved_cpsr)
        return result

    def screen(self):
        from PIL import Image
        pixels = bytes(self.core.uc.mem_read(addrs.FRAMEBUFFER, 800 * 480 * 2))
        return Image.frombytes("RGB", (800, 480), pixels, "raw", "BGR;16")

    def tap_debug(self, x, y):
        """Touch injection through the stock coordinate dispatch chain
        (proven sequence from preview_ft8.Panel.tap)."""
        self.call_debug(0x41D4, x, y)
        self.call_debug(0x23498, 0)
        self.call_debug(0x23498, 0)
        self.call_debug(0x41F8)
        self.call_debug(0x23498, 0)

    def show_mode_debug(self):
        """Open the MODE popup the way preview_ft8.Panel.show_mode does."""
        uc = self.core.uc
        uc.mem_write(addrs.UI_STATE, b"\x30")
        uc.mem_write(addrs.UI_STATE + 0x13B, b"\x05\x01")
        self.call_debug(0x3C51C, addrs.UI_STATE, 1)

    def regs(self):
        uc = self.core.uc
        return {"pc": uc.reg_read(UC_ARM_REG_PC), "sp": uc.reg_read(UC_ARM_REG_SP)}

    def read_mem(self, address, size):
        return bytes(self.core.uc.mem_read(address, size))

    def irq_stats(self):
        return {"injected": self.core.irq_injected,
                "svc": self.core.svc_count,
                "undef": self.core.undef_count,
                "iar": self.gic.iar_reads,
                "ostm0_ticks": self.ostm0.ticks,
                "clock_ms": self.core.clock.now_ns / 1e6}
