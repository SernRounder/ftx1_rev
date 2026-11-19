# Disassemble RX address ranges via PseudoDisassembler; args: outfile [start end]...
from ghidra.app.util import PseudoDisassembler
from pathlib import Path
args = getScriptArgs()
out = Path(str(args[0]))
ps = PseudoDisassembler(currentProgram)

def addr(a):
    return currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress('%08x' % a)

def dump(a, b):
    result = []
    while a < b:
        try:
            ins = ps.disassemble(addr(a))
        except Exception:
            ins = None
        if ins is None:
            result.append('%08x ??' % a)
            a += 1
            continue
        flows = ','.join(str(f) for f in ins.getFlows())
        result.append('%08x %-28s %-43s %s' % (a, bytes((x & 255 for x in ins.getBytes())).hex(' '), str(ins), flows))
        a += ins.getLength()
    return '\n'.join(result)

parts = []
for i in range(1, len(args), 2):
    a, b = map(lambda x: int(str(x), 16), args[i:i+2])
    parts.append(dump(a, b))
out.write_text('\n\n'.join(parts), encoding='utf-8')
