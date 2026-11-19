# Ghidra postScript: dump full instruction listing with resolved literal loads.
#@category rev_ftx1
def main():
    listing = currentProgram.getListing()
    fm = currentProgram.getFunctionManager()
    out = open(r"work\an\cwdec_export\listing.tsv", "w")
    out.write("addr\tbytes\tmnemonic\toperands\tfunc\n")
    it = listing.getInstructions(True)
    n = 0
    for ins in it:
        fn = fm.getFunctionContaining(ins.getAddress())
        out.write("%s\t%s\t%s\t%s\t%s\n" % (
            ins.getAddress(), ins.getBytes().__str__().replace(" ", ""),
            ins.getMnemonicString(), ins.toString().split(" ", 1)[-1] if " " in ins.toString() else "",
            fn.getName() if fn else "?"))
        n += 1
    out.close()
    println("listing done: %d instructions" % n)

main()
