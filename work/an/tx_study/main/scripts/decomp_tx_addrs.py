# @runtime PyGhidra
# MAIN 固件 TX 键控链反编译:目标函数 + RAM 标量引用扫描 + caller/callee 一层
import os, re
from ghidra.app.decompiler import DecompInterface
from ghidra.program.model.scalar import Scalar

OUT = r"work/an/tx_study/main"
DEC = os.path.join(OUT, "decomp")
os.makedirs(DEC, exist_ok=True)

FUNCS = [0xFFED6966, 0xFFF579C0, 0xFFF5836E]          # E8入队 / E8开启分支 / 播放菜单+键控原因
SCALARS = {0x17B54, 0x8013C5, 0x801324, 0x822D62, 0x8C02B}  # TX原因/VOICE_PTT/TX_SEQ/TX_ACCEPTED/SEND_A端口
MAX_PER_SCALAR = 16   # 每个标量最多反编译多少个引用函数
MAX_CALLER_DECOMP = 24

af = currentProgram.getAddressFactory().getDefaultAddressSpace()
fm = currentProgram.getFunctionManager()
listing = currentProgram.getListing()

def to_addr(v):
    return af.getAddress("%x" % v)

def sanitize(s):
    return re.sub(r"[^A-Za-z0-9_.+-]", "_", s)

# ---- Pass 1: 标量引用扫描(全库指令操作数) ----
scalar_hits = {v: {} for v in SCALARS}   # value -> {func_entry: count}
n_ins = 0
for ins in listing.getInstructions(True):
    n_ins += 1
    if monitor.isCancelled():
        break
    ops = []
    for i in range(4):
        try:
            ops.extend(ins.getOpObjects(i))
        except Exception:
            pass
    vals = set()
    for op in ops:
        if isinstance(op, Scalar):
            vals.add(op.getUnsignedValue())
    if not vals & SCALARS:
        continue
    f = fm.getFunctionContaining(ins.getAddress())
    key = str(f.getEntryPoint()) if f else "nofunc@" + str(ins.getAddress())
    for v in (vals & SCALARS):
        d = scalar_hits[v].setdefault(key, [0, f.getName() if f else "?"])
        d[0] += 1
println("[txstudy] scanned %d instructions" % n_ins)
for v in sorted(scalar_hits):
    println("[txstudy] scalar 0x%X -> %d functions" % (v, len(scalar_hits[v])))

# ---- Pass 2: 组装反编译集 ----
targets = {}   # entry_str -> (Function, reasons set)
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
        add_target(f, "core")
        for c in f.getCallingFunctions(monitor):
            add_target(c, "caller-of-%x" % v)
        for c in f.getCalledFunctions(monitor):
            add_target(c, "callee-of-%x" % v)

for v in sorted(scalar_hits):
    ranked = sorted(scalar_hits[v].items(), key=lambda kv: -kv[1][0])[:MAX_PER_SCALAR]
    for entry, (cnt, name) in ranked:
        f = fm.getFunctionAt(to_addr(int(entry, 16)))
        if f is None:
            f = fm.getFunctionContaining(to_addr(int(entry, 16)))
        add_target(f, "ref-0x%X(%d)" % (v, cnt))

# caller 的 caller(一层,限制数量)——追分发器上溯
extra = 0
for k, (f, rs) in list(targets.items()):
    if extra >= MAX_CALLER_DECOMP:
        break
    if any(r.startswith("core") for r in rs) or any(r.startswith("caller-of") for r in rs):
        for c in f.getCallingFunctions(monitor):
            if str(c.getEntryPoint()) not in targets:
                add_target(c, "caller2-of-%s" % str(f.getEntryPoint()))
                extra += 1
                if extra >= MAX_CALLER_DECOMP:
                    break
println("[txstudy] decompile set: %d functions" % len(targets))

# ---- Pass 3: 反编译 ----
ifc = DecompInterface()
ifc.openProgram(currentProgram)
index = ["# MAIN TX 键控链反编译索引\n",
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
        println("[txstudy] done %s %s" % (k, f.getName()))
finally:
    ifc.dispose()

with open(os.path.join(OUT, "index.md"), "w", encoding="utf-8") as fh:
    fh.write("\n".join(index) + "\n")

# 标量命中统计全文落盘(供后续按需二次反编译)
with open(os.path.join(OUT, "scalar-hits.md"), "w", encoding="utf-8") as fh:
    fh.write("# RAM 标量引用统计(全部命中函数,含未反编译)\n\n")
    for v in sorted(scalar_hits):
        fh.write("## 0x%X\n\n" % v)
        for entry, (cnt, name) in sorted(scalar_hits[v].items(), key=lambda kv: -kv[1][0]):
            fh.write("- %s %s x%d\n" % (entry, name, cnt))
println("[txstudy] COMPLETE")
