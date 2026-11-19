import struct
from collections import Counter

path = r"work/dec/FTX-1_IFDSP_V0110.SFL.bin"
data = open(path, "rb").read()

# Known string offsets (task names etc.)
anchors = {
    0x28d10: "C4Uart", 0x28d1c: "Thread_Ipc", 0x28d28: "Thread_Main",
    0x28d34: "Rx_Audio", 0x28d40: "Rx_C4FM", 0x28d48: "Tx_C4FM",
    0x28d50: "Composite_SPI", 0x28d60: "Rx_Path", 0x28d68: "Tx_Path",
    0x28d70: "idle", 0x28d75: "suspended",
}

# All aligned words
words = []
for o in range(0, len(data) - 3, 4):
    (w,) = struct.unpack_from("<I", data, o)
    words.append((o, w))

# For each word, for each anchor, base = w - anchor. Vote.
votes = Counter()
detail = {}
for o, w in words:
    if w == 0:
        continue
    for a, name in anchors.items():
        base = w - a
        # plausible flash base for Cortex-M: aligned 0x10000, between 0 and 0x10000000
        if 0 <= base < 0x10000000:
            # round to 0x100 boundary to cluster
            votes[base & ~0xFF] += 1
            detail.setdefault(base & ~0xFF, []).append((o, w, name, base))

for b, c in votes.most_common(20):
    print(f"base~{b:#010x}  votes={c}")
    for o, w, name, exact in detail[b][:6]:
        print(f"   ref@{o:#08x} -> {w:#010x} ({name}, exact base {exact:#010x})")
