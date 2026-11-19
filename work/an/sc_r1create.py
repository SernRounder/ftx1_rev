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
print("region1 instructions:", len(insns))

# find: ldr rX,[pc,#..] within 3 ins before a bl, where bl target called >=3 times w/ r2 stack pattern
# simpler: find all bl; look back 6 ins for mov.w r2,#imm (0x100..0x10000)
cands = []
for i, ins in enumerate(insns):
    if ins.mnemonic != "bl":
        continue
    try:
        t = int(ins.op_str.lstrip("#"), 0)
    except ValueError:
        continue
    ctx = insns[max(0, i-6):i]
    stack = None; entries = []; nameimm = None
    for c in ctx:
        m = re.match(r"r2, #?(0x[0-9a-f]+|\d+)$", c.op_str)
        if c.mnemonic in ("mov.w", "movs", "mov") and m:
            v = int(m.group(1), 0)
            if 0x100 <= v <= 0x10000:
                stack = v
        m2 = re.match(r"r1, #?(\d+)$", c.op_str)
        if c.mnemonic in ("movs", "mov.w", "mov") and m2:
            nameimm = int(m2.group(1))
        m3 = re.match(r"(\w+), \[pc, #(0x[0-9a-f]+|-?\d+)\]", c.op_str)
        if c.mnemonic == "ldr" and m3:
            pool = ((c.address + 4) & ~3) + int(m3.group(2), 0)
            if 0x21800 <= pool <= 0x5c400 - 4:
                (w,) = struct.unpack_from("<I", data, pool)
                entries.append((m3.group(1), w))
    if stack:
        cands.append((ins.address, t, stack, nameimm, entries))

from collections import Counter
tc = Counter(t for _, t, *_ in cands)
print("\ncall targets with stack-size arg pattern:")
for t, c in tc.most_common(12):
    print(f"  target {t:#x} (ram {t+K1:#x}): {c} sites")
    for a, tt, s, n, e in cands:
        if tt == t:
            ent = [(r, hex(w), f"file {w-K1:#x}" if w & 1 and 0x205090 <= (w & ~1) < 0x23FC90 else "") for r, w in e]
            print(f"    site {a:#x}: stack={s:#x} name_imm={n} lits={ent}")
