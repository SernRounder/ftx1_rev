import struct, re
from collections import Counter, defaultdict
from capstone import *

path = r"work/dec/FTX-1_IFDSP_V0110.SFL.bin"
data = open(path, "rb").read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
md.detail = False

def disasm_region(start, end):
    """linear sweep with resync, yields instructions"""
    off = start
    while off < end:
        got = False
        for ins in md.disasm(data[off:end], off):
            yield ins
            off = ins.address + ins.size
            got = True
        if not got:
            off += 2  # skip bad halfword

regions = [(0x21800, 0x5c400), (0x61800, len(data))]
n_ins = 0
ldr_pc = []
bl_targets = Counter()
for start, end in regions:
    for ins in disasm_region(start, end):
        n_ins += 1
        if ins.mnemonic == "ldr" and ins.op_str.startswith(("r", "w")) and "[pc" in ins.op_str:
            m = re.match(r"(\w+), \[pc, #(0x[0-9a-f]+|-?\d+)\]", ins.op_str)
            if m:
                imm = int(m.group(2), 0)
                pool = ((ins.address + 4) & ~3) + imm
                ldr_pc.append((ins.address, pool))
        elif ins.mnemonic == "bl":
            try:
                t = int(ins.op_str.lstrip("#"), 0)
                bl_targets[t] += 1
            except ValueError:
                pass

print("instructions decoded:", n_ins)
print("pc-relative ldr count:", len(ldr_pc))
print("distinct BL targets:", len(bl_targets))

# now read pool words and vote on base using string anchors
anchors = {
    0x28d10: "C4Uart", 0x28d1c: "Thread_Ipc", 0x28d28: "Thread_Main",
    0x28d34: "Rx_Audio", 0x28d40: "Rx_C4FM", 0x28d48: "Tx_C4FM",
    0x28d50: "Composite_SPI", 0x28d60: "Rx_Path", 0x28d68: "Tx_Path",
}
votes = Counter()
ev = defaultdict(list)
for site, pool in ldr_pc:
    if pool + 4 > len(data):
        continue
    (w,) = struct.unpack_from("<I", data, pool)
    for a, name in anchors.items():
        B = w - a
        if 0x01000000 <= B < 0x12000000:
            votes[B] += 1
            ev[B].append((site, pool, w, name))

print("\ntop exact base votes:")
for B, c in votes.most_common(8):
    names = sorted(set(n for *_, n in ev[B]))
    print(f"base={B:#010x} votes={c} anchors={names}")
    for site, pool, w, name in ev[B][:8]:
        print(f"   ldr@{site:#08x} pool@{pool:#08x} -> {w:#010x} ({name})")
