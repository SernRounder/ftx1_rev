# @runtime PyGhidra
# TX chain study postScript for FTX-1 MAIN firmware (RXv2).
# Usage (args after script name):
#   tx_study.py <out_dir> funcs <hexaddr>[,<hexaddr>...] [--callers=N] [--callees=N] [--name=SYMBOL]
#       Decompile functions at addresses; optionally expand caller/callee graph N levels.
#   tx_study.py <out_dir> datarefs <spec>[,<spec>...] [--decompile]
#       spec = hexaddr | hexaddr-hexaddr (range). Full instruction sweep for scalar operands
#       equal to addr (or in range). Reports function per hit. --decompile also decompiles those.
#   tx_study.py <out_dir> disasm <hexstart> <hexend>
#       Dump disassembly range to out/disasm_<start>_<end>.txt
#   tx_study.py <out_dir> findstr <substr>
#       Find defined strings containing substr; list referencing functions.
#   tx_study.py <out_dir> rename <hexaddr>=<name>[,<hexaddr>=<name>...]
#       Rename functions (persisted in project).
#   tx_study.py <out_dir> taskinfo <hexaddr>
#       Dump nearby data (T_CTSK-like structures) around address.
import os
import re
import sys

from ghidra.app.decompiler import DecompInterface
from ghidra.program.model.address import AddressSet

ADDRFMT = lambda a: "%08x" % a.getOffset()

def sanitize(s):
    return re.sub(r"[^A-Za-z0-9_.+-]", "_", s)

def parse_int(tok):
    tok = tok.strip()
    if tok.lower().startswith("0x"):
        return int(tok, 16)
    return int(tok, 16)  # default hex without 0x

class Ctx(object):
    def __init__(self, out_dir):
        self.out = out_dir
        self.decomp_dir = os.path.join(out_dir, "decomp")
        if not os.path.isdir(self.decomp_dir):
            os.makedirs(self.decomp_dir)
        self.ifc = DecompInterface()
        self.ifc.openProgram(currentProgram)
        self.fm = currentProgram.getFunctionManager()
        self.rm = currentProgram.getReferenceManager()
        self.listing = currentProgram.getListing()
        self.af = currentProgram.getAddressFactory()

    def addr(self, off):
        return self.af.getAddress("%08x" % off)

    def decompile(self, fn, reason=""):
        ep = fn.getEntryPoint()
        name = fn.getName()
        path = os.path.join(self.decomp_dir, "%s_%s.c" % (ADDRFMT(ep), sanitize(name)))
        if os.path.exists(path):
            return path
        try:
            res = self.ifc.decompileFunction(fn, 120, monitor)
            if res.decompileCompleted() and res.getDecompiledFunction():
                c = res.getDecompiledFunction().getC()
            else:
                c = "// DECOMPILE FAILED: %s\n" % res.getErrorMessage()
        except Exception as e:  # noqa
            c = "// DECOMPILE EXCEPTION: %s\n" % e
        with open(path, "w", encoding="utf-8", errors="replace") as f:
            f.write("// addr=%s name=%s size=%d reason=%s\n\n" % (
                ADDRFMT(ep), name, fn.getBody().getNumAddresses(), reason))
            f.write(c)
        return path

    def fn_at(self, off):
        return self.fm.getFunctionAt(self.addr(off)) or self.fm.getFunctionContaining(self.addr(off))

    def callers(self, fn):
        return list(fn.getCallingFunctions(monitor))

    def callees(self, fn):
        return list(fn.getCalledFunctions(monitor))


def cmd_funcs(ctx, addrs, opt_callers, opt_callees, opt_name):
    edges = []
    seen = set()
    frontier = []
    for a in addrs:
        fn = ctx.fn_at(a)
        if fn is None:
            println("[tx] no function at %08x" % a)
            continue
        frontier.append((fn, 0, "root"))
    while frontier:
        fn, depth, why = frontier.pop()
        ep = fn.getEntryPoint().getOffset()
        if ep in seen:
            continue
        seen.add(ep)
        p = ctx.decompile(fn, why)
        println("[tx] decompiled %s %s -> %s (depth=%d %s)" % (ADDRFMT(fn.getEntryPoint()), fn.getName(), p, depth, why))
        if depth < opt_callers:
            for c in ctx.callers(fn):
                edges.append((ADDRFMT(c.getEntryPoint()), c.getName(), "calls", ADDRFMT(fn.getEntryPoint()), fn.getName()))
                frontier.append((c, depth + 1, "caller of %s@%s" % (fn.getName(), ADDRFMT(fn.getEntryPoint()))))
        if depth < opt_callees:
            for c in ctx.callees(fn):
                edges.append((ADDRFMT(fn.getEntryPoint()), fn.getName(), "calls", ADDRFMT(c.getEntryPoint()), c.getName()))
                frontier.append((c, depth + 1, "callee of %s@%s" % (fn.getName(), ADDRFMT(fn.getEntryPoint()))))
    with open(os.path.join(ctx.out, "callgraph_edges.tsv"), "a", encoding="utf-8") as f:
        for e in edges:
            f.write("\t".join(e) + "\n")
    println("[tx] funcs done, %d functions" % len(seen))


