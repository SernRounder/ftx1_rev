import struct
from collections import Counter

path = r"work/dec/FTX-1_IFDSP_V0110.SFL.bin"
data = open(path, "rb").read()

regions = {
    "region1": (0x21800, 0x5c400),
    "region2": (0x61800, len(data)),
}

for name, (lo, hi) in regions.items():
    words = []
    for o in range(lo, hi - 3, 4):
        (w,) = struct.unpack_from("<I", data, o)
        if w:
            words.append(w)
    votes = Counter()
    for w in words:
        # base B such that target file offset w-B in [lo,hi)
        # B = w - t for t in [lo, hi) -> B in (w-hi, w-lo]
        Bmin = w - hi + 1
        Bmax = w - lo
        # iterate 0x1000-aligned B in range (cap to sane)
        b = (Bmin + 0xFFF) & ~0xFFF
        while b <= Bmax:
            if 0 <= b < 0x40000000:
                votes[b] += 1
            b += 0x1000
    print(f"\n{name}: top self-reference bases (0x1000-aligned):")
    for B, c in votes.most_common(12):
        print(f"  base {B:#010x}: {c} self-refs ({c*100//len(words)}% of {len(words)} words)")
