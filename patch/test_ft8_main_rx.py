"""PyGhidra post-script. Execute the packaged MAIN hooks in the RX emulator."""

import struct
import sys
import zlib
from pathlib import Path

from ghidra.app.emulator import EmulatorHelper


def main():
    source = Path(str(getSourceFile().getAbsolutePath())).parent
    sys.path.insert(0, str(source))
    from build_ft8_main import read_main, sfl_codec

    image = Path(str(getScriptArgs()[0])).read_bytes()
    assert int(image[0x200:0x220].split()[1]) == len(image)
    assert int(image[0x220:0x228], 16) == zlib.crc32(image[0x240:] + bytes.fromhex("8f93c635"))
    codec = sfl_codec()
    _, records = read_main(codec, image)
    stock_image = (source.parent / "work/fw/FTX-1_MAIN_V0113.SFL").read_bytes()
    _, stock = read_main(codec, stock_image)
    fixed = next(i for i, record in enumerate(records) if record[1] == 0xFFFFFF00)
    assert records[fixed:] == stock[-len(records[fixed:]):]

    assert all(valid for _, _, _, valid in records)
    memory = {address + offset: value for kind, address, data, valid in records
              if kind == "3" and valid for offset, value in enumerate(data)}
    assert bytes(memory[i] for i in range(0xFFE80059, 0xFFE8005D)) == bytes.fromhex("056ae901")
    assert bytes(memory[i] for i in range(0xFFF576BD, 0xFFF576C7)) == bytes.fromhex("390a0039000339650102")
    assert all(not 0xFFF88000 <= i < 0xFFFFFF00 for i in memory)
    cpu = EmulatorHelper(currentProgram)
    space = currentProgram.getAddressFactory().getDefaultAddressSpace()

    def address(value):
        return space.getAddress(f"{value:08x}")

    def write(location, data):
        cpu.writeMemory(address(location), bytes(data))

    def word(location, value):
        write(location, struct.pack("<I", value))

    def byte(location):
        return cpu.readMemoryByte(address(location)) & 0xff

    def call(entry, stop, arg=0, *, stack=0x6000):
        cpu.writeRegister("R0", stack)
        cpu.writeRegister("R1", arg)
        cpu.writeRegister(cpu.getPCRegister(), entry)
        word(stack, stop)
        for _ in range(2000):
            if cpu.getExecutionAddress() == address(stop):
                return
            pc = cpu.getExecutionAddress()
            assert cpu.step(monitor), f"{entry:#x} at {pc}: {cpu.getLastError()}"
        raise AssertionError(f"RX emulator did not return from {entry:#x}")

    def stock_return(location, value=0):
        write(location, (0x66, (value << 4) | 1, 0x02))

    # Use the packaged instructions for every patch, including the SWR timer
    # trampoline and the softkey dispatch chain in the repurposed stock code.
    write(0xFFE80000, (memory.get(i, 0xff) for i in range(0xFFE80000, 0xFFF88000)))

    for function in (0xFFEA5030, 0xFFED6966, 0xFFEC6639, 0xFFEDDD2F, 0xFFEA65FD, 0xFFEFF418):
        stock_return(function)
    stock_return(0xFFEC7EDC, 1)
    stock_return(0xFFEC670F, 9)
    stock_return(0xFFEC67C3)
    stock_return(0xFFEC7ACE)
    write(0xFFEC89F4, (memory[i] for i in range(0xFFEC89F4, 0xFFEC89F4 + 430)))

    state, packet, report = 0x3F870, 0x1B939, 0x1B485
    ptt, accepted, reason, sequence = 0x8013C5, 0x822D62, 0x17B54, 0x801324
    send_a = 0x8C02B
    playback_pin, playback_latch = 0x8C04B, 0x3D18D
    voice_active = 0x80130C + 0x21D3D
    pcm_play = 0x80130C + 0x21D82
    write(state, b"\xff" * 17)
    call(0xFFF8675F, 0x5140, stack=0x1000)
    assert bytes(cpu.readMemory(address(state), 17)) == bytes(16) + b"\xff"
    stock_init = bytes(memory[i] for i in range(0xFFE9C88C, 0xFFE9CCB8))
    assert bytes(cpu.readMemory(address(0x3F440), len(stock_init))) == stock_init

    word(0x83B2C8, 0x80130C)
    word(0x801328, 7074000)
    for location in (ptt, accepted, reason, pcm_play, send_a,
                     voice_active, 0x80130C + 0x21D83, 0x80130C + 0x21B20,
                     0x8013CD, 0x36617, playback_pin, playback_latch,
                     0x80130C + 0x21D7D, 0x80130C + 0x21FCC):
        write(location, b"\0")
    word(0x80130C + 0x2202C, 0)
    write(sequence, b"\x08")
    call(0xFFEA1E41, 0xFFEA1E45)
    assert byte(state) == 1

    def command(op, token, revision=None):
        if revision is None:
            revision = byte(state + 15) if op == 1 else 0
        write(packet, (0xe8, 0xf8, 70, 84, 56, op, token, revision, 0))
        call(0xFFED60CB, 0xFFED60F0, packet)

    def status(caller=0xFFEE401D, copy_caller=0):
        word(0x6000 + 32, caller)
        word(0x6000 + 36, copy_caller)
        call(0xFFED7F3F, 0xFFED7F4C)
        return byte(report)

    for location in (0x8013CE, 0x8013D4, 0x4B04, 0x801326, 0x50F4):
        write(location, b"\0")
    write(0x5044, (37,))
    write(0x504C, (50,))
    # Common frame offsets 30/31 carry original status values.
    write(report + 21, (0x8C, 0x32, 0, 0, 0x65))
    assert status() == 0x80
    assert byte(report + 23) == 37 and byte(report + 24) == 0x80
    write(0x50F4, b"\1")
    assert status() == 0x80
    assert byte(report + 23) == 50 and byte(report + 24) == 0x81
    assert (byte(report + 21), byte(report + 22), byte(report + 25)) == (0x8C, 0x32, 0x65)
    write(0x50F4, b"\0")
    # Outside a native lease, the original playback GPIO still owns voice PTT.
    call(0xFFEA12FB, 0xFFEA12FF)
    assert byte(playback_latch) == 1
    write(ptt, b"\1")
    write(voice_active, b"\1")
    write(playback_pin, b"\4")
    call(0xFFEA12FB, 0xFFEA12FF)
    assert byte(ptt) == byte(voice_active) == byte(playback_latch) == 0
    write(playback_pin, b"\0")
    call(0xFFEA12FB, 0xFFEA12FF)
    assert byte(playback_latch) == 1
    cpu.writeRegister("R14", 0x5100)
    cpu.writeRegister("R15", 0)
    write(0x5100, b"\1")
    call(0xFFED7AF1, 0xFFED7AF6)
    assert cpu.readRegister("R1").intValue() == 16
    word(state, 512)
    assert status() == 0xa0
    write(state + 15, b"\x8a")
    stock_return(0xFFEC7EDC, 0)
    command(1, 1)
    assert not byte(ptt) and not byte(pcm_play)
    stock_return(0xFFEC7EDC, 1)
    stock_return(0xFFEC670F, 0)
    assert status() & 3 == 3
    command(1, 2)
    assert not byte(ptt)
    stock_return(0xFFEC670F, 9)
    command(1, 8)
    command(1, 3, revision=1)
    assert not byte(ptt)
    command(1, 3)
    assert byte(ptt) == byte(pcm_play) == 1
    cpu.writeRegister("R14", 0x5100)
    cpu.writeRegister("R15", 0)
    call(0xFFED7AF1, 0xFFED7AF6)
    assert cpu.readRegister("R1").intValue() == 0
    assert status() & 0x1f == (3 << 2) | 2
    write(accepted, b"\1")
    write(reason, b"\x0a")
    assert status() & 3 == 2
    write(sequence, b"\x03")
    assert status() & 3 == 2
    write(send_a, b"\x08")
    assert status() & 3 == 1
    # Replay a stock playback-end edge just after the native lease keys RF.
    write(playback_pin, b"\4")
    call(0xFFEA12FB, 0xFFEA12FF)
    assert byte(ptt) == byte(voice_active) == byte(pcm_play) == 1, (
        "stock playback GPIO released native FT8 PTT"
    )
    command(0, 2)
    assert byte(ptt) == 1
    command(0, 3)
    assert not byte(ptt) and not byte(pcm_play)
    assert status() & 3 == 3
    for location in (accepted, reason, send_a):
        write(location, b"\0")
    write(sequence, b"\x08")
    call(0xFFEA12FB, 0xFFEA12FF)
    assert status() & 3 == 0
    assert byte(playback_latch) == 0

    command(1, 4)
    assert byte(ptt) == 1
    write(accepted, b"\1")
    write(reason, b"\x0a")
    write(sequence, b"\x03")
    write(send_a, b"\x08")
    word(state, 512 + 126400)
    call(0xFFEA12FB, 0xFFEA12FF)
    assert byte(ptt) == byte(pcm_play) == 1
    word(state, 512 + 135000)
    call(0xFFEA12FB, 0xFFEA12FF)
    assert not byte(ptt) and not byte(pcm_play)
    assert status() & 0xdf == 0x80 | (4 << 2) | 3

    for location in (accepted, reason, send_a):
        write(location, b"\0")
    write(sequence, b"\x08")
    call(0xFFEA12FB, 0xFFEA12FF)
    write(pcm_play + 1, b"\1")
    command(1, 5)
    assert not byte(ptt)
    write(pcm_play + 1, b"\0")
    command(1, 5)
    assert byte(ptt)
    word(state, 135512 + 2799)
    call(0xFFEA12FB, 0xFFEA12FF)
    assert byte(ptt)
    word(state, 135512 + 2800)
    call(0xFFEA12FB, 0xFFEA12FF)
    assert not byte(ptt) and not byte(pcm_play)
    call(0xFFEA12FB, 0xFFEA12FF)
    command(1, 6)
    assert byte(ptt)
    write(reason, b"\x09")
    call(0xFFEA12FB, 0xFFEA12FF)
    assert not byte(ptt) and not byte(pcm_play)
    write(reason, b"\0")
    call(0xFFEA12FB, 0xFFEA12FF)
    command(1, 7)
    assert byte(ptt) == byte(pcm_play) == 1
    assert status() & 0xc0 == 0x80
    # Other stock playback jobs still process their explicit stop request.
    word(0x80130C + 0x2202C, 2)
    call(0xFFEA12FB, 0xFFEA12FF)
    assert not byte(ptt) and not byte(pcm_play)
    assert status() & 0xdf == 0x80 | (7 << 2) | 3
    call(0xFFEA12FB, 0xFFEA12FF)
    assert status() & 0xdf == 0x80 | (7 << 2)

    stock_return(0xFFEC670F, 1)
    assert status() & 3 == 0
    command(1, 1)
    assert byte(ptt) == byte(pcm_play) == 1
    write(accepted, b"\1")
    write(reason, b"\x0a")
    write(sequence, b"\x03")
    write(send_a, b"\x08")
    call(0xFFEA12FB, 0xFFEA12FF)
    assert status() & 3 == 1
    stock_return(0xFFEC670F, 9)
    call(0xFFEA12FB, 0xFFEA12FF)
    assert not byte(ptt) and not byte(pcm_play)
    assert status() & 3 == 3

    def click(button):
        call(0xFFF01906, 0x5140, button)
        item = cpu.readRegister("R1").intValue() & 0xffffffff
        code, _, _, ident, callback = struct.unpack("<HBBII", bytes(cpu.readMemory(address(item), 12)))
        assert ident == button and code == 0x596 + (button == 0xef)
        call(callback, 0x5140)
        return byte(state + 15)

    write(state + 15, b"\0")
    assert click(0xee) == 0x8a
    assert status() & 0x80 and byte(report + 24) == 0x8a
    for caller, copy_caller in ((0xFFED7999, 0), (0xFFEDCC3D, 0xFFEE4074), (0xFFEDCC3D, 0xFFEE43E6)):
        write(report, b"\0")
        write(report + 23, b"\0\0")
        assert status(caller, copy_caller) & 0x80 and byte(report + 24) == 0x8a
    # The same stock copy node builds other types, including the 0x50 keyboard.
    write(0x6000 + 12, struct.pack("<H", 33))
    write(report, b"\0")
    write(report + 23, b"\0\xff")
    assert status(0xFFEDCC3D, 0xFFEDEB7A) == 0
    assert (byte(report + 23), byte(report + 24)) == (0, 0)
    assert click(0xef) == 0x94
    for location in (accepted, reason, send_a):
        write(location, b"\0")
    write(sequence, b"\x08")
    call(0xFFEA12FB, 0xFFEA12FF)
    command(1, 1, revision=0x8a)
    assert not byte(ptt) and not byte(pcm_play)
    command(2, 0x8a)
    assert byte(state + 15) == 0x94
    command(2, 0x94)
    assert byte(state + 15) == 0x98
    assert click(0xef) == 0xa4
    assert click(0xef) == 0xa8
    assert click(0xee) == 0xb2
    command(1, 1, revision=0x8a)
    assert not byte(ptt) and not byte(pcm_play)
    call(0xFFF0D076, 0xFFF0D082)
    assert byte(0x84c6) == 1 and byte(state + 15) == 0xb8
    assert click(0xef) == 0xb8
    cpu.dispose()
    print("PASS: USB/DATA-U PTT, timers, power, button dispatch, close revision and SWR exclusion")


main()
