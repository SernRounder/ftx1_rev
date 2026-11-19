import struct
from collections import Counter, defaultdict
from capstone import *

path = r"work/dec/FTX-1_IFDSP_V0110.SFL.bin"
data = open(path, "rb").read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
md.detail = True

regions = [(0x21800, 0x5c400), (0x61800, len(data))]

# collect literal loads: ldr rt, [pc, #imm] -> pool addr
lit_words = []  # (site_off, pool_off, word)
for start, end in regions:
    code = data[start:end]
    for ins in md.disasm(code, start):
        if ins.mnemonic == "ldr" and "[pc" in ins.op_str:
            # parse: ldr rX, [pc, #0x123]
            import re
            m = re.match(r"(\w+), \[pc,? ?#?(0x[0-9a-f]+|\d+)?\]?", ins.op_str)
            if not m:
                continue
            imm = m.group(2)
            imm = int(imm, 0) if imm else 0
            pool = ((ins.address + 4) & ~3) + imm
            if start <= pool <= end - 4:
                (w,) = struct.unpack_from("<I", data, pool)
                lit_words.append((ins.address, pool, w))

print("literal loads found:", len(lit_words))

# string pool anchors (task names)
anchors = {
    0x28d10: "C4Uart", 0x28d1c: "Thread_Ipc", 0x28d28: "Thread_Main",
    0x28d34: "Rx_Audio", 0x28d40: "Rx_C4FM", 0x28d48: "Tx_C4FM",
    0x28d50: "Composite_SPI", 0x28d60: "Rx_Path", 0x28d68: "Tx_Path",
}
# Vote: base B such that word W points at anchor file offset: B = W - anchor
votes = Counter()
ev = defaultdict(list)
for site, pool, w in lit_words:
    for a, name in anchors.items():
        B = w - a
        if 0x01000000 <= B < 0x12000000:  # plausible flash bases
            votes[B] += 1
            ev[B].append((site, pool, w, name))

print("\ntop exact base votes (from literal loads only):")
for B, c in votes.most_common(10):
    names = set(n for *_, n in ev[B])
    print(f"base={B:#010x} votes={c} distinct-anchors={len(names)}")
    for site, pool, w, name in ev[B][:10]:
        print(f"   ldr@{site:#x} pool@{pool:#x} -> {w:#010x} = base+{w-B:#x} ({name})")
