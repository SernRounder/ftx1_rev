import struct

path = r"work/dec/FTX-1_IFDSP_V0110.SFL.bin"
data = open(path, "rb").read()

def hexdump(off, n):
    for i in range(off, off + n, 16):
        chunk = data[i:i+16]
        h = " ".join(f"{b:02x}" for b in chunk)
        a = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        print(f"{i:08x}  {h:<48}  {a}")

print("== head 0x40 ==")
hexdump(0, 0x40)
print("== nonzero regions in first 0x2000 ==")
runs = []
start = None
for i in range(0x2000):
    if data[i] != 0:
        if start is None:
            start = i
    else:
        if start is not None:
            runs.append((start, i))
            start = None
if start is not None:
    runs.append((start, 0x2000))
for s, e in runs:
    print(f"nonzero {s:#x}..{e:#x} (len {e-s:#x})")
    if e - s <= 0x100:
        hexdump(s, min(e - s, 0x100))

# Also: any 0x2000xxxx word anywhere in first 0x400 that could be SP
print("== words that look like SRAM pointers in first 0x400 ==")
for o in range(0, 0x400, 4):
    (w,) = struct.unpack_from("<I", data, o)
    if 0x20000000 <= w < 0x20080000:
        print(hex(o), hex(w))
