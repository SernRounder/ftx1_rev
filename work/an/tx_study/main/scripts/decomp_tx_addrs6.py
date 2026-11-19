# @runtime PyGhidra
# 第六批:CAT 键控处理器 ffeb48dc 的调用链上溯(ffea9c5a 及其 callers)
import os, re
from ghidra.app.decompiler import DecompInterface

OUT = r"work/an/tx_study/main"
DEC = os.path.join(OUT, "decomp")
af = currentProgram.getAddressFactory().getDefaultAddressSpace()
fm = currentProgram.getFunctionManager()

def to_addr(v):
    return af.getAddress("%x" % v)

targets = {}
def add(f, reason):
    if f is None:
        return
    k = str(f.getEntryPoint())
    if k not in targets:
        targets[k] = (f, set())
    targets[k][1].add(reason)

for v in [0xFFEA9C5A]:
    f = fm.getFunctionAt(to_addr(v))
    if f:
        add(f, "cat-dispatch")
        for c in f.getCallingFunctions(monitor):
            add(c, "caller-of-%x" % v)
            for c2 in c.getCallingFunctions(monitor):
                add(c2, "caller2-of-%x" % v)
    else:
        println("[txstudy6] MISSING 0x%X" % v)

println("[txstudy6] set=%d" % len(targets))
ifc = DecompInterface()
ifc.openProgram(currentProgram)
try:
    for k, (f, rs) in sorted(targets.items()):
        res = ifc.decompileFunction(f, 120, monitor)
        code = res.getDecompiledFunction().getC() if (res.decompileCompleted() and res.getDecompiledFunction()) else "// FAILED"
        with open(os.path.join(DEC, "%s_%s.c" % (k, re.sub(r"[^A-Za-z0-9_.+-]", "_", f.getName()))), "w", encoding="utf-8", errors="replace") as fh:
            fh.write("// addr=%s name=%s size=%d reason=%s\n\n%s\n" % (k, f.getName(), f.getBody().getNumAddresses(), ",".join(sorted(rs)), code))
        callers = ",".join(str(c.getEntryPoint()) for c in f.getCallingFunctions(monitor))
        println("[txstudy6] done %s %s size=%d callers=%s" % (k, f.getName(), f.getBody().getNumAddresses(), callers))
finally:
    ifc.dispose()
println("[txstudy6] COMPLETE")
