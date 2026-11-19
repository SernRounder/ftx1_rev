import struct

path = r"work/dec/FTX-1_IFDSP_V0110.SFL.bin"
data = open(path, "rb").read()

print("== tail 0x83300..0x836fc ==")
for i in range(0x83300, len(data), 16):
    chunk = data[i:i+16]
    h = " ".join(f"{b:02x}" for b in chunk)
    a = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
    print(f"{i:08x}  {h:<48}  {a}")

# collect printable strings with offsets in tail
import re
print("\n== strings in 0x60000..end ==")
for m in re.finditer(rb"[\x20-\x7e]{4,}", data[0x60000:]):
    print(f"{0x60000+m.start():#08x}: {m.group().decode()!r}")
