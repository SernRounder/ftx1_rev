import struct

path = r"work/dec/FTX-1_IFDSP_V0110.SFL.bin"
data = open(path, "rb").read()

def dump(off, n, label):
    print(f"== {label} ==")
    for i in range(off, off + n, 16):
        chunk = data[i:i+16]
        h = " ".join(f"{b:02x}" for b in chunk)
        a = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        print(f"{i:08x}  {h:<48}  {a}")
    print()

dump(0x21800, 0x100, "region1 start 0x21800")
dump(0x61c00, 0x60, "around 0x61c00")
dump(0x61800, 0x100, "region2 start 0x61800")

# find where region2 really begins
print("nonzero scan 0x5c400..0x64000:")
for i in range(0x5c400, 0x64000, 0x40):
    blk = data[i:i+0x40]
    nz = sum(1 for b in blk if b)
    if nz:
        print(f"{i:#08x}: {nz}/64 nonzero")
