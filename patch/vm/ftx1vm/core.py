"""ArmCore: unicorn ARM core + hardware-style exception injection.

Full-system semantics implemented here (validated by patch/vm/probe_unicorn*.py):

* SVC exceptions (µITRON syscalls, ``svc #0`` wrappers) arrive through
  UC_HOOK_INTR; we emulate exception entry into the SVC vector exactly as
  the Cortex-A9 would (banked SPSR/LR/SP, mode switch), and the firmware's
  dispatcher at 0x60400160 does the rest.
* IRQs: pended through the GIC model; the board's slice loop checks
  deliverability between emu slices and injects the IRQ entry
  (vector 0x18 -> 0x604001A4) with banked mode switch.  No per-block hook —
  throughput matters (a global block hook costs ~50x).
* WFI is not decoded by this unicorn build -> UC_HOOK_INSN_INVALID skips it
  and flags the core as sleeping so the main loop can fast-forward virtual
  time to the next event.
* Virtual time advances per slice (executed instruction count) at cpu_hz.
"""

import struct

from unicorn import (
    Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_INTR,
    UC_HOOK_INSN_INVALID, UcError,
)
from unicorn.arm_const import (
    UC_ARM_REG_CPSR, UC_ARM_REG_PC, UC_ARM_REG_LR, UC_ARM_REG_SP,
    UC_ARM_REG_SPSR, UC_ARM_REG_R0, UC_ARM_REG_C1_C0_2, UC_ARM_REG_FPEXC,
)

from . import addrs
from .clock import VirtualClock

WFI_WORDS = {0xF57FF207}          # wfi (probe_unicorn.py: invalid in this build)