def scalar_refs_sweep(ctx, targets):
    """targets: list of (lo, hi). Returns list of (insn_addr, func, value, mnemonic)."""
    hits = []
    it = ctx.listing.getInstructions(True)
    n = 0
    while it.hasNext():
        insn = it.next()
        n += 1
        if (n % 100000) == 0:
            println("[tx] sweep %d insns..." % n)
        found = None
        nops = insn.getNumOperands()
        for oi in range(nops):
            for o in insn.getOpObjects(oi):
                if o is None:
                    continue
                cn = o.getClass().getName()
                if "Scalar" in cn:
                    v = o.getUnsignedValue() if hasattr(o, "getUnsignedValue") else o.getValue()
                    for (lo, hi) in targets:
                        if lo <= v <= hi:
                            found = v
                            break
                if found is not None:
                    break
            if found is not None:
                break
        if found is not None:
            a = insn.getAddress()
            fn = ctx.fm.getFunctionContaining(a)
            fname = fn.getName() if fn else "<none>"
            fep = ADDRFMT(fn.getEntryPoint()) if fn else "-"
            hits.append((ADDRFMT(a), fep, fname, found, insn.getMnemonicString(), str(insn)))
    println("[tx] sweep done: %d instructions scanned, %d hits" % (n, len(hits)))
    return hits


def cmd_datarefs(ctx, specs, do_decompile):
    targets = []
    for s in specs:
        if "-" in s:
            lo, hi = s.split("-")
            targets.append((parse_int(lo), parse_int(hi)))
        else:
            v = parse_int(s)
            targets.append((v, v))
    hits = scalar_refs_sweep(ctx, targets)
    outp = os.path.join(ctx.out, "datarefs_%s.tsv" % "_".join(sanitize(s) for s in specs))
    with open(outp, "w", encoding="utf-8") as f:
        f.write("insn_addr\tfunc_addr\tfunc_name\tvalue\tmnemonic\ttext\n")
        for h in hits:
            f.write("\t".join(str(x) for x in h) + "\n")
    println("[tx] datarefs written to %s" % outp)
    if do_decompile:
        fns = {}
        for h in hits:
            if h[1] != "-":
                fns[h[1]] = h[2]
        for fep, fname in sorted(fns.items()):
            fn = ctx.fm.getFunctionAt(ctx.addr(int(fep, 16)))
            if fn is not None:
                ctx.decompile(fn, "refs target data")
                println("[tx] decompiled %s %s" % (fep, fname))
    # Also try real references (if Ghidra created them, e.g. pointer tables in loaded space)
    for (lo, hi) in targets:
        try:
            for a_off in range(lo, hi + 1):
                pass
        except Exception:
            pass
    refout = []
    for (lo, hi) in targets:
        a = lo
        while a <= hi:
            try:
                aa = ctx.addr(a)
            except Exception:
                break
            for ref in ctx.rm.getReferencesTo(aa):
                frm = ref.getFromAddress()
                fn = ctx.fm.getFunctionContaining(frm)
                refout.append((ADDRFMT(frm), ADDRFMT(fn.getEntryPoint()) if fn else "-", fn.getName() if fn else "<none>",
                               str(ref.getReferenceType()), str(ref)))
            a += 1
    if refout:
        rp = os.path.join(ctx.out, "datarefs_real_%s.tsv" % "_".join(sanitize(s) for s in specs))
        with open(rp, "w", encoding="utf-8") as f:
            f.write("from\tfunc_addr\tfunc_name\ttype\tref\n")
            for r in refout:
                f.write("\t".join(r) + "\n")
        println("[tx] real refs: %d -> %s" % (len(refout), rp))


