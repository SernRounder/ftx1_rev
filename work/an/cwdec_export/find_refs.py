# Ghidra postScript: find functions whose decompiled body contains target constants.
#@category rev_ftx1
import ghidra.app.decompiler as dec
from ghidra.util.task import ConsoleTaskMonitor

TARGETS = {
    "str_CW_PITCH_abs": 0x606bfaf8,
    "str_CW_PITCH_off": 0x2bfaf8,
    "str_SETTING_abs": 0x606bfadc,
    "str_SEARCH_abs": 0x606bfaf0,
    "ui_mirror": 0x60935bb4,
    "view_struct": 0x60939942,
    "popup_hit_c61e0": 0x604c61e0,
    "popup_draw_3bd3c": 0x6043bd3c,
}

def main():
    program = currentProgram
    ifc = dec.DecompInterface()
    ifc.openProgram(program)
    fm = program.getFunctionManager()
    out = open(r"work\an\cwdec_export\constant_refs.tsv", "w")
    out.write("target\tfunc\tfunc_addr\n")
    monitor = ConsoleTaskMonitor()
    n = 0
    for fn in fm.getFunctions(True):
        n += 1
        if n % 250 == 0:
            monitor.setMessage("decompiled %d" % n)
        res = ifc.decompileFunction(fn, 20, monitor)
        if not res.decompileCompleted():
            continue
        text = res.getDecompiledFunction().getC()
        low = text.lower()
        for name, val in TARGETS.items():
            forms = ("%x" % val, "0x%x" % val, "%d" % val)
            if any(f in low for f in forms):
                out.write("%s\t%s\t%s\n" % (name, fn.getName(), fn.getEntryPoint()))
        # also dump the CW PITCH referencing function bodies for reading
    out.close()
    ifc.dispose()
    println("done over %d functions" % n)

main()
