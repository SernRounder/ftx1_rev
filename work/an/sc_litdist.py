import struct, re
from collections import Counter
from capstone import *

path = r"work/dec/FTX-1_IFDSP_V0110.SFL.bin"
data = open(path, "rb").read()
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)

def disasm_region(start, end):
    off = start
    while off < end:
        got = False
        for ins in md.disasm(data[off:end], off):
            yield ins
            off = ins.address + ins.size
            got = True
        if not got:
            off += 2

regions = [(0x21800, 0x5c400), (0x61800, len(data))]
pools = set()
for start, end in regions:
    for ins in disasm_region(start, end):
        if ins.mnemonic == "ldr":
            m = re.match(r"(\w+), \[pc, #(0x[0-9a-f]+|-?\d+)\]", ins.op_str)
            if m:
                pools.add(((ins.address + 4) & ~3) + int(m.group(2), 0))

words = []
for p in pools:
    if p + 4 <= len(data):
        (w,) = struct.unpack_from("<I", data, p)
        words.append((p, w))

print("pool words:", len(words))
hi = Counter((w >> 24) & 0xFF for _, w in words)
print("top-byte histogram (hex:count):")
for b, c in sorted(hi.items(), key=lambda kv: -kv[1])[:24]:
    print(f"  {b:02x}: {c}")

# show words in classic MCU ranges
def show(lo, hi_, label, limit=30):
    sel = [(p, w) for p, w in words if lo <= w < hi_]
    print(f"\n{label}: {len(sel)}")
    for p, w in sel[:limit]:
        # what would this point at, per-file-offset if base==lo-region mapping unknown
        print(f"  pool@{p:#08x} -> {w:#010x}")

show(0x08000000, 0x08200000, "in 0x0800_0000..0x0820_0000 (STM32 flash)")
show(0x20000000, 0x20080000, "in 0x2000_0000.. (SRAM)")
show(0x40000000, 0x50000000, "in 0x4000_0000.. (periph)")
show(0xE0000000, 0x100000000, "in 0xE000_0000.. (PPB)")
