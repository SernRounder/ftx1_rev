# @runtime PyGhidra
# 第四批:wrapper 群区域强制反汇编 + 邻接函数反编译
import os, re
from ghidra.app.decompiler import DecompInterface
from ghidra.app.cmd.disassemble import DisassembleCommand
from ghidra.program.model.address import AddressSet

OUT = r"work/an/tx_study/main"
DEC = os.path.join(OUT, "decomp")
af = currentProgram.getAddressFactory().getDefaultAddressSpace()
fm = currentProgram.getFunctionManager()
listing = currentProgram.getListing()

def to_addr(v):
    return af.getAddress("%x" % v)

# 1) 强制反汇编 wrapper 区(含未识别间隙)
start, end = to_addr(0xFFEF7920), to_addr(0xFFEF7A60)
cmd = DisassembleCommand(AddressSet(start, end), None, True)
cmd.applyTo(currentProgram, monitor)
lines = []
it = listing.getInstructions(start, True)
a = start
while a is not None and a.getOffset() <= end.getOffset():
    ins = listing.getInstructionAt(a)
    if ins is None:
        lines.append("%s  ??  %s" % (a, listing.getCodeUnitAt(a)))
        a = a.add(1)
        continue
    lines.append("%s  %s" % (a, ins.toString()))
    a = ins.getMaxAddress().add(1) if ins.getLength() else a.add(1)
with open(os.path.join(OUT, "wrapper-region-disasm.txt"), "w", encoding="utf-8", errors="replace") as fh:
    fh.write("\n".join(lines) + "\n")
println("[txstudy4] disasm %d lines" % len(lines))

# 2) 反编译邻接函数
FUNCS = [0xFFEF7803, 0xFFEF7920, 0xFFEF8010, 0xFFEF80A2, 0xFFEF8134, 0xFFEF81AA, 0xFFEF8220]
ifc = DecompInterface()
ifc.openProgram(currentProgram)
try:
    for v in FUNCS:
        f = fm.getFunctionAt(to_addr(v))
        if not f:
            println("[txstudy4] MISSING 0x%X" % v)
            continue
        res = ifc.decompileFunction(f, 120, monitor)
        code = res.getDecompiledFunction().getC() if (res.decompileCompleted() and res.getDecompiledFunction()) else "// FAILED"
        with open(os.path.join(DEC, "%s_%s.c" % (str(f.getEntryPoint()), re.sub(r"[^A-Za-z0-9_.+-]", "_", f.getName()))), "w", encoding="utf-8", errors="replace") as fh:
            fh.write("// addr=%s reason=core4\n\n%s\n" % (str(f.getEntryPoint()), code))
        println("[txstudy4] done 0x%X" % v)
finally:
    ifc.dispose()
println("[txstudy4] COMPLETE")
