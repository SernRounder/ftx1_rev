import struct, re, pickle
from collections import Counter, defaultdict
from capstone import *

data = open(r"work/dec/FTX-1_IFDSP_V0110.SFL.bin", "rb").read()
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)

def sweep(start, end):
    """resync linear sweep; yield instructions"""
    off = start
    while off < end:
        got = False
        for ins in md.disasm(data[off:end], off):
            yield ins
            off = ins.address + ins.size
            got = True
        if not got:
            off += 2

REGIONS = [(0x21800, 0x5c400, 0x1E3290, "R1"), (0x61800, len(data), 0x1E784, "R2")]

bl_targets = defaultdict(set)   # target -> set(callsite files offs)
funcs = set()
for lo, hi, K, tag in REGIONS:
    for ins in sweep(lo, hi):
        if ins.mnemonic == "bl":
            try:
                t = int(ins.op_str.lstrip("#"), 0)
            except ValueError:
                continue
            if lo <= t < hi:
                funcs.add(t)
                bl_targets[t].add(ins.address)

print("BL-derived function starts:", len(funcs))
per_region = {t: ("R1" if t < 0x5c400 else "R2") for t in funcs}
c1 = sum(1 for t in funcs if t < 0x5c400)
c2 = len(funcs) - c1
print(f"region1: {c1}, region2: {c2}")

# save
with open("funcs.pkl", "wb") as f:
    pickle.dump({"funcs": sorted(funcs), "bl_targets": {k: sorted(v) for k, v in bl_targets.items()}, "K": {"R1": 0x1E3290, "R2": 0x1E784}}, f)

# fan-out stats: most-called functions = libs/kernel
calls_count = {t: len(v) for t, v in bl_targets.items()}
top = sorted(calls_count.items(), key=lambda kv: -kv[1])[:40]
print("\ntop called functions:")
for t, c in top:
    r = "R1" if t < 0x5c400 else "R2"
    K = 0x1E3290 if r == "R1" else 0x1E784
    print(f"  {r} file {t:#08x} (addr {t+K:#010x}): {c} calls")
