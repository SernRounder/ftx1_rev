# Print all references TO given addresses (hex strings). args: outfile addr1 [addr2 ...]
from pathlib import Path
args = getScriptArgs()
out = Path(str(args[0]))
space = currentProgram.getAddressFactory().getDefaultAddressSpace()
fm = currentProgram.getFunctionManager()
rm = currentProgram.getReferenceManager()
lines = []
for i in range(1, len(args)):
    a = space.getAddress(args[i])
    refs = rm.getReferencesTo(a)
    lines.append('=== refs to %s ===' % a)
    for r in refs:
        f = fm.getFunctionContaining(r.getFromAddress())
        lines.append('  %s  from %s  in %s  type=%s' % (
            r.getReferenceType(), r.getFromAddress(), f.getEntryPoint() if f else '?', r.getReferenceType()))
    # also code units that contain the address as operand (scalar) - search listing
    cu = currentProgram.getListing().getCodeUnitAt(a)
    if cu:
        lines.append('  unit at %s : %s' % (a, cu.toString()))
out.write_text('\n'.join(lines), encoding='utf-8')
print(lines[:60])