def cmd_disasm(ctx, start, end):
    outp = os.path.join(ctx.out, "disasm_%08x_%08x.txt" % (start, end))
    it = ctx.listing.getInstructions(ctx.addr(start), True)
    with open(outp, "w", encoding="utf-8", errors="replace") as f:
        while it.hasNext():
            insn = it.next()
            if insn.getAddress().getOffset() > end:
                break
            f.write("%s\t%s\t%s\n" % (ADDRFMT(insn.getAddress()), str(insn), insn.getMnemonicString()))
    println("[tx] disasm written %s" % outp)


def cmd_findstr(ctx, needle):
    outp = os.path.join(ctx.out, "findstr_%s.tsv" % sanitize(needle))
    rows = []
    it = ctx.listing.getDefinedData(True)
    while it.hasNext():
        d = it.next()
        try:
            if d.hasStringValue():
                v = str(d.getValue())
                if needle.lower() in v.lower():
                    a = d.getAddress()
                    fns = set()
                    for ref in ctx.rm.getReferencesTo(a):
                        fn = ctx.fm.getFunctionContaining(ref.getFromAddress())
                        if fn:
                            fns.add((ADDRFMT(fn.getEntryPoint()), fn.getName()))
                    rows.append((ADDRFMT(a), v, ";".join("%s %s" % x for x in sorted(fns))))
        except Exception:
            pass
    with open(outp, "w", encoding="utf-8") as f:
        f.write("addr\tvalue\treferenced_by\n")
        for r in rows:
            f.write("\t".join(x.replace("\t", " ") for x in r) + "\n")
    println("[tx] findstr: %d rows -> %s" % (len(rows), outp))


def cmd_rename(ctx, pairs):
    for a, name in pairs:
        fn = ctx.fm.getFunctionAt(ctx.addr(a))
        if fn is None:
            println("[tx] rename: no fn at %08x" % a)
            continue
        try:
            fn.setName(name, ghidra.program.model.symbol.SourceType.USER_DEFINED)
            println("[tx] renamed %08x -> %s" % (a, name))
        except Exception as e:  # noqa
            println("[tx] rename FAILED %08x: %s" % (a, e))


def cmd_taskinfo(ctx, start, length):
    outp = os.path.join(ctx.out, "data_%08x_%x.txt" % (start, length))
    a = ctx.addr(start)
    mem = currentProgram.getMemory()
    bs = bytearray()
    try:
        for i in range(length):
            bs.append(mem.getByte(a.add(i)) & 0xFF)
    except Exception as e:  # noqa
        println("[tx] data read err %s" % e)
    with open(outp, "wb") as f:
        f.write(bytes(bs))
    # also listing representation
    with open(outp + ".txt", "w", encoding="utf-8", errors="replace") as f:
        it = ctx.listing.getCodeUnits(ctx.addr(start), True)
        n = 0
        while it.hasNext() and n < length:
            cu = it.next()
            f.write("%s\t%s\n" % (ADDRFMT(cu.getAddress()), str(cu)))
            n += cu.getLength()
    println("[tx] data dump -> %s" % outp)


def main():
    args = getScriptArgs()
    if len(args) < 2:
        println("[tx] usage: tx_study.py <out_dir> <mode> <args...>")
        return
    out_dir = args[0]
    mode = args[1]
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    ctx = Ctx(out_dir)
    try:
        if mode == "funcs":
            addrs = [parse_int(x) for x in args[2].split(",")]
            oc, od, name = 0, 0, None
            for a in args[3:]:
                if a.startswith("--callers="):
                    oc = int(a.split("=")[1])
                elif a.startswith("--callees="):
                    od = int(a.split("=")[1])
                elif a.startswith("--name="):
                    name = a.split("=", 1)[1]
            cmd_funcs(ctx, addrs, oc, od, name)
        elif mode == "datarefs":
            specs = args[2].split(",")
            do_dec = "--decompile" in args
            cmd_datarefs(ctx, specs, do_dec)
        elif mode == "disasm":
            cmd_disasm(ctx, parse_int(args[2]), parse_int(args[3]))
        elif mode == "findstr":
            cmd_findstr(ctx, args[2])
        elif mode == "rename":
            pairs = []
            for p in args[2].split(","):
                a, n = p.split("=")
                pairs.append((parse_int(a), n))
            cmd_rename(ctx, pairs)
        elif mode == "taskinfo":
            cmd_taskinfo(ctx, parse_int(args[2]), int(args[3], 16))
        else:
            println("[tx] unknown mode %s" % mode)
    finally:
        ctx.ifc.dispose()
        # save renames
        try:
            currentProgram.save("tx_study", monitor)
        except Exception:  # noqa
            pass


main()
