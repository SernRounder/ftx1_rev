# @runtime PyGhidra
# Decompile target functions (+caller/callee expansion) for DISPLAY audio->DMAC CH3 study.
# Usage: -postScript tx_study.py <outdir> <hexaddr,hexaddr,...> [callee_depth] [caller_depth]
import os, re
from ghidra.app.decompiler import DecompInterface
from ghidra.app.cmd.function import CreateFunctionCmd

args = getScriptArgs()
OUT = args[0]
TARGETS = [int(a, 16) for a in args[1].split(",")]
CALLEE_D = int(args[2]) if len(args) > 2 else 0
CALLER_D = int(args[3]) if len(args) > 3 else 0

fm = currentProgram.getFunctionManager()
af = currentProgram.getAddressFactory().getDefaultAddressSpace()
listing = currentProgram.getListing()
rm = currentProgram.getReferenceManager()

def sanitize(s):
    return re.sub(r"[^A-Za-z0-9_.+-]", "_", s)

def fn_at(off):
    a = af.getAddress(off)
    f = fm.getFunctionAt(a)
    if f is None:
        f = fm.getFunctionContaining(a)
    return f

def ensure_fn(off):
    f = fn_at(off)
    if f is None or int(f.getEntryPoint().getOffset()) != off:
        cmd = CreateFunctionCmd(af.getAddress(off))
        cmd.applyTo(currentProgram, monitor)
        f = fn_at(off)
    return f

ifc = DecompInterface()
ifc.openProgram(currentProgram)

# BFS: entries are (ep, callee_depth_left, caller_depth_left)
queue = []
done = set()
for t in TARGETS:
    f = ensure_fn(t)
    if f is None:
        println("[tx] no func at %x" % t)
        continue
    ep = int(f.getEntryPoint().getOffset())
    if ep not in done:
        done.add(ep)
        queue.append((ep, CALLEE_D, CALLER_D))

results = {}   # ep -> (name, c_code, callers_str, callees_str, literals)
qi = 0
while qi < len(queue):
    ep, cd, pd = queue[qi]; qi += 1
    f = fn_at(ep)
    if f is None:
        continue
    name = f.getName()
    # callers / callees
    callers = []
    for c in f.getCallingFunctions(monitor):
        cep = int(c.getEntryPoint().getOffset())
        callers.append((cep, c.getName()))
    callees = []
    for c in f.getCalledFunctions(monitor):
        cep = int(c.getEntryPoint().getOffset())
        callees.append((cep, c.getName()))
    # literals (defined data referenced within function body)
    lits = []
    body = f.getBody()
    it = listing.getInstructions(body, True)
    for ins in it:
        for ref in ins.getReferencesFrom():
            t = ref.getToAddress()
            if t is None:
                continue
            d = listing.getDataAt(t)
            if d is not None and d.hasStringValue():
                lits.append("0x%s STR %r" % (t, str(d.getValue())[:80]))
            elif d is not None and d.getValue() is not None:
                try:
                    v = int(d.getValue().getValue() if hasattr(d.getValue(), "getValue") else d.getValue())
                except Exception:
                    continue
                lits.append("0x%s DAT 0x%08X" % (t, v & 0xFFFFFFFF))
    # decompile
    code = None
    try:
        res = ifc.decompileFunction(f, 120, monitor)
        if res.decompileCompleted() and res.getDecompiledFunction():
            code = res.getDecompiledFunction().getC()
    except Exception as e:
        code = "// decompile error: %s" % e
    results[ep] = (name, code, callers, callees, lits, int(f.getBody().getNumAddresses()))
    # expand
    if pd > 0:
        for cep, _ in callers:
            if cep not in done:
                done.add(cep); queue.append((cep, cd, pd - 1))
    if cd > 0:
        for cep, _ in callees:
            if cep not in done:
                done.add(cep); queue.append((cep, cd - 1, 0))

meta = []
for ep in sorted(results):
    name, code, callers, callees, lits, size = results[ep]
    fn = "%06x_%s.c" % (ep, sanitize(name))
    with open(os.path.join(OUT, fn), "w", encoding="utf-8", errors="replace") as fh:
        fh.write("// addr=0x%06x (runtime 0x%08x) name=%s size=%d\n" % (ep, ep + 0x60400000, name, size))
        fh.write("// callers: %s\n" % ", ".join("0x%06x:%s" % c for c in callers))
        fh.write("// callees: %s\n" % ", ".join("0x%06x:%s" % c for c in callees))
        fh.write("// literals:\n")
        for l in lits:
            fh.write("//   %s\n" % l)
        fh.write("\n" + (code or "// FAILED"))
    meta.append("0x%06x\t%s\tsize=%d\tcallers=%d\tcallees=%d\t%s" % (ep, name, size, len(callers), len(callees), fn))

with open(os.path.join(OUT, "_index.txt"), "a", encoding="utf-8") as fh:
    fh.write("\n".join(meta) + "\n")

println("[tx] exported %d functions to %s" % (len(results), OUT))
ifc.dispose()
