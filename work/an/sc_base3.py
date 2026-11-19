import struct
from collections import defaultdict

path = r"work/dec/FTX-1_IFDSP_V0110.SFL.bin"
data = open(path, "rb").read()

POOL_LO, POOL_HI = 0x28c80, 0x28e40

words = []
for o in range(0, len(data) - 3, 4):
    (w,) = struct.unpack_from("<I", data, o)
    if w:
        words.append((o, w))
print("aligned nonzero words:", len(words))

# candidate bases: B such that word w maps into pool. B = w - t for t in pool range.
# Accumulate per 0x100-rounded base bucket.
from collections import Counter
votes = Counter()
evidence = defaultdict(list)
for o, w in words:
    for t in range(POOL_LO, POOL_HI, 4):
        B = w - t
        if 0x00000000 <= B < 0x20000000 and (B & 0xFFF) == 0:  # aligned base candidates only
            votes[B] += 1
            evidence[B].append((o, w, t))

print("\ntop 4K-aligned base candidates by #words pointing into string pool:")
for B, c in votes.most_common(10):
    print(f"base={B:#010x}  words_into_pool={c}")
    for o, w, t in evidence[B][:12]:
        s = data[t:t+20]
        txt = "".join(chr(b) if 32 <= b < 127 else "." for b in s[:14])
        print(f"   word@{o:#08x}={w:#010x} -> file {t:#x}: {txt!r}")
