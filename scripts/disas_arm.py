# Raw-disassemble address ranges: outfile [--a32] start1 end1 [start2 end2 ...]
from capstone import CS_ARCH_ARM, CS_MODE_ARM, Cs
from ghidra.app.util import PseudoDisassembler
from pathlib import Path

args = [str(arg) for arg in getScriptArgs()]
out = Path(str(args[0]))
force_a32 = len(args) > 1 and args[1] == "--a32"
if force_a32:
    args.pop(1)
ps = PseudoDisassembler(currentProgram)
space = currentProgram.getAddressFactory().getDefaultAddressSpace()
mem = currentProgram.getMemory()
a32 = Cs(CS_ARCH_ARM, CS_MODE_ARM) if force_a32 else None

def read(a, n):
    start = space.getAddress(f'{a:08x}')
    return bytes(mem.getByte(start.add(i)) & 0xff for i in range(n))

parts = []
for i in range(1, len(args), 2):
    a = int(str(args[i]), 16)
    b = int(str(args[i+1]), 16)
    lines = []
    while a < b:
        if a32 is not None:
            raw = read(a, 4)
            decoded = next(a32.disasm(raw, a, count=1), None)
            assembly = f'{decoded.mnemonic} {decoded.op_str}' if decoded else '??'
            lines.append(f'{a:08x} {raw.hex(" "):11s} {assembly}')
            a += 4
            continue
        ins = ps.disassemble(space.getAddress(f'{a:08x}'))
        if ins is None:
            lines.append('%08x ?? %s' % (a, read(a, 4).hex()))
            a += 4
            continue
        flows = ','.join(str(f) for f in ins.getFlows())
        lines.append('%08x %-11s %-40s %s' % (a, read(a, ins.getLength()).hex(' '), str(ins), flows))
        a += ins.getLength()
    parts.append('\n'.join(lines))
out.write_text('\n\n'.join(parts), encoding='utf-8')
