import struct
from capstone import *

path = r"work/dec/FTX-1_IFDSP_V0110.SFL.bin"
data = open(path, "rb").read()
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)

print("== disasm file 0x11a8 (candidate reset 0x080011a8) ==")
for ins in md.disasm(data[0x11a8:0x11a8+0x80], 0x11a8):
    print(f"{ins.address:#08x}: {ins.bytes.hex():<12} {ins.mnemonic} {ins.op_str}")

print("\n== disasm file 0x120c (candidate 0x0800120d) ==")
for ins in md.disasm(data[0x120c:0x120c+0x40], 0x120c):
    print(f"{ins.address:#08x}: {ins.bytes.hex():<12} {ins.mnemonic} {ins.op_str}")

print("\n== disasm file 0x1244 (candidate 0x08001245 stub) ==")
for ins in md.disasm(data[0x1244:0x1244+0x20], 0x1244):
    print(f"{ins.address:#08x}: {ins.bytes.hex():<12} {ins.mnemonic} {ins.op_str}")

# hexdump 0x1100..0x1240
print("\n== hex 0x1100..0x1240 ==")
for i in range(0x1100, 0x1240, 16):
    chunk = data[i:i+16]
    h = " ".join(f"{b:02x}" for b in chunk)
    print(f"{i:08x}  {h}")
