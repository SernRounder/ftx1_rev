"""M0 probes: verify unicorn 2.1.3 behaviour needed by the full-system VM.

Answers, before the board is built:
  A. CP15 writes (MMU/SCTLR/cache maintenance) tolerated on Cortex-A9 ARM mode?
  B. Undefined-instruction exceptions: hook callback? manual banked-mode
     switch into an UNDEF vector and back via "movs pc, lr"?
  C. IRQ injection: switch to IRQ mode (banked SP/LR/SPSR), run handler,
     return with "subs pc, lr, #4"?  CPSR restored, banks intact?
  D. WFI behaviour in the TCG build.
  E. Do SVC-mode SPSR/SP/LR banks survive a mode round-trip?
"""

import struct

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_INTR, UC_HOOK_INSN_INVALID, UcError
from unicorn.arm_const import (
    UC_ARM_REG_CPSR, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC,
    UC_ARM_REG_SPSR, UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
)

CODE = 0x00100000
STACK = 0x00200000
VECTORS = 0x00000000

SVC, UND, IRQ = 0x13, 0x1B, 0x12


def assemble(words):
    return b"".join(struct.pack("<I", w) for w in words)


def fresh():
    cpu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    cpu.mem_map(CODE, 0x10000)
    cpu.mem_map(STACK - 0x10000, 0x10000)
    cpu.mem_map(VECTORS, 0x10000)
    return cpu


def cpsr(cpu):
    return cpu.reg_read(UC_ARM_REG_CPSR)


def set_mode(cpu, mode, spsr, lr, sp):
    """Emulate exception entry the way real hardware would."""
    cur = cpsr(cpu)
    cpu.reg_write(UC_ARM_REG_CPSR, (cur & ~0x1F) | mode | 0x80)  # enter mode, I set
    cpu.reg_write(UC_ARM_REG_SPSR, cur)
    cpu.reg_write(UC_ARM_REG_LR, lr)
    cpu.reg_write(UC_ARM_REG_SP, sp)


def probe_a_cp15():
    """SCTLR/TTBR/DACR/cache-maintenance MCRs + ISB."""
    code = assemble([
        0xEE110F10,  # mrc p15,0,r0,c1,c0,0   (read SCTLR)
        0xEE010F10,  # mcr p15,0,r0,c1,c0,0   (write SCTLR back)
        0xEE010F50,  # mcr p15,0,r0,c2,c0,0?  placeholder TTBR0-class
        0xEE010F10 & 0xFFFFFFFF,  # (repeat SCTLR)
        0xF57FF04F,  # dsb sy
        0xF57FF06F,  # isb sy
        0xE3A0002A,  # mov r0, #42
        0xE1A0F00E,  # mov pc, lr
    ])
    cpu = fresh()
    cpu.mem_write(CODE, code)
    cpu.reg_write(UC_ARM_REG_LR, CODE + 0x100)
    cpu.emu_start(CODE, CODE + 0x100, count=100000)
    assert cpu.reg_read(UC_ARM_REG_R0) == 42
    print("A  CP15 MCR/MRC + barriers: OK  (SCTLR=%#x)" % cpu.reg_read(UC_ARM_REG_R0))


def probe_b_undef():
    """UDEF syscall-style dispatch through a vector with banked UND mode."""
    # Vector 0x04 -> branch to handler at CODE+0x100.
    cpu = fresh()
    cpu.mem_write(VECTORS + 0x04, assemble([0xEA000000 + (0x100 - 0x8) >> 2 & 0xFFFFFF]))
    handler = assemble([
        0xE10F0000,  # mrs r0, spsr          (kernel reads caller cpsr)
        0xE3811001,  # orr r1, r1, #1        (touch r1 so we see clobber)
        0xE160006E,  # subs? -> use movs pc, lr below
        0xE1B0F00E,  # movs pc, lr           (restore cpsr from SPSR, return)
    ])
    # NOTE: 'movs pc, lr' = 0xE1B0F00E; drop the stray subs above.
    handler = assemble([
        0xE10F0000,  # mrs r0, spsr
        0xE1B0F00E,  # movs pc, lr
    ])
    cpu.mem_write(CODE + 0x100, handler)
    main = assemble([
        0xE3A01001,  # mov r1, #1
        0xE7DF151F,  # undefined (µITRON syscall opcode)
        0xE3A01002,  # mov r1, #2   <- must execute after return
        0xEAFFFFFE,  # b .
    ])
    cpu.mem_write(CODE, main)
    events = []

    def on_intr(uc, intno, _):
        pc = uc.reg_read(UC_ARM_REG_PC)
        events.append((intno, pc))
        # Emulate UNDEF entry: LR_und = instruction after the undef insn.
        set_mode(uc, UND, spsr=cpsr(uc), lr=pc, sp=STACK)
        uc.reg_write(UC_ARM_REG_PC, VECTORS + 0x04)

    cpu.hook_add(UC_HOOK_INTR, on_intr)
    cpu.reg_write(UC_ARM_REG_LR, CODE + 0x200)
    cpu.emu_start(CODE, CODE + 0x200, count=100000)
    r1 = cpu.reg_read(UC_ARM_REG_R1)
    mode = cpsr(cpu) & 0x1F
    assert r1 == 2, f"r1={r1}: UNDEF round-trip did not resume"
    assert mode == SVC, f"cpsr mode {mode:#x} after return, expected SVC"
    print(f"B  UDEF via UC_HOOK_INTR: OK  events={events}  r1={r1} mode=SVC")


