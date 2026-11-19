# List functions overlapping given address ranges (hex strings); args: outfile lo1 hi1 [lo2 hi2 ...]
from pathlib import Path
args = getScriptArgs()
out = Path(str(args[0]))
space = currentProgram.getAddressFactory().getDefaultAddressSpace()
fm = currentProgram.getFunctionManager()
rows = []
for i in range(1, len(args), 2):
    lo = space.getAddress(args[i])
    hi = space.getAddress(args[i+1])
    for f in fm.getFunctions(lo, True):
        if f.getEntryPoint() > hi:
            break
        if f.getBody().getMaxAddress() >= lo:
            rows.append('%s entry=%s size=%d' % (f.getName(), f.getEntryPoint(), f.getBody().getNumAddresses()))
out.write_text('\n'.join(rows), encoding='utf-8')
print(rows[:40])
