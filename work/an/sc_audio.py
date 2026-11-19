import struct, re
from collections import Counter, defaultdict
from capstone import *

data = open(r"work/dec/FTX-1_IFDSP_V0110.SFL.bin", "rb").read()
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
K2 = 0x1E784

def sweep(start, end):
    off = start
    while off < end:
        got = False
        for ins in md.disasm(data[off:end], off):
            yield ins
            off = ins.address + ins.size
            got = True
        if not got:
            off += 2

# 1) immediate constants of interest in code (mov.w/movs/compare)
INTERESTING = {16000: "16000(16k)", 8000: "8000", 2000: "2000", 4000: "4000", 32000: "32000",
               44100: "44100", 48000: "48000", 22050: "22050", 24000: "24000", 1200: "1200(baud)",
               9600: "9600", 115200: "115200", 1000000: "1e6", 441: "441", 882: "882"}
hits = defaultdict(list)
insns2 = list(sweep(0x61800, len(data)))
for ins in insns2:
    m = re.match(r"(\w+), #?(0x[0-9a-f]+|\d+)$", ins.op_str)
    if m and ins.mnemonic in ("mov.w", "movs", "mov", "cmp.w", "cmp", "cmp"):
        try:
            v = int(m.group(2), 0)
        except ValueError:
            continue
        if v in INTERESTING:
            hits[v].append((ins.address, ins.mnemonic))
    if ins.mnemonic in ("cmp.w", "cmp") :
        pass

for v, lst in sorted(hits.items()):
    print(f"{INTERESTING[v]}: {len(lst)} sites: {[hex(a) for a,_ in lst[:14]]}")

# 2) pool words equal to interesting values
print("\npool words:")
for o in range(0x61800, len(data) - 3, 4):
    (w,) = struct.unpack_from("<I", data, o)
    if w in INTERESTING:
        print(f"  @{o:#08x}: {w} ({INTERESTING[w]})")
