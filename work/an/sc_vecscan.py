import struct, sys

path = r"work/dec/FTX-1_IFDSP_V0110.SFL.bin"
data = open(path, "rb").read()
print("size", hex(len(data)))

# Scan for candidate vector tables: word[0] = valid RAM SP (0x2000xxxx or 0x1000xxxx etc, 8-aligned),
# word[1] = even value (thumb reset) that maps into image under some base.
# Strategy: for each offset, compute candidate base = word1 - (offset+4) ... but offset unknown.
# Better: brute force base candidates: assume reset vector word at offset o points to base+o+4 region.
# So base = word1_value - (o + 4). Collect votes per base, requiring word[0] looks like RAM pointer.

votes = {}
for o in range(0, min(len(data), 0x20000), 4):
    w0, w1 = struct.unpack_from("<II", data, o)
    # SP: top of RAM, typical 0x2000xxxx / 0x2001xxxx (STM32), 0x1000xxxx (ccm)
    if not (0x20000000 <= w0 < 0x20080000 or 0x10000000 <= w0 < 0x10010000):
        continue
    if w1 & 1 or w1 < 0x08000000 or w1 > 0x08200000:  # thumb, in flash
        continue
    base = w1 - (o + 4)
    votes[base] = votes.get(base, 0) + 1

for b, c in sorted(votes.items(), key=lambda kv: -kv[1])[:15]:
    print(hex(b), c)
