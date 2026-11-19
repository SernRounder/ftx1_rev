"""Build the position-independent FULL AUTO queue formatter for the SD card."""

import argparse
import struct
import tempfile
import zlib
from pathlib import Path

from elftools.elf.elffile import ELFFile

from build_ft8_menu import PAYLOAD, ZIG, run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zig", type=Path, default=ZIG)
    parser.add_argument("-o", "--out", type=Path, required=True)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as directory:
        elf_path = Path(directory) / "ft8_queue.elf"
        run(args.zig, "cc", "-target", "thumb-freestanding-eabi", "-mcpu=cortex_a9",
            "-mthumb", "-mfloat-abi=soft", "-Oz", "-fPIC", "-ffreestanding", "-fno-builtin",
            "-fno-unwind-tables", "-fno-stack-protector", "-ffunction-sections", "-fdata-sections",
            "-DFT8_RADIO", "-nostdlib", "-static", "-Wl,--no-undefined", "-Wl,--gc-sections",
            "-Wl,-e,ft8_queue_entry",
            f"-Wl,-T,{PAYLOAD / 'ft8_plugin.ld'}", PAYLOAD / "ft8_queue_plugin.c", "-o", elf_path)
        with elf_path.open("rb") as file:
            elf = ELFFile(file)
            section = elf.get_section_by_name(".plugin")
            code = section.data()
            entry = elf.header["e_entry"]
            if (section["sh_addr"] != 0 or not entry & 1 or entry & ~1 >= len(code)
                    or len(code) > 16 * 1024):
                raise ValueError("Invalid FT8 plugin entry or size")
            for section in elf.iter_sections():
                if section["sh_size"] and (section["sh_type"] in ("SHT_REL", "SHT_RELA") or
                                          section["sh_flags"] & 2 and section.name != ".plugin"):
                    raise ValueError(f"Unexpected plugin section {section.name}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    header = struct.pack("<4s3I", b"FT8P", 1, len(code), entry)
    args.out.write_bytes(header + struct.pack("<I", zlib.crc32(header + code)) + code)
    print(f"{args.out}: {len(code)} bytes of position-independent code and data")


if __name__ == "__main__":
    main()