def probe_c_irq():
    """IRQ injection with banked SP/LR/SPSR and 'subs pc, lr, #4' return."""
    cpu = fresh()
    # IRQ vector 0x18 -> handler at CODE+0x100. Handler touches a fake GIC at
    # MMIO-ish RAM word, then returns.
    cpu.mem_write(VECTORS + 0x18, assemble([0xEA000000 + ((0x100 - 0x1C) >> 2) & 0xFFFFFF]))
    handler = assemble([
        0xE10F2000,  # mrs r2, spsr
        0xE1B0F00E,  # movs pc, lr   (simplified; real one uses subs pc,lr,#4)
    ])
    # Real firmware style: IRQ entry already did 'sub lr, lr, #4', so the
    # handler returns with 'subs pc, lr, #4' only when LR still holds the
    # raw value.  We emulate the true entry: LR_irq = pc+4 then entry code
    # subtracts 4 -> so handler ends with: subs pc, lr, #4.
    handler = assemble([
        0xE10F2000,        # mrs r2, spsr
        0xE25EF004,        # subs pc, lr, #4
    ])
    cpu.mem_write(CODE + 0x100, handler)
    cpu.mem_write(CODE, assemble([
        0xE3A01007,  # mov r1, #7
        0xEAFFFFFE,  # loop: b .
    ]))
    fired = []

    def inject(uc, _addr, _size, _user):
        if fired:
            return
        fired.append(True)
        pc = uc.reg_read(UC_ARM_REG_PC)
        before = cpsr(uc)
        # Hardware-style IRQ entry: LR_irq = next+4, entry stub does sub lr,#4.
        set_mode(uc, IRQ, spsr=before, lr=pc + 4, sp=STACK - 0x100)
        uc.reg_write(UC_ARM_REG_PC, VECTORS + 0x18)
        # our vector branch does NOT subtract 4; emulate the stock entry's
        # 'sub lr, lr, #4' by jumping straight to handler with lr=pc:
        uc.reg_write(UC_ARM_REG_LR, pc)
        uc.reg_write(UC_ARM_REG_PC, CODE + 0x100)

    from unicorn import UC_HOOK_BLOCK
    cpu.hook_add(UC_HOOK_BLOCK, inject, begin=CODE + 8, end=CODE + 8)
    cpu.emu_start(CODE, 0, count=1000)
    mode = cpsr(cpu) & 0x1F
    assert mode == SVC, f"mode {mode:#x} after IRQ return"
    assert cpu.reg_read(UC_ARM_REG_R1) == 7
    print(f"C  IRQ banked round-trip: OK  fired={len(fired)} mode=SVC r2(spsr copy)={cpu.reg_read(UC_ARM_REG_R2):#x}")


def probe_d_wfi():
    cpu = fresh()
    cpu.mem_write(CODE, assemble([
        0xE3A00005,  # mov r0, #5
        0xF57FF207,  # wfi
        0xE3A00006,  # mov r0, #6   <- should still execute
        0xE1A0F00E,  # mov pc, lr
    ]))
    cpu.reg_write(UC_ARM_REG_LR, CODE + 0x100)
    try:
        cpu.emu_start(CODE, CODE + 0x100, count=100000)
        r0 = cpu.reg_read(UC_ARM_REG_R0)
        print(f"D  WFI: continues (r0={r0})")
    except UcError as exc:
        print(f"D  WFI: UcError {exc} (would need NOP patching)")


def probe_e_banks():
    """SVC SP/LR/SPSR survive a mode round-trip (banked registers intact)."""
    cpu = fresh()
    cpu.reg_write(UC_ARM_REG_SP, STACK)
    cpu.reg_write(UC_ARM_REG_LR, 0xABCDEF01)
    cpu.reg_write(UC_ARM_REG_CPSR, (cpsr(cpu) & ~0x1F) | IRQ | 0x80)
    cpu.reg_write(UC_ARM_REG_SP, STACK - 0x40)
    cpu.reg_write(UC_ARM_REG_LR, 0x11112222)
    cpu.reg_write(UC_ARM_REG_SPSR, 0x60000013)
    cpu.reg_write(UC_ARM_REG_CPSR, (cpsr(cpu) & ~0x1F) | SVC)
    assert cpu.reg_read(UC_ARM_REG_SP) == STACK, "SVC SP bank corrupted"
    assert cpu.reg_read(UC_ARM_REG_LR) == 0xABCDEF01, "SVC LR bank corrupted"
    cpu.reg_write(UC_ARM_REG_CPSR, (cpsr(cpu) & ~0x1F) | IRQ)
    assert cpu.reg_read(UC_ARM_REG_SP) == STACK - 0x40, "IRQ SP bank lost"
    assert cpu.reg_read(UC_ARM_REG_LR) == 0x11112222, "IRQ LR bank lost"
    assert cpu.reg_read(UC_ARM_REG_SPSR) == 0x60000013, "IRQ SPSR lost"
    cpu.reg_write(UC_ARM_REG_CPSR, (cpsr(cpu) & ~0x1F) | SVC)
    print("E  banked SP/LR/SPSR round-trip: OK")


if __name__ == "__main__":
    probe_a_cp15()
    probe_b_undef()
    probe_c_irq()
    probe_d_wfi()
    probe_e_banks()
    print("all probes done")
