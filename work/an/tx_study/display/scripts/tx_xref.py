# @runtime PyGhidra
# Dump references TO given addresses (code+data), and disassembly around an address.
# Usage: -postScript tx_xref.py <outfile> <mode:refs|dis|both> <addr> [<addr>...]
import os

args = getScriptArgs()
OUT = args[0]
MODE = args[1]
ADDRS = [int(a, 16) for a in args[2:]]

fm = currentProgram.getFunctionManager()
af = currentProgram.getAddressFactory().getDefaultAddressSpace()
listing = currentProgram.getListing()
rm = currentProgram.getReferenceManager()

lines = []
for t in ADDRS:
    a = af.getAddress(t)
    if MODE in ("refs", "both"):
        lines.append("=== refs to 0x%06x ===" % t)
        for ref in rm.getReferencesTo(a):
            frm = ref.getFromAddress()
            f = fm.getFunctionContaining(frm)
            fname = f.getName() if f else "?"
            # include the instruction text
            ins = listing.getInstructionAt(frm)
            txt = str(ins) if ins else ""
            lines.append("  %s from %06x in %s : %s" % (ref.getReferenceType(), int(frm.getOffset()), fname, txt))
        # also data xrefs from anywhere in program (pointers stored in data)
        lines.append("=== mem refs to 0x%06x (scan) ===" % t)
        try:
            it = listing.getDefinedData(True)
            for d in it:
                try:
                    for r in d.getReferencesFrom():
                        if int(r.getToAddress().getOffset()) == t:
                            lines.append("  DATA at %06x -> target" % int(d.getAddress().getOffset()))
                except Exception:
                    pass
        except Exception as e:
            lines.append("  scan error %s" % e)
    if MODE in ("dis", "both"):
        lines.append("=== disasm around 0x%06x ===" % t)
        start = af.getAddress(max(0, t - 0x40))
        end = af.getAddress(t + 0x100)
        ins_iter = listing.getInstructions(start, True)
        for ins in ins_iter:
            ia = ins.getAddress()
            if int(ia.getOffset()) > t + 0x100:
                break
            prefix = ">>" if int(ia.getOffset()) == t else "  "
            lines.append("%s %06x  %s" % (prefix, int(ia.getOffset()), str(ins)))

with open(OUT, "a", encoding="utf-8") as fh:
    fh.write("\n".join(lines) + "\n")
println("[xref] wrote %d lines" % len(lines))
