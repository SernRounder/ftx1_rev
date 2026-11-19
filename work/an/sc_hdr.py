import struct

path = r"work/dec/FTX-1_IFDSP_V0110.SFL.bin"
data = open(path, "rb").read()

def hexdump(off, n, base=0):
    for i in range(off, off + n, 16):
        chunk = data[i:i+16]
        h = " ".join(f"{b:02x}" for b in chunk)
        a = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        print(f"{i:08x}  {h:<48}  {a}")

print("== 0x400..0x620 ==")
hexdump(0x400, 0x220)
print()
print("== 0x5c0..0x1100 words (nonzero only) ==")
for o in range(0x5c0, 0x1100, 4):
    (w,) = struct.unpack_from("<I", data, o)
    if w:
        print(f"{o:#08x}: {w:#010x}")
