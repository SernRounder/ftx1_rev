import struct

data = open(r"work/dec/FTX-1_IFDSP_V0110.SFL.bin", "rb").read()
SHIFT = 0x1DE178  # blob file -> DSP RAM addr (blob loads at 0x200000, file 0x21e88)

def f2a(f):
    return f + SHIFT

def a2f(a):
    return a - SHIFT

BLOB_LO, BLOB_HI = 0x21e88, 0x5c3d0

def describe(w):
    """interpret a DSP word"""
    if 0x200000 <= w < 0x200000 + 0x3A548:
        f = a2f(w)
        # string?
        s = data[f:f + 16].split(b"\x00")[0]
        if len(s) >= 2 and all(32 <= b < 127 for b in s):
            return f"blob file {f:#x} str {s.decode()!r}"
        return f"blob file {f:#x}"
    if w & 1 and 0x200000 <= w - 1 < 0x200000 + 0x3A548:
        return f"blob file {a2f(w-1):#x} (thumb)"
    return ""

print("== dump file 0x2a800..0x2a9c0 (task table area) ==")
for i in range(0x2a800, 0x2a9c0, 4):
    w = struct.unpack_from("<I", data, i)[0]
    d = describe(w)
    print(f"{i:#08x} (dsp {f2a(i):#x}): {w:#010x}  {d}")
