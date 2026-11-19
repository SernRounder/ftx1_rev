import struct
from capstone import *

data = open(r"work/dec/FTX-1_IFDSP_V0110.SFL.bin", "rb").read()

# 1. verify artifact: count byte pattern 'c0 20 00' in region1
blob = data[0x21800:0x5c400]
cnt = blob.count(bytes([0xC0, 0x20, 0x00]))
print(f"pattern 'c0 20 00' occurrences in region1 blob: {cnt}")
cnt2 = blob.count(bytes([0x20, 0x00]))
print(f"pattern '20 00': {cnt2}")

# 2. try architectures
archs = [
    ("TMS320C64x", CS_ARCH_TMS320C64X, CS_MODE_BIG_ENDIAN),
    ("TMS320C64x LE", CS_ARCH_TMS320C64X, CS_MODE_LITTLE_ENDIAN),
    ("TriCore", CS_ARCH_TRICORE, CS_MODE_LITTLE_ENDIAN),
    ("SH4", CS_ARCH_SH, CS_MODE_SH4 | CS_MODE_LITTLE_ENDIAN),
    ("MIPS32 LE", CS_ARCH_MIPS, CS_MODE_MIPS32 | CS_MODE_LITTLE_ENDIAN),
    ("XCore", CS_ARCH_XCORE, CS_MODE_LITTLE_ENDIAN),
    ("RISCV32", CS_ARCH_RISCV, CS_MODE_RISCV32 | CS_MODE_LITTLE_ENDIAN),
    ("M68K", CS_ARCH_M68K, CS_MODE_BIG_ENDIAN),
    ("PPC", CS_ARCH_PPC, CS_MODE_32 | CS_MODE_BIG_ENDIAN),
]
sample = data[0x25000:0x26000]
for name, arch, mode in archs:
    try:
        md = Cs(arch, mode)
        ins_list = list(md.disasm(sample, 0x25000))
        nbytes = sum(i.size for i in ins_list)
        print(f"{name}: {len(ins_list)} ins covering {nbytes}/4096 bytes")
    except Exception as e:
        print(f"{name}: error {e}")
