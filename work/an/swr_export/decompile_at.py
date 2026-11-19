# Ghidra postScript: decompile functions containing given addresses, plus
# callers that reference a set of data addresses. Args (space separated):
#   <out_dir> <program:addr,addr,...> [ref:addr,addr,...] [caller_depth]
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor
import os, sys

args = getScriptArgs()
out_dir = args[0]
targets = {}
for spec in args[1].split(";"):
    name, addrs = spec.split(":")
    targets[name] = [int(a, 16) for a in addrs.split(",")]
ref_targets = {}
if len(args) > 2 and args[2].startswith("ref:"):
    ref_targets["main"] = [int(a, 16) for a in args[2][4:].split(",")]
depth = int(args[3]) if len(args) > 3 else 0

program = currentProgram
af = program.getAddressFactory().getDefaultAddressSpace()
fm = program.getFunctionManager()
rm = program.getReferenceManager()
decomp = DecompInterface()
decomp.openProgram(program)
monitor = ConsoleTaskMonitor()

os.makedirs(os.path.join(out_dir, "decompiled"), exist_ok=True)
seen = set()
queue = []

for name, addrs in targets.items():
    for a in addrs:
        addr = af.getAddress(a)
        fn = fm.getFunctionContaining(addr)
        if fn is None:
            fn = fm.getFunctionAt(addr)
        if fn is not None:
            key = fn.getEntryPoint().toString()
            if key not in seen:
                seen.add(key)
                queue.append((fn, 0, "direct:%s@%x" % (name, a)))
        else:
            print("[decompile_at] no function contains %x" % a)

for name, addrs in ref_targets.items():
    for a in addrs:
        addr = af.getAddress(a)
        for ref in rm.getReferencesTo(addr):
            src = ref.getFromAddress()
            fn = fm.getFunctionContaining(src)
            if fn is not None:
                key = fn.getEntryPoint().toString()
                if key not in seen:
                    seen.add(key)
                    queue.append((fn, 0, "ref:%s@%x" % (name, a)))

out = []
done = set()
while queue:
    fn, lvl, why = queue.pop(0)
    if fn.getEntryPoint().toString() in done:
        continue
    done.add(fn.getEntryPoint().toString())
    res = decomp.decompileFunction(fn, 90, monitor)
    text = res.getDecompiledFunction().getC() if res.decompileCompleted() else "// DECOMPILE FAILED"
    path = os.path.join(out_dir, "decompiled", "%s_%s.c" % (fn.getEntryPoint(), fn.getName()))
    with open(path, "w", encoding="utf-8") as f:
        f.write("// addr=%s why=%s callers_depth=%d\n" % (fn.getEntryPoint(), why, lvl))
        f.write(text)
    out.append("%s %s (%s)" % (fn.getEntryPoint(), fn.getName(), why))
    if lvl < depth:
        for caller in fn.getCallingFunctions(monitor):
            if caller.getEntryPoint().toString() not in done:
                queue.append((caller, lvl + 1, "caller-of:%s" % fn.getName()))

with open(os.path.join(out_dir, "decompile_at.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("[decompile_at] wrote %d functions" % len(out))
