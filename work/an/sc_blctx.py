import struct, re
from capstone import *

data = open(r"work/dec/FTX-1_IFDSP_V0110.SFL.bin", "rb").read()
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
K1 = 0x1E3290

def sweep(start, end):
    off = start
    while off < end:
        got = False
        for ins in md.disasm(data[off:end], off):
            yield ins
            off = ins.address + ins.size
            got = True
        if not got:
            off += 2

insns = list(sweep(0x21800, 0x5c400))
idx = {ins.address: i for i, ins in enumerate(insns)}

results = []
for i, ins in enumerate(insns):
    if ins.mnemonic != "bl":
        continue
    try:
        t = int(ins.op_str.lstrip("#"), 0)
    except ValueError:
        continue
    ctx = insns[max(0, i-8):i]
    # any ldr-literal loading an odd word (function pointer) into r0/r1/r3 in region1 window?
    for c in ctx:
        m3 = re.match(r"([rR][0-3]), \[pc, #(0x[0-9a-f]+|-?\d+)\]", c.op_str)
        if c.mnemonic == "ldr" and m3:
            pool = ((c.address + 4) & ~3) + int(m3.group(2), 0)
            if 0x21800 <= pool <= 0x5c400 - 4:
                (w,) = struct.unpack_from("<I", data, pool)
                if w & 1 and 0x205091 <= w < 0x23FC91:
                    results.append((ins.address, t, m3.group(1), w))

print(f"BL sites preceded by function-pointer literal load: {len(results)}")
for site, t, reg, w in results:
    print(f"  bl@{site:#x} -> {t:#x} | {reg} <- {w:#x} (entry file {w&~1:#x})")
