# @runtime PyGhidra
# 第五批:全库扫描 5 个 slot 入口的调用点(bsr/jsr 目标匹配)
import os, re
from ghidra.app.decompiler import DecompInterface

OUT = r"work/an/tx_study/main"
DEC = os.path.join(OUT, "decomp")
TARGETS = {0xFFEF7973, 0xFFEF7999, 0xFFEF79BF, 0xFFEF79E5, 0xFFEF7A0B,
           0xFFEF7979, 0xFFEF799F, 0xFFEF79C5, 0xFFEF79EB, 0xFFEF7A11,
           0xFFF585A7, 0xFFF5836E}
af = currentProgram.getAddressFactory().getDefaultAddressSpace()
fm = currentProgram.getFunctionManager()
listing = currentProgram.getListing()

def to_addr(v):
    return af.getAddress("%x" % v)

hits = []
for ins in listing.getInstructions(True):
    if monitor.isCancelled():
        break
    ft = ins.getFlowType()
    if not ft.isCall():
        continue
    for ref in ins.getReferencesFrom():
        if ref.getReferenceType().isCall() and ref.getToAddress().getOffset() in TARGETS:
            f = fm.getFunctionContaining(ins.getAddress())
            hits.append((str(ins.getAddress()), ref.getToAddress().getOffset(), str(f.getEntryPoint()) if f else "nofunc", f.getName() if f else "?"))

with open(os.path.join(OUT, "wrapper-callers.md"), "w", encoding="utf-8") as fh:
    fh.write("# slot 入口调用点扫描\n\n")
    for a, t, f, n in hits:
        fh.write("- %s -> 0x%X (in %s %s)\n" % (a, t, f, n))
println("[txstudy5] %d call hits" % len(hits))
for a, t, f, n in hits[:20]:
    println("[txstudy5] %s -> 0x%X in %s %s" % (a, t, f, n))

# 反编译命中函数
targets = {}
for a, t, f, n in hits:
    if f != "nofunc":
        fn = fm.getFunctionAt(to_addr(int(f, 16)))
        if fn:
            targets[str(fn.getEntryPoint())] = fn
println("[txstudy5] decompiling %d callers" % len(targets))
ifc = DecompInterface()
ifc.openProgram(currentProgram)
try:
    for k, fn in sorted(targets.items()):
        res = ifc.decompileFunction(fn, 120, monitor)
        code = res.getDecompiledFunction().getC() if (res.decompileCompleted() and res.getDecompiledFunction()) else "// FAILED"
        with open(os.path.join(DEC, "%s_%s.c" % (k, re.sub(r"[^A-Za-z0-9_.+-]", "_", fn.getName()))), "w", encoding="utf-8", errors="replace") as fh:
            fh.write("// addr=%s reason=caller-of-slot-wrapper\n\n%s\n" % (k, code))
        println("[txstudy5] done %s" % k)
finally:
    ifc.dispose()
println("[txstudy5] COMPLETE")
