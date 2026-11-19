# @runtime PyGhidra
# Dump disassembly for a raw address range with literal annotations.
# Usage: -postScript tx_dis.py <outfile> <start_hex> <end_hex>
import os

args = getScriptArgs()
OUT = args[0]
START = int(args[1], 16)
END = int(args[2], 16)

fm = currentProgram.getFunctionManager()
af = currentProgram.getAddressFactory().getDefaultAddressSpace()
listing = currentProgram.getListing()

lines = []
a = af.getAddress(START)
it = listing.getInstructions(a, True)
for ins in it:
    ia = int(ins.getAddress().getOffset())
    if ia > END:
        break
    fn = fm.getFunctionContaining(ins.getAddress())
    fname = fn.getName() if fn else ""
    # annotate literal loads
    ann = ""
    for ref in ins.getReferencesFrom():
        to = ref.getToAddress()
        if to is None:
            continue
        d = listing.getDataAt(to)
        if d is not None and d.getValue() is not None:
            try:
                v = int(d.getValue().getValue() if hasattr(d.getValue(), "getValue") else d.getValue())
                ann += "  ; [0x%06x]=0x%08X" % (int(to.getOffset()), v & 0xFFFFFFFF)
            except Exception:
                pass
            if d.hasStringValue():
                ann += " STR"
    lines.append("%06x  %-40s %s%s" % (ia, str(ins), fname, ann))

with open(OUT, "w", encoding="utf-8") as fh:
    fh.write("\n".join(lines) + "\n")
println("[dis] %d instructions %06x-%06x" % (len(lines), START, END))
