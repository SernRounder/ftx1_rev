import struct
from capstone import *

path = r"work/dec/FTX-1_IFDSP_V0110.SFL.bin"
data = open(path, "rb").read()
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)

def dis(start, end, label):
    print(f"===== {label} {start:#x}..{end:#x} =====")
    off = start
    while off < end:
        got = False
        for ins in md.disasm(data[off:end], off):
            print(f"{ins.address:#08x}: {ins.bytes.hex():<12} {ins.mnemonic:<8} {ins.op_str}")
            off = ins.address + ins.size
            got = True
        if not got:
            print(f"{off:#08x}: {data[off]:02x}{data[off+1]:02x}  <bad>")
            off += 2

dis(0x1240, 0x16c8, "boot funcs")
dis(0x16c8, 0x1900, "boot main")
