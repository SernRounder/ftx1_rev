import struct
from capstone import *

data = open(r"work/dec/FTX-1_IFDSP_V0110.SFL.bin", "rb").read()
K1 = 0x1E3290

names = [(0x28d10, "C4Uart"), (0x28d1c, "Thread_Ipc"), (0x28d28, "Thread_Main"),
         (0x28d34, "Rx_Audio"), (0x28d40, "Rx_C4FM"), (0x28d48, "Tx_C4FM"),
         (0x28d50, "Composite_SPI"), (0x28d60, "Rx_Path"), (0x28d68, "Tx_Path")]
targets = {f + K1: n for f, n in names}

print("pointer words to task names in region1:")
for o in range(0x21800, 0x5c400 - 3, 4):
    (w,) = struct.unpack_from("<I", data, o)
    if w in targets:
        print(f"  word@{o:#08x} = {w:#010x} -> {targets[w]}")
# also -1/+1 (thumb)
targ2 = dict(targets)
for t, n in list(targets.items()):
    targ2[t + 1] = n + "|1"
targets = targ2
print("with thumb bit:")
for o in range(0x21800, 0x5c400 - 3, 4):
    (w,) = struct.unpack_from("<I", data, o)
    if w in targets:
        print(f"  word@{o:#08x} = {w:#010x} -> {targets[w]}")
