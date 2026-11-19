# @runtime PyGhidra
# 第七批(收尾):剩余 0x83B2C8 引用者 + ffea9c5a 中调 ffeb48dc 的 class 字节
import os, re
from ghidra.app.decompiler import DecompInterface

OUT = r"work/an/tx_study/main"
DEC = os.path.join(OUT, "decomp")
af = currentProgram.getAddressFactory().getDefaultAddressSpace()
fm = currentProgram.getFunctionManager()
listing = currentProgram.getListing()

def to_addr(v):
    return af.getAddress("%x" % v)

# 1) ffea9c5a 内调 ffeb48dc 的上下文(找 class 字节)
big = fm.getFunctionAt(to_addr(0xFFEA9C5A))
out = ["# ffeb48dc 调用点上下文\n"]
for ins in listing.getInstructions(big.getEntryPoint(), True):
    if not big.getBody().contains(ins.getAddress()):
        break
    for ref in ins.getReferencesFrom():
        if ref.getToAddress().getOffset() == 0xFFEB48DC:
            # 向上找 switch 分支标签:打印前 6 条指令
            ctx = []
            a2 = ins.getAddress()
            for i in range(6):
                a2 = a2.subtract(1)
                cu = listing.getInstructionAt(a2)
                if cu:
                    ctx.insert(0, "%s  %s" % (a2, cu.toString()))
            out.append("```\n" + "\n".join(ctx) + "\n%s  %s\n```" % (ins.getAddress(), ins.toString()))
            println("[txstudy7] call site %s" % ins.getAddress())

# 2) 反编译剩余函数
targets = {}
for v in [0xFFF57C64, 0xFFF58125, 0xFFEB1CDF, 0xFFED6742, 0xFFED6A82, 0xFFEA9250]:
    f = fm.getFunctionAt(to_addr(v))
    if f:
        targets[str(f.getEntryPoint())] = f
    else:
        println("[txstudy7] MISSING 0x%X" % v)

ifc = DecompInterface()
ifc.openProgram(currentProgram)
try:
    for k, f in sorted(targets.items()):
        res = ifc.decompileFunction(f, 120, monitor)
        code = res.getDecompiledFunction().getC() if (res.decompileCompleted() and res.getDecompiledFunction()) else "// FAILED"
        with open(os.path.join(DEC, "%s_%s.c" % (k, re.sub(r"[^A-Za-z0-9_.+-]", "_", f.getName()))), "w", encoding="utf-8", errors="replace") as fh:
            fh.write("// addr=%s name=%s size=%d reason=core7\n\n%s\n" % (k, f.getName(), f.getBody().getNumAddresses(), code))
        println("[txstudy7] done %s" % k)
finally:
    ifc.dispose()

with open(os.path.join(OUT, "cat-callsite.txt"), "w", encoding="utf-8") as fh:
    fh.write("\n".join(out) + "\n")
println("[txstudy7] COMPLETE")
