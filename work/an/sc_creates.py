import struct, re
from capstone import *

data = open(r"work/dec/FTX-1_IFDSP_V0110.SFL.bin", "rb").read()
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
K2 = 0x1E784

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

CREATE = 0x63a3c
sites = []
insns = list(sweep(0x61800, len(data)))
for i, ins in enumerate(insns):
    if ins.mnemonic == "bl":
        try:
            t = int(ins.op_str.lstrip("#"), 0)
        except ValueError:
            continue
        if t == CREATE:
            sites.append(i)
print(f"callers of create@{CREATE:#x}: {len(sites)}")
for i in sites:
    ctx = insns[max(0, i - 10):i + 2]
    print("----")
    for c in ctx:
        ann = ""
        m = re.match(r"(\w+), \[pc, #(0x[0-9a-f]+|-?\d+)\]", c.op_str)
        if c.mnemonic.startswith("ldr") and m:
            pool = ((c.address + 4) & ~3) + int(m.group(2), 0)
            if pool + 4 <= len(data):
                w = struct.unpack_from("<I", data, pool)[0]
                extra = ""
                if w & 1 and 0x80000 <= w - 1 < 0x107A00:
                    extra = f" entry file {w-1-K2:#x}"
                t2 = w - K2
                if 0x833d0 <= t2 < 0x83700:
                    s = data[t2:t2+20].split(b"\x00")[0]
                    extra = f" str {s.decode('latin1')!r}"
                ann = f"   ; ={w:#010x}{extra}"
        mark = " <<< bl create" if c.mnemonic == "bl" else ""
        print(f"{c.address:#08x}: {c.mnemonic:<9} {c.op_str}{ann}{mark}")
