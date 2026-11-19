"""M0 probe 3: MMIO read-value substitution via read hooks; write hook ordering."""

import struct

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2

CODE = 0x00100000
MMIO = 0xE8000000


def assemble(words):
    return b"".join(struct.pack("<I", w) for w in words)


cpu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
cpu.mem_map(CODE, 0x1000)
cpu.mem_map(MMIO, 0x1000)

reads, writes = [], []


def on_read(uc, access, address, size, value, user):
    reads.append((address, size))
    # Substitute: pretend the register holds 0xCAFE.
    uc.mem_write(address, struct.pack("<I", 0xCAFE))


def on_write(uc, access, address, size, value, user):
    writes.append((address, size, value))


cpu.hook_add(UC_HOOK_MEM_READ, on_read, begin=MMIO, end=MMIO + 0xFFF)
cpu.hook_add(UC_HOOK_MEM_WRITE, on_write, begin=MMIO, end=MMIO + 0xFFF)

# ldr r2, [r1] with r1=MMIO ; str r2, [r1, #4]
cpu.mem_write(CODE, assemble([
    0xE59F1000 & 0xFFFFFFFF,  # placeholder (unused)
    0xE59F1000,
]))
cpu.mem_write(CODE, assemble([
    0xE59F2000,  # ldr r2, [pc]  -> reads literal
]))
# Simpler: build program with literal pool.
prog = assemble([
    0xE1A01000,        # mov r1, r0        (r0 = MMIO base passed in)
    0xE5912000,        # ldr r2, [r1]      (read MMIO+0)
    0xE5812004,        # str r2, [r1, #4]  (write MMIO+4)
    0xE1A0F00E,        # mov pc, lr
])
cpu.mem_write(CODE, prog)
cpu.reg_write(UC_ARM_REG_R0, MMIO)
cpu.reg_write(UC_ARM_REG_R2, 0)
cpu.emu_start(CODE, CODE + 12, count=100)

print("reads:", reads, "writes:", writes)
print("r2 =", hex(cpu.reg_read(UC_ARM_REG_R2)), "(want 0xcafe => substitution works)")
mem_after = cpu.mem_read(MMIO + 4, 4)
print("mem[MMIO+4] after store:", mem_after.hex(), "(write-through stored)")
