import struct
from collections import Counter

data = open(r"work/dec/FTX-1_IFDSP_V0110.SFL.bin", "rb").read()
LO, HI = 0x21800, 0x5c400

# histogram of word values by 64KB bucket, in blob
hist = Counter()
words = []
for o in range(LO, HI - 3, 4):
    (w,) = struct.unpack_from("<I", data, o)
    if w:
        words.append(w)
        hist[w >> 16] += 1
print("word high-16 histogram (blob):")
for h, c in sorted(hist.items(), key=lambda kv: -kv[1])[:16]:
    print(f"  {h:08x}xxxx: {c}")

# pointer family: values in 0x200000..0x280000; find implied load base via diff-pair clustering
# For a table at 0x28e20 with consecutive +4 targets, targets are data addrs. Try to find L:
# count words in [L, L+0x3AC00) per L candidate (0x1000 steps) - maximize
best = Counter()
for w in words:
    if 0x200000 <= w < 0x300000:
        # L in (w-HI, w-LO]
        lmin = w - HI + 1
        lmax = w - LO
        b = (lmin + 0xFFF) & ~0xFFF
        while b <= lmax:
            best[b] += 1
            b += 0x1000
print("\ntop blob load bases (words self-contained):")
for L, c in best.most_common(10):
    print(f"  L={L:#x}: {c}")
