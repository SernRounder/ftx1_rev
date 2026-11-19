import struct, re
from capstone import *

data = open(r"work/dec/FTX-1_IFDSP_V0110.SFL.bin", "rb").read()
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
K1 = 0x1E3290

def try_sync(anchor_pool, lo, hi):
    """try disasm starting at every halfword in [lo,hi); return (start, ins) streams containing a pc-ldr hitting anchor_pool"""
    for s in range(lo, hi, 2):
        ins_list = list(md.disasm(data[s:hi], s))
        # stop if a bad decode occurs early -> md.disasm returns partial list
        if len(ins_list) < 4:
            continue
        for k, ins in enumerate(ins_list):
            if ins.address > anchor_pool - 4:
                break
            m = re.match(r"(\w+), \[pc, #(0x[0-9a-f]+|-?\d+)\]", ins.op_str)
            if ins.mnemonic == "ldr" and m:
                pool = ((ins.address + 4) & ~3) + int(m.group(2), 0)
                if pool == anchor_pool:
                    return s, ins_list, k
    return None

r = try_sync(0x2aac0, 0x2a9e0, 0x2aac0)
if r:
    s, ins_list, k = r
    print(f"synced start {s:#x}; reference at index {k}")
    for ins in ins_list[max(0, k-25):k+6]:
        ann = ""
        m = re.match(r"(\w+), \[pc, #(0x[0-9a-f]+|-?\d+)\]", ins.op_str)
        if ins.mnemonic == "ldr" and m:
            pool = ((ins.address + 4) & ~3) + int(m.group(2), 0)
            if pool + 4 <= len(data):
                (w,) = struct.unpack_from("<I", data, pool)
                extra = ""
                if 0x205090 <= w < 0x23FC90:
                    extra = f" (region1 file {w-K1:#x})"
                ann = f"   ; ={w:#010x}{extra}"
        print(f"{ins.address:#08x}: {ins.bytes.hex():<10} {ins.mnemonic:<9} {ins.op_str}{ann}")
