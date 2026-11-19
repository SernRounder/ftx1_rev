import struct, re
from collections import Counter, defaultdict
from capstone import *

data = open(r"work/dec/FTX-1_IFDSP_V0110.SFL.bin", "rb").read()
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)

def disasm(start, end):
    off = start
    while off < end:
        got = False
        for ins in md.disasm(data[off:end], off):
            yield ins
            off = ins.address + ins.size
            got = True
        if not got:
            off += 2

# region 2: RAM = file + 0x1E784. Region 1: unknown K (RAM = file + K).
# Collect strict literal loads in region 1 only.
R1LO, R1HI = 0x21800, 0x5c400
lit = []
for ins in disasm(R1LO, R1HI):
    m = re.match(r"(\w+), \[pc, #(0x[0-9a-f]+|-?\d+)\]", ins.op_str)
    if ins.mnemonic == "ldr" and m:
        pool = ((ins.address + 4) & ~3) + int(m.group(2), 0)
        if R1LO <= pool <= R1HI - 4:
            (w,) = struct.unpack_from("<I", data, pool)
            lit.append((ins.address, pool, w))
print("region1 literal loads:", len(lit))

# anchors: strings in region1 data (file offsets)
anchors = {}
for off, name in [(0x28d10,"C4Uart"),(0x28d1c,"Thread_Ipc"),(0x28d28,"Thread_Main"),
                  (0x28d34,"Rx_Audio"),(0x28d40,"Rx_C4FM"),(0x28d48,"Tx_C4FM"),
                  (0x28d50,"Composite_SPI"),(0x28d60,"Rx_Path"),(0x28d68,"Tx_Path"),
                  (0x28d70,"idle"),(0x28d75,"suspended"),(0x28d7e,"delay"),
                  (0x28d86,"exited"),(0x28d90,"join"),(0x28d95,"event"),
                  (0x28d9c,"cond"),(0x28da4,"mutex"),(0x28dc0,"powf"),(0x28dc8,"sqrtf")]:
    anchors[off] = name

# solve K = A - f for each (word, anchor) with K in plausible RAM window 0x0..0x400000, and K maps region1 into <=0x200000+slack
votes = Counter()
ev = defaultdict(list)
for site, pool, w in lit:
    for f, name in anchors.items():
        K = w - f
        if 0x1000 <= K < 0x400000:
            votes[K] += 1
            ev[K].append((site, w, name))

top = [(K, c) for K, c in votes.most_common(30)]
# cluster by 4KB
cl = Counter()
for K, c in top:
    cl[K & ~0xFFF] += c
print("clustered K votes:", [(hex(k), c) for k, c in cl.most_common(8)])

for K, c in votes.most_common(6):
    names = sorted(set(n for _, _, n in ev[K]))
    print(f"\nK={K:#x} votes={c} anchors={names}")
    for site, w, n in ev[K][:8]:
        print(f"   ldr@{site:#x} word={w:#x} -> {n}")