class ArmCore:
    def __init__(self, image, *, cpu_hz=400_000_000, log=None, trace=None):
        # 400 MHz is the RZ/A1H ceiling; conditional clock per ftx1-firmware#119 is 384/64/32 MHz.
        self.image = image
        self.log = log or (lambda *_: None)
        self.trace = trace or (lambda *_: None)
        self.clock = VirtualClock(cpu_hz)
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)

        # VFPv3: hard-float FT8 decoder needs CP10/11 + FPEXC.EN
        self.uc.reg_write(UC_ARM_REG_C1_C0_2, 0x00F00000)
        self.uc.reg_write(UC_ARM_REG_FPEXC, 0x40000000)

        self._mapped = []
        self.map_ram(addrs.SRAM_BASE, addrs.SRAM_SIZE, quiet=True)
        self.uc.mem_write(addrs.IMAGE_BASE, image)

        self.gic = None                # set by board
        self.irq_injected = 0
        self.svc_count = 0
        self.undef_count = 0
        self.sleeping = False
        self.stop_reason = None
        self.invalid_insns = {}
        self.invalid_sites = {}         # word -> first pc
        self.PYLIB = {0xBDD64: self._py_memset}
        for off in (0x20820, 0x20834, 0x20848, 0x2085C, 0x20870):
            self.PYLIB[off] = self._py_wait_ready
        self.PYLIB[0x20940] = self._set_ctx_flag2      # wait [r0+2] loops
        self.PYLIB[0x20970] = self._set_ctx_flag3      # wait [r0+3] loops

        uc = self.uc
        uc.hook_add(UC_HOOK_INTR, self._on_intr)
        self._h_invalid = uc.hook_add(UC_HOOK_INSN_INVALID, self._on_invalid_insn)
        # Full set/way cache maintenance loop (stock 0x3058) burns ~1M guest
        # instructions for hardware the TCG core does not model — skip it.
        uc.hook_add(UC_HOOK_CODE, self._skip_stock, begin=addrs.IMAGE_BASE + 0x3058,
                    end=addrs.IMAGE_BASE + 0x3058)
        # unicorn 2.1.x mis-translates Thumb IT blocks that contain 32-bit
        # conditional instructions (ITTT HS + stmhs.w + bhs.w in the stock
        # __aeabi_memset at 0xBDD64 mis-decodes as BL/invalid).  Replace the
        # affected compiler intrinsics with Python equivalents.
        for off, handler in self.PYLIB.items():
            uc.hook_add(UC_HOOK_CODE, handler, begin=addrs.IMAGE_BASE + off,
                        end=addrs.IMAGE_BASE + off)

    # stock offsets -> Python reimplementation (self-bound in __init__)
    PYLIB = {}

    def _skip_stock(self, cpu, _address, _size, _user):
        from unicorn.arm_const import UC_ARM_REG_LR
        cpu.reg_write(UC_ARM_REG_PC, cpu.reg_read(UC_ARM_REG_LR))

    def _py_memset(self, cpu, _address, _size, _user):
        """__aeabi_memset(r0=dest, r1=n, r2=byte) at stock 0xBDD64."""
        from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_LR, UC_ARM_REG_PC
        dest, count, value = (cpu.reg_read(r) for r in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2))
        if count:
            cpu.mem_write(dest, bytes((value & 0xFF,)) * count)
        cpu.reg_write(UC_ARM_REG_PC, cpu.reg_read(UC_ARM_REG_LR))

    # polled completion byte for each stock wait stub (QSPI/SPI channels the
    # VM does not model — treated as always complete)
    WAIT_FLAG = {0x20820: 0x607C0653, 0x20834: 0x607C0654, 0x20848: 0x607C0655,
                 0x2085C: 0x607C0656, 0x20870: 0x607C065B}

    def _py_wait_ready(self, cpu, address, _size, _user):
        from unicorn.arm_const import UC_ARM_REG_LR, UC_ARM_REG_PC
        cpu.mem_write(self.WAIT_FLAG[address - addrs.IMAGE_BASE], b"\x01")
        cpu.reg_write(UC_ARM_REG_PC, cpu.reg_read(UC_ARM_REG_LR))

    def _set_ctx_flag2(self, cpu, _address, _size, _user):
        """0x20940: `ldrb r1,[r0,#2]; cmp; beq` — mark ctx+2 complete."""
        from unicorn.arm_const import UC_ARM_REG_R0
        cpu.mem_write(cpu.reg_read(UC_ARM_REG_R0) + 2, b"\x01")

    def _set_ctx_flag3(self, cpu, _address, _size, _user):
        """0x20970: same for ctx+3."""
        from unicorn.arm_const import UC_ARM_REG_R0
        cpu.mem_write(cpu.reg_read(UC_ARM_REG_R0) + 3, b"\x01")

    # --- memory -----------------------------------------------------------
    def map_ram(self, base, size, quiet=False):
        base &= ~0xFFF
        size = (size + 0xFFF) & ~0xFFF
        for mbase, msize in self._mapped:
            if mbase <= base < mbase + msize or base <= mbase < base + size:
                return                  # already covered
        self.uc.mem_map(base, size)
        self._mapped.append((base, size))
        if not quiet:
            self.log(f"[mem] mapped {base:#010x}+{size:#x}")

    # --- register helpers ---------------------------------------------------
    @staticmethod
    def cpsr(uc):
        return uc.reg_read(UC_ARM_REG_CPSR)

    def mode(self):
        return self.cpsr(self.uc) & 0x1F

    def interrupts_enabled(self):
        return not (self.cpsr(self.uc) & addrs.CPSR_I)

    def _exception_enter(self, mode, vector, lr, set_i=True, set_f=False):
        uc = self.uc
        cur = self.cpsr(uc)
        new = (cur & ~(0x1F | addrs.CPSR_T)) | mode
        if set_i:
            new |= addrs.CPSR_I
        if set_f:
            new |= addrs.CPSR_F
        uc.reg_write(UC_ARM_REG_CPSR, new)
        uc.reg_write(UC_ARM_REG_SPSR, cur)
        uc.reg_write(UC_ARM_REG_LR, lr)
        uc.reg_write(UC_ARM_REG_PC, vector)

    def inject_irq(self):
        """Hardware-style IRQ entry (called between slices by the board)."""
        uc = self.uc
        cpsr = self.cpsr(uc)
        if cpsr & addrs.CPSR_I:
            return False
        if (cpsr & 0x1F) in (addrs.ARM_IRQ, addrs.ARM_FIQ, addrs.ARM_ABT, addrs.ARM_UND):
            return False                # inside a handler; it will re-enable
        self.irq_injected += 1
        pc = uc.reg_read(UC_ARM_REG_PC)
        # Hardware IRQ entry: LR_irq = next+4; stock entry stub does sub lr,#4
        self._exception_enter(addrs.ARM_IRQ, addrs.IRQ_ENTRY, pc + 4, set_i=True)
        return True

    # --- hooks --------------------------------------------------------------
    def _on_intr(self, uc, intno, _user):
        # SVC (software interrupt) -> vector 0x08 with SVC-mode banks.
        pc = uc.reg_read(UC_ARM_REG_PC)
        if self.cpsr(uc) & addrs.CPSR_T:
            insn = struct.unpack("<H", bytes(uc.mem_read(pc - 2, 2)))[0]
            is_svc = insn & 0xFF00 == 0xDF00
        else:
            insn = struct.unpack("<I", bytes(uc.mem_read(pc - 4, 4)))[0]
            is_svc = insn & 0x0F000000 == 0x0F000000
        if intno == 2 and is_svc:
            self.svc_count += 1
            self._exception_enter(addrs.ARM_SVC, addrs.SVC_VECTOR, pc, set_i=False)
            return
        self.log(f"[core] unexpected UC_HOOK_INTR intno={intno} pc={pc:#x}")

    def _on_invalid_insn(self, uc, _user):
        pc = uc.reg_read(UC_ARM_REG_PC)
        try:
            word = struct.unpack("<I", bytes(uc.mem_read(pc, 4)))[0]
        except UcError:
            word = 0
        if word in WFI_WORDS:
            self.sleeping = True
            return True                 # skip; main loop fast-forwards time
        n = self.invalid_insns.get(word, 0) + 1
        self.invalid_insns[word] = n
        self.invalid_sites.setdefault(word, pc)
        if n <= 5:
            self.log(f"[core] invalid insn {word:#010x} @ {pc:#010x} — skipping")
        return True

    # --- execution ----------------------------------------------------------
    def run(self, count=2_000_000):
        """Execute one slice; returns False when the CPU should be slept."""
        self.sleeping = False
        self.stop_reason = None
        pc = self.uc.reg_read(UC_ARM_REG_PC)
        if self.cpsr(self.uc) & addrs.CPSR_T:
            pc |= 1
        try:
            self.uc.emu_start(pc, 0, count=count)
        except UcError as exc:
            self.stop_reason = f"{exc} @ pc={self.uc.reg_read(UC_ARM_REG_PC):#x}"
            return False
        return True
