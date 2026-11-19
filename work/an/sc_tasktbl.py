import struct

path = r"work/dec/FTX-1_IFDSP_V0110.SFL.bin"
data = open(path, "rb").read()

names = [(0x28d10, "C4Uart"), (0x28d1c, "Thread_Ipc"), (0x28d28, "Thread_Main"),
         (0x28d34, "Rx_Audio"), (0x28d40, "Rx_C4FM"), (0x28d48, "Tx_C4FM"),
         (0x28d50, "Composite_SPI"), (0x28d60, "Rx_Path"), (0x28d68, "Tx_Path")]
deltas = [names[i+1][0] - names[i][0] for i in range(len(names)-1)]
print("expected deltas:", [hex(d) for d in deltas])

# scan all alignments for word runs matching deltas (consecutive words)
hits = []
for o in range(0, len(data) - 40):
    ws = []
    ok = True
    for i in range(9):
        (w,) = struct.unpack_from("<I", data, o + 4*i)
        ws.append(w)
    for i in range(8):
        if ws[i+1] - ws[i] != deltas[i]:
            ok = False
            break
    if ok:
        base = ws[0] - names[0][0]
        hits.append((o, ws, base))
        print(f"TABLE at file {o:#x}: base = {base:#010x}")
        for i, (fo, n) in enumerate(names):
            print(f"   {n:<15} -> {ws[i]:#010x}  (implies base {ws[i]-fo:#010x})")

# also: same deltas but entries interleaved with other fields (stride 8: name,func pairs)
print("\nstride-8 search (name @ even slots):")
for o in range(0, len(data) - 72):
    ws = [struct.unpack_from("<I", data, o + 8*i)[0] for i in range(9)]
    if all(ws[i+1] - ws[i] == deltas[i] for i in range(8)):
        base = ws[0] - names[0][0]
        print(f"TABLE(stride8) at {o:#x}: base = {base:#010x}")
        # dump surroundings
        for i in range(9):
            f = struct.unpack_from("<I", data, o + 8*i + 4)[0]
            print(f"   {names[i][1]:<15} name->{ws[i]:#010x} other->{f:#010x} (file {f-base:#x} if code)")

# and stride 12 / 16 variants
for stride in (12, 16):
    for o in range(0, len(data) - stride*9):
        ws = [struct.unpack_from("<I", data, o + stride*i)[0] for i in range(9)]
        if all(ws[i+1] - ws[i] == deltas[i] for i in range(8)):
            print(f"TABLE(stride{stride}) at {o:#x}: base = {ws[0]-names[0][0]:#010x}")
