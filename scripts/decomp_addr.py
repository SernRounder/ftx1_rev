# Decompile functions at/containing given addresses; also resolve callers.
# args: outfile addr1 [addr2 ...]
from ghidra.app.decompiler import DecompInterface
from ghidra.app.cmd.function import CreateFunctionCmd
from ghidra.app.cmd.disassemble import DisassembleCommand
from ghidra.program.model.symbol import RefType
from pathlib import Path

args = getScriptArgs()
out = Path(str(args[0]))
addrs = [int(str(x), 16) for x in args[1:]]
space = currentProgram.getAddressFactory().getDefaultAddressSpace()
fm = currentProgram.getFunctionManager()
listing = currentProgram.getListing()

def addr(a):
    return space.getAddress('%08x' % a)

def ensure_func(a):
    p = addr(a)
    f = fm.getFunctionContaining(p)
    if f is None:
        DisassembleCommand(p, None, True).applyTo(currentProgram, monitor)
        f = fm.getFunctionContaining(p)
    if f is None:
        CreateFunctionCmd(p).applyTo(currentProgram, monitor)
        f = fm.getFunctionContaining(p)
    return f

ifc = DecompInterface()
ifc.openProgram(currentProgram)
chunks = []
seen = set()
for a in addrs:
    f = ensure_func(a)
    if f is None or f.getEntryPoint() in seen:
        continue
    seen.add(f.getEntryPoint())
    res = ifc.decompileFunction(f, 90, monitor)
    body = res.getDecompiledFunction().getC() if res.decompileCompleted() else '// decompile failed'
    callers = []
    for ref in currentProgram.getReferenceManager().getReferencesTo(f.getEntryPoint()):
        cf = fm.getFunctionContaining(ref.getFromAddress())
        callers.append('%s @ %s' % (cf.getEntryPoint() if cf else '?', ref.getFromAddress()))
    chunks.append('// ==== %s  entry=%s  callers=%d ====\n// %s\n%s\n' % (
        f.getName(), f.getEntryPoint(), len(callers), ' | '.join(callers[:24]), body))
out.write_text('\n'.join(chunks), encoding='utf-8')
