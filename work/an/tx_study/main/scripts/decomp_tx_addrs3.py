# @runtime PyGhidra
# 第三批:函数指针 xref(ffef79xx)+ 播放流检测 + 辅助函数
import os, re
from ghidra.app.decompiler import DecompInterface

OUT = r"work/an/tx_study/main"
DEC = os.path.join(OUT, "decomp")

FUNCS = [0xFFED6822, 0xFFEC0708, 0xFFF589BA, 0xFFF58C1C, 0xFFF58CF2,
         0xFFF585A7, 0xFFED12FA, 0xFFEA65FD, 0xFFEA517C, 0xFFEA51F5, 0xFFEA5432,
         0xFFECC23D, 0xFFED2594, 0xFFEC7A59, 0xFFECA85A, 0xFFEA7E71]
PTRS = [0xFFEF7A11, 0xFFEF799F, 0xFFEF7979, 0xFFF5836E, 0xFFEF7ADD]

af = currentProgram.getAddressFactory().getDefaultAddressSpace()
fm = currentProgram.getFunctionManager()
rm = currentProgram.getReferenceManager()

def to_addr(v):
    return af.getAddress("%x" % v)

def sanitize(s):
    return re.sub(r"[^A-Za-z0-9_.+-]", "_", s)

# 函数指针引用查找(含数据引用)
lines = ["# 函数指针/入口引用查找\n"]
for v in PTRS:
    a = to_addr(v)
    refs = []
    for ref in rm.getReferencesTo(a):
        frm = ref.getFromAddress()
        f = fm.getFunctionContaining(frm)
        refs.append("  %s in %s (%s)" % (str(frm), f.getName() if f else "nofunc/data", ref.getReferenceType()))
    lines.append("## 0x%X -> %d refs\n%s\n" % (v, len(refs), "\n".join(refs) if refs else "  (none)"))
    println("[txstudy3] ptr 0x%X -> %d refs" % (v, len(refs)))

targets = {}
def add_target(f, reason):
    if f is None:
        return
    k = str(f.getEntryPoint())
    if k not in targets:
        targets[k] = (f, set())
    targets[k][1].add(reason)

for v in FUNCS:
    f = fm.getFunctionAt(to_addr(v))
    if f:
        add_target(f, "core3")
    else:
        println("[txstudy3] MISSING FUNC 0x%X" % v)

# 指针引用者所在函数也反编译
for v in PTRS:
    for ref in rm.getReferencesTo(to_addr(v)):
        f = fm.getFunctionContaining(ref.getFromAddress())
        add_target(f, "ptrref-0x%X" % v)

println("[txstudy3] decompile set: %d" % len(targets))
ifc = DecompInterface()
ifc.openProgram(currentProgram)
try:
    for k, (f, rs) in sorted(targets.items(), key=lambda kv: int(kv[0], 16)):
        try:
            res = ifc.decompileFunction(f, 120, monitor)
            code = res.getDecompiledFunction().getC() if (res.decompileCompleted() and res.getDecompiledFunction()) else "// DECOMPILE FAILED"
        except Exception as e:
            code = "// EXCEPTION %s" % e
        with open(os.path.join(DEC, "%s_%s.c" % (k, sanitize(f.getName()))), "w", encoding="utf-8", errors="replace") as fh:
            fh.write("// addr=%s name=%s size=%d reason=%s\n\n%s\n" % (
                k, f.getName(), f.getBody().getNumAddresses(), ",".join(sorted(rs)), code))
        println("[txstudy3] done %s" % k)
finally:
    ifc.dispose()

with open(os.path.join(OUT, "ptr-refs.md"), "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines) + "\n")
println("[txstudy3] COMPLETE")
