"""M0 probes round 2: syscall opcode handling, INSN_INVALID hook, block hooks."""

import struct

from unicorn import (Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_BLOCK, UC_HOOK_CODE,
                     UC_HOOK_INSN_INVALID, UC_HOOK_INTR, UcError)
from unicorn.arm_const import UC_ARM_REG_PC, UC_ARM_REG_R1, UC_ARM_REG_LR, UC_ARM_REG_CPSR

from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM

CODE = 0x00100000
SVC, UND = 0x13, 0x1B


def assemble(words):
    return b"".join(struct.pack("<I", w) for w in words)


def fresh():
    cpu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    cpu.mem_map(CODE, 0x10000)
    return cpu


def disasm(word):
    for insn in Cs(CS_ARCH_ARM, CS_MODE_ARM).disasm(struct.pack("<I", word), 0):
        return f"{insn.mnemonic} {insn.op_str}"
    return "UNDEFINED (capstone)"


def probe_syscall_opcode():
    print("syscall word 0xE7DF151F ->", disasm(0xE7DF151F))
    print("classic undef  0xE7F000F0 ->", disasm(0xE7F000F0))
    # What does unicorn do with 0xE7F000F0 with/without INSN_INVALID hook?
    cpu = fresh()
    cpu.mem_write(CODE, assemble([0xE3A01007, 0xE7F000F0, 0xE3A01009, 0xEAFFFFFE]))
    try:
        cpu.emu_start(CODE, 0, count=100)
        print("0xE7F000F0 executed silently, r1 =", cpu.reg_read(UC_ARM_REG_R1))
    except UcError as exc:
        print("0xE7F000F0 ->", exc)

    seen = []
    cpu2 = fresh()
    cpu2.mem_write(CODE, assemble([0xE3A01007, 0xE7F000F0, 0xE3A01009, 0xEAFFFFFE]))

    def on_invalid(uc, _user):
        pc = uc.reg_read(UC_ARM_REG_PC)
        seen.append(pc)
        return True  # skip the instruction

    cpu2.hook_add(UC_HOOK_INSN_INVALID, on_invalid)
    cpu2.emu_start(CODE, 0, count=100)
    print("with INSN_INVALID hook: seen=", [hex(p) for p in seen],
          "r1=", cpu2.reg_read(UC_ARM_REG_R1))


def probe_invalid_pc_redirect():
    """INSN_INVALID hook: can we redirect PC into a vector-like handler?"""
    cpu = fresh()
    # main: mov r1,#7 ; UNDEF(0xE7F000F0) ; mov r1,#9 ; b .
    cpu.mem_write(CODE, assemble([0xE3A01007, 0xE7F000F0, 0xE3A01009, 0xEAFFFFFE]))
    # handler at CODE+0x100: mov r1,#0x42 ; movs pc, lr  (lr = insn after undef)
    cpu.mem_write(CODE + 0x100, assemble([0xE3A01042, 0xE1B0F00E]))
    done = []

    def on_invalid(uc, _user):
        pc = uc.reg_read(UC_ARM_REG_PC)
        done.append(pc)
        if pc == CODE + 4:
            cur = uc.reg_read(UC_ARM_REG_CPSR)
            uc.reg_write(UC_ARM_REG_CPSR, (cur & ~0x1F) | UND | 0xC0)
            uc.reg_write(UC_ARM_REG_LR, pc + 4)  # UNDEF lr = next insn
            uc.reg_write(UC_ARM_REG_PC, CODE + 0x100)
            return True
        return True

    cpu.hook_add(UC_HOOK_INSN_INVALID, on_invalid)
    cpu.emu_start(CODE, 0, count=1000)
    r1 = cpu.reg_read(UC_ARM_REG_R1)
    mode = cpu.reg_read(UC_ARM_REG_CPSR) & 0x1F
    print(f"redirect via INSN_INVALID: r1={r1:#x} (want 0x42 via handler) mode={mode:#x} sites={[hex(p) for p in done]}")


def probe_block_hook():
    """Why did round-1 block hook not fire? enumerate blocks."""
    cpu = fresh()
    cpu.mem_write(CODE, assemble([0xE3A01007, 0xEAFFFFFE]))  # mov r1,#7; b .
    blocks = []

    def on_block(uc, addr, size, _user):
        blocks.append((addr, size))

    cpu.hook_add(UC_HOOK_BLOCK, on_block)
    cpu.emu_start(CODE, 0, count=500)
    uniq = sorted(set(blocks))
    print("blocks (first 5 uniq):", [(hex(a), s) for a, s in uniq[:5]], "total hits:", len(blocks))

    # now range-limited to the loop address
    cpu2 = fresh()
    cpu2.mem_write(CODE, assemble([0xE3A01007, 0xEAFFFFFE]))
    hits = []
    cpu2.hook_add(UC_HOOK_BLOCK, lambda uc, a, s, u: hits.append(a),
                  begin=CODE + 4, end=CODE + 4)
    cpu2.emu_start(CODE, 0, count=500)
    print("range-limited block hook hits:", len(hits))


if __name__ == "__main__":
    probe_syscall_opcode()
    probe_invalid_pc_redirect()
    probe_block_hook()
