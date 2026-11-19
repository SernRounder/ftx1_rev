import struct, re
from collections import defaultdict
from capstone import *

data = open(r"work/dec/FTX-1_IFDSP_V0110.SFL.bin", "rb").read()
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
K1 = 0x1E3290

def disasm(start, end):
    off = start
    while off < end:
        got = False
        for ins in md.disasm(data[off:end], off):
            yield ins
            off = ins.address + ins.size
            got = True
        if not got:
            off += 2

names = {0x28d10: "C4Uart", 0x28d1c: "Thread_Ipc", 0x28d28: "Thread_Main",
         0x28d34: "Rx_Audio", 0x28d40: "Rx_C4FM", 0x28d48: "Tx_C4FM",
         0x28d50: "Composite_SPI", 0x28d60: "Rx_Path", 0x28d68: "Tx_Path"}

# track movw -> movt pairs per register
mov = {}
hits = []
for ins in disasm(0x21800, 0x5c400):
    m = re.match(r"(\w+), #?(0x[0-9a-f]+|\d+)$", ins.op_str)
    if not m:
        continue
    rd, imm = m.group(1), int(m.group(2), 0)
    if ins.mnemonic == "movw":
        mov[rd] = imm
    elif ins.mnemonic == "movt" and rd in mov:
        val = (imm << 16) | (mov[rd] & 0xFFFF)
        for f, n in names.items():
            a = f + K1
            if val in (a, a + 1):
                hits.append((ins.address, val, n))
        mov[rd] = -1  # consumed

for site, val, n in hits:
    print(f"movt-movw @ {site:#08x} built {val:#010x} -> {n}")
