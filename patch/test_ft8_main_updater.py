"""Run the stock DISPLAY MAIN image reader with a simulated SD file."""

import argparse
import struct
from pathlib import Path

from unicorn import UC_ARCH_ARM, UC_HOOK_CODE, UC_MODE_ARM, Uc
from unicorn.arm_const import (
    UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
    UC_ARM_REG_R3, UC_ARM_REG_SP,
)

from build_ft8_main import MAIN_APP_LIMIT, MAIN_CODE, ROOT, read_main, sfl_codec


BASE = 0x60400000
STACK, STOP, TAIL = 0x609FE000, 0x61000000, 0x61001000
FILE = 1


class Reader:
    def __init__(self, display, image):
        self.cpu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        self.cpu.mem_map(0x60000000, 0xA00000)
        self.cpu.mem_map(STOP, 0x2000)
        self.cpu.mem_write(BASE, display)
        self.image = image
        self.position = 0
        self.crc_ok = False
        self.bad_record = None
        for offset, action in ((0x6A8F8, self.read), (0x6A230, self.readline), (0x6B5F0, self.seek)):
            address = BASE + offset
            self.cpu.hook_add(UC_HOOK_CODE, self.file_call, action, begin=address, end=address)
        for offset in (0xAC00, 0xAC60):
            address = BASE + offset
            self.cpu.hook_add(UC_HOOK_CODE, self.observe, begin=address, end=address)

    def observe(self, cpu, address, _size, _data):
        value = cpu.reg_read(UC_ARM_REG_R0)
        if address == BASE + 0xAC00:
            self.crc_ok = value == 0
        elif value == 0xFFFFFFFF:
            self.bad_record = self.position

    def file_call(self, cpu, _address, _size, action):
        registers = UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3
        result = action(*(cpu.reg_read(register) for register in registers))
        cpu.reg_write(UC_ARM_REG_R0, result)
        cpu.reg_write(UC_ARM_REG_PC, cpu.reg_read(UC_ARM_REG_LR))

    def read(self, target, width, count, handle):
        assert handle == FILE and width == 1
        data = self.image[self.position:self.position + count]
        if data:
            self.cpu.mem_write(target, data)
        self.position += len(data)
        return len(data)

    def readline(self, target, capacity, handle, _unused):
        assert handle == FILE
        if self.position == len(self.image):
            return 0
        end = min(self.position + capacity - 1, len(self.image))
        lf = self.image.find(b"\n", self.position, end)
        if lf >= 0:
            end = lf + 1
        self.cpu.mem_write(target, self.image[self.position:end] + b"\0")
        self.position = end
        return target

    def seek(self, handle, position, origin, _unused):
        assert handle == FILE and origin == 0
        self.position = position
        return 0

    def tail(self):
        # FUN_0000abc4 performs the stock outer CRC check, streams and parses
        # every S-record, and copies bytes in the requested flash interval.
        for register, value in ((UC_ARM_REG_R0, FILE), (UC_ARM_REG_R1, MAIN_CODE),
                                (UC_ARM_REG_R2, MAIN_APP_LIMIT - 1), (UC_ARM_REG_R3, TAIL),
                                (UC_ARM_REG_SP, STACK), (UC_ARM_REG_LR, STOP)):
            self.cpu.reg_write(register, value)
        self.cpu.mem_write(STACK, struct.pack("<I", 1))
        self.cpu.emu_start(BASE + 0xABC4, STOP, count=900_000_000)
        assert self.cpu.reg_read(UC_ARM_REG_PC) == STOP
        assert self.cpu.reg_read(UC_ARM_REG_SP) == STACK
        return self.cpu.reg_read(UC_ARM_REG_R0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="+", type=Path)
    parser.add_argument("--reject", action="append", type=Path, default=[])
    args = parser.parse_args()
    display = (ROOT / "work/dec/display/display.bin").read_bytes()
    codec = sfl_codec()
    for path in args.images:
        image = path.read_bytes()
        _, records = read_main(codec, image)
        expected = b"".join(data for kind, address, data, _ in records
                            if kind == "3" and MAIN_CODE <= address < MAIN_APP_LIMIT)
        reader = Reader(display, image)
        assert reader.tail() == len(expected), path
        assert reader.crc_ok and reader.bad_record is None, path
        assert reader.cpu.mem_read(TAIL, len(expected)) == expected, path
        print(f"PASS: stock updater accepted {path.parent.name}, copied {len(expected)} tail bytes", flush=True)
    for path in args.reject:
        reader = Reader(display, path.read_bytes())
        assert reader.tail() == 0xFFFFFFFF, path
        assert reader.crc_ok and reader.bad_record is not None, path
        assert reader.bad_record >= len(reader.image) - 0x1000, path
        print(f"PASS: stock updater passed CRC then rejected a tail record in {path.parent.name}", flush=True)


if __name__ == "__main__":
    main()
