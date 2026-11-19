# @runtime PyGhidra
# 第二批:入队链/TX允许/SEND_A端口/任务入口 + 数据地址 xref(VOICE_PTT 等)
import os, re
from ghidra.app.decompiler import DecompInterface

OUT = r"work/an/tx_study/main"
DEC = os.path.join(OUT, "decomp")
os.makedirs(DEC, exist_ok=True)

FUNCS = [0xFFEF7A11, 0xFFEF799F, 0xFFEF7979, 0xFFF584FC, 0xFFF588F2,
         0xFFED6046, 0xFFED5BC9, 0xFFEA678A, 0xFFEA1158, 0xFFEA12A3,
         0xFFECA60A, 0xFFEC6639, 0xFFEC7253,
         0xFFF58E90, 0xFFF58E61, 0xFFEDDD2F,
         0xFFEC08DF, 0xFFF58D18, 0xFFECEF1C, 0xFFECF45A]
DATAS = [0x008013C5, 0x00801324, 0x00822D62, 0x00017B54, 0x008013D6,
         0x0083B2C8, 0x0083B2CC]   # VOICE_PTT/TX_SEQ/TX_ACCEPTED/TX原因/错误码/VOICE基址指针
MAX_PER_DATA = 20

af = currentProgram.getAddressFactory().getDefaultAddressSpace()
fm = currentProgram.getFunctionManager()
rm = currentProgram.getReferenceManager()

def to_addr(v):
    return af.getAddress("%x" % v)

def sanitize(s):
    return re.sub(r"[^A-Za-z0-9_.+-]", "_", s)

targets = {}
def add_target(f, reason):
    if f is None:
        return
    k = str(f.getEntryPoint())
    if k not in targets:
        targets[k] = (f, set())
    targets[k][1].add(reason)

data_hit_summary = []
for v in FUNCS:
    f = fm.getFunctionAt(to_addr(v))
    if f:
        add_target(f, "core2")
    else:
        println("[txstudy2] MISSING FUNC 0x%X" % v)

for v in DATAS:
    a = to_addr(v)
    fns = {}
    for ref in rm.getReferencesTo(a):
        frm = ref.getFromAddress()
        f = fm.getFunctionContaining(frm)
        key = str(f.getEntryPoint()) if f else "nofunc@" + str(frm)
        fns.setdefault(key, [0, f, ref.getReferenceType()])
        fns[key][0] += 1
    data_hit_summary.append((v, fns))
    println("[txstudy2] data 0x%X -> %d referencing funcs" % (v, len(fns)))
    for entry, (cnt, f, rtype) in sorted(fns.items(), key=lambda kv: -kv[1][0])[:MAX_PER_DATA]:
        if f is not None:
            add_target(f, "xref-0x%X(%s x%d)" % (v, rtype, cnt))

println("[txstudy2] decompile set: %d functions" % len(targets))

ifc = DecompInterface()
ifc.openProgram(currentProgram)
index = ["# MAIN TX 第二批反编译索引\n",
         "| entry | name | size | 命中原因 | callers | callees |",
         "|---|---|---|---|---|---|"]
try:
    for k, (f, rs) in sorted(targets.items(), key=lambda kv: int(kv[0], 16)):
        try:
            res = ifc.decompileFunction(f, 120, monitor)
            code = res.getDecompiledFunction().getC() if (res.decompileCompleted() and res.getDecompiledFunction()) else "// DECOMPILE FAILED"
        except Exception as e:
            code = "// EXCEPTION %s" % e
        fn = "%s_%s.c" % (k, sanitize(f.getName()))
        with open(os.path.join(DEC, fn), "w", encoding="utf-8", errors="replace") as fh:
            fh.write("// addr=%s name=%s size=%d reason=%s\n\n%s\n" % (
                k, f.getName(), f.getBody().getNumAddresses(), ",".join(sorted(rs)), code))
        callers = ",".join(str(c.getEntryPoint()) for c in f.getCallingFunctions(monitor))
        callees = ",".join(str(c.getEntryPoint()) for c in f.getCalledFunctions(monitor))
        index.append("| %s | %s | %d | %s | %s | %s |" % (
            k, f.getName(), f.getBody().getNumAddresses(),
            "<br>".join(sorted(rs)), callers[:120], callees[:120]))
        println("[txstudy2] done %s %s" % (k, f.getName()))
finally:
    ifc.dispose()

with open(os.path.join(OUT, "index2.md"), "w", encoding="utf-8") as fh:
    fh.write("\n".join(index) + "\n\n# 数据地址 xref 汇总\n\n")
    for v, fns in data_hit_summary:
        fh.write("## 0x%X (%d funcs)\n" % (v, len(fns)))
        for entry, (cnt, f, rtype) in sorted(fns.items(), key=lambda kv: -kv[1][0]):
            fh.write("- %s %s x%d %s\n" % (entry, f.getName() if f else "?", cnt, rtype))
        fh.write("\n")
println("[txstudy2] COMPLETE")
