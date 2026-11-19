from capstone import *

data = open(r"work/dec/FTX-1_IFDSP_V0110.SFL.bin", "rb").read()
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)

# per 0x400 block: (a) instructions decoded from block start sync, (b) push prologue count, (c) bl count
print("block     ins  push  bl   | thumb-likeness")
runs = []
cur = None
for b in range(0x21800, 0x5c400, 0x400):
    chunk = data[b:b+0x400]
    ins_list = list(md.disasm(chunk, b))
    n = len(ins_list)
    pushes = sum(1 for i in ins_list if i.mnemonic == "push")
    bls = sum(1 for i in ins_list if i.mnemonic == "bl")
    pops = sum(1 for i in ins_list if i.mnemonic in ("pop", "pop.w"))
    # thumb score
    score = pushes + bls + pops
    kind = "CODE" if score >= 4 else ("code?" if score >= 1 else "data?")
    if cur and cur[0] == kind:
        cur[2] = b + 0x400
        cur[3] += n; cur[4] += score
    else:
        if cur: runs.append(cur)
        cur = [kind, b, b + 0x400, n, score]
if cur: runs.append(cur)
for kind, s, e, n, sc in runs:
    print(f"{s:#08x}-{e:#08x} {kind:6} ins={n:5} score={sc:4}")
