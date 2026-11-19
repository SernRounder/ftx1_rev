import struct

path = r"work/dec/FTX-1_IFDSP_V0110.SFL.bin"
data = open(path, "rb").read()

# density map: fraction of nonzero bytes per 0x100 block
print("block   nonzero/256")
runs = []
cur_start = None
cur_nonzero = 0
for i in range(0, len(data), 0x100):
    blk = data[i:i+0x100]
    nz = sum(1 for b in blk if b)
    if nz > 4:
        if cur_start is None:
            cur_start = i
            cur_nz = 0
        cur_nz += nz
        runs and None
    else:
        if cur_start is not None:
            runs.append((cur_start, i, cur_nz))
            cur_start = None
if cur_start is not None:
    runs.append((cur_start, len(data), cur_nz))

# merge runs separated by small gaps
merged = []
for s, e, nz in runs:
    if merged and s - merged[-1][1] <= 0x400:
        merged[-1] = (merged[-1][0], e, merged[-1][2] + nz)
    else:
        merged.append((s, e, nz))
for s, e, nz in merged:
    print(f"dense {s:#08x}..{e:#08x}  len={e-s:#08x} nonzero={nz}")
