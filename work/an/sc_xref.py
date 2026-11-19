import struct

path = r"work/dec/FTX-1_IFDSP_V0110.SFL.bin"
data = open(path, "rb").read()

# 1. Search whole file for words == 0x08000000 + string offsets (and +1 thumb)
targets = {
    0x28d10: "C4Uart", 0x28d1c: "Thread_Ipc", 0x28d28: "Thread_Main",
    0x28d34: "Rx_Audio", 0x28d40: "Rx_C4FM", 0x28d48: "Tx_C4FM",
    0x28d50: "Composite_SPI", 0x28d60: "Rx_Path", 0x28d68: "Tx_Path",
}
hits = []
for o in range(0, len(data) - 3, 2):  # 2-aligned to catch odd placements
    (w,) = struct.unpack_from("<I", data, o)
    if (w & 0x0FFFFFF8) in (0x08000000 + a for a in targets) or w in (0x08000000 + a for a in targets):
        t = w - 0x08000000
        if t in targets:
            hits.append((o, w, targets[t]))
for o, w, n in hits:
    print(f"@{o:#08x}: {w:#010x} -> {n}")

# 2. Also all words in 0x08020000..0x08030000 (pointers into string pool neighborhood)
print("\npointers 0x0802_8000..0x0802_a000 anywhere in file:")
for o in range(0, len(data) - 3, 4):
    (w,) = struct.unpack_from("<I", data, o)
    if 0x08028000 <= w < 0x0802a000:
        t = w - 0x08000000
        s = data[t:t+16]
        txt = "".join(chr(b) if 32 <= b < 127 else "." for b in s)
        print(f"@{o:#08x}: {w:#010x} -> str {txt!r}")

# 3. Dump the string pool with context
print("\nstring pool dump 0x28c80..0x28e40:")
for i in range(0x28c80, 0x28e40, 16):
    chunk = data[i:i+16]
    h = " ".join(f"{b:02x}" for b in chunk)
    a = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
    print(f"{i:08x}  {h:<48}  {a}")
