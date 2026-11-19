# Ghidra postScript: given pool word addresses, find instructions referencing them.
#@category rev_ftx1
POOL_ADDRS = [
    0x2c0fa8, 0x2c0fb0, 0x2c0fb4, 0x2c0fb8,   # D-LEVEL, D-MARKER, D-COLOR, D-CONTRAST
    0x2c1058, 0x2c131c, 0x2c1550, 0x2c1554, 0x2c1640,
    0x2c1b48, 0x2c1b50, 0x2c1b54,             # LSB, CW-L, CW-U
    0x2c1c30, 0x2c1ccc,
]

def main():
    fm = currentProgram.getFunctionManager()
    rm = currentProgram.getReferenceManager()
    out = open(r"work\an\cwdec_export\pool_xrefs.tsv", "w")
    out.write("pool_addr\tfrom_addr\tfunction\n")
    for pa in POOL_ADDRS:
        for ref in rm.getReferencesTo(currentProgram.getAddressFactory().getAddress("%08x" % pa)):
            fn = fm.getFunctionContaining(ref.getFromAddress())
            out.write("%08x\t%s\t%s\n" % (pa, ref.getFromAddress(), fn.getName() if fn else "?"))
    out.close()
    println("pool_xrefs done")

main()
