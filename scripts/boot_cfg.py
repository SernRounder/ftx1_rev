# Recursive function explorer for RX firmware (recreated from prior session)
# args: outfile max_depth func_limit root1 [root2 ...]
from ghidra.app.util import PseudoDisassembler
from collections import deque
from pathlib import Path
args = getScriptArgs()
out = Path(str(args[0]))
max_depth = int(str(args[1]))
limit = int(str(args[2]))
roots = [int(str(x), 16) for x in args[3:]]
ps = PseudoDisassembler(currentProgram)
space = currentProgram.getAddressFactory().getDefaultAddressSpace()

def address(n):
    return space.getAddress('%08x' % n)

def fn(entry):
    stack = [entry]
    found = {}
    calls = []
    while stack and len(found) < 2400:
        pc = stack.pop()
        if pc in found or not 0xffe80000 <= pc < 0xfff87dc2:
            continue
        a = address(pc)
        try:
            i = ps.disassemble(a)
        except Exception:
            continue
        if i is None:
            continue
        typ = i.getFlowType()
        targets = [t.getUnsignedOffset() for t in i.getFlows()]
        dest = ' '.join('%08x' % t for t in targets)
        found[pc] = '%08x %s%s' % (pc, str(i), '  -> ' + dest if dest else '')
        if typ.isCall():
            calls.extend((pc, t) for t in targets)
        elif typ.isJump():
            stack.extend(targets)
        if typ.hasFallthrough():
            stack.append(pc + i.getLength())
    return found, calls

q = deque((0, p) for p in roots)
done = set()
rows = []
while q and len(done) < limit:
    d, pc = q.popleft()
    if pc in done:
        continue
    done.add(pc)
    lines, calls = fn(pc)
    rows.append('FUNC %08x depth=%s instructions=%s calls=%s' % (pc, d, len(lines), ' '.join('%08x:%08x' % x for x in calls)))
    rows.extend(lines[a] for a in sorted(lines))
    if d < max_depth:
        q.extend((d + 1, target) for _, target in calls if target not in done)
out.write_text('\n'.join(rows), encoding='utf-8')
