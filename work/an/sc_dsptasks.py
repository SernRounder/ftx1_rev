import struct

data = open(r"work/dec/FTX-1_IFDSP_V0110.SFL.bin", "rb").read()
S = 0x1DE178  # file -> DSP RAM

def resolve(w):
    """interpret blob word as DSP pointer"""
    if 0x200000 <= w < 0x23A548:
        f = w - 0x200000 + 0x21e88
        s = data[f:f + 16].split(b"\x00")[0]
        if len(s) >= 2 and all(32 <= b < 127 for b in s):
            return f"-> blob file {f:#x} str {s.decode()!r}"
        return f"-> blob file {f:#x}"
    return ""

sites = {
    0x29bc4: "Rx_Audio",
    0x29bd8: "Rx_C4FM",
    0x29ec0: "Tx_C4FM",
    0x2a2bc: "Composite_SPI",
    0x2a420: "Rx_Path",
    0x2a438: "Tx_Path",
    0x29660: "Thread_Main",
    0x295f4: "Thread_Ipc",
    0x2a848: "C4Uart",
}
for site, name in sites.items():
    print(f"===== {name} @file {site:#x} (dsp {site+S:#x}) =====")
    lo = site - 0x20
    hi = site + 0x18
    for i in range(lo, hi, 4):
        w = struct.unpack_from("<I", data, i)[0]
        r = resolve(w)
        mark = " <<<" if i == site else ""
        print(f"  {i:#08x} (dsp {i+S:#x}): {w:#010x} {r}{mark}")
    print()
