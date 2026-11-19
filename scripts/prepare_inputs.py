"""Prepare local baseline files and generate the sq9pd integration data."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "patch"))

from build_ft8_main import read_main, sfl_codec

SQ9PD_COMMIT = "ee71225da9db6200a8098547f4f00b6caf438371"
STOCK_HASHES = {
    "FTX-1_DISPLAY_V0110.SFL": "962fda27ae2f0a0deedb039b868a545ef0f6736b686c266e19f231dbe3973bba",
    "FTX-1_MAIN_V0113.SFL": "de02ce415b37ca6621ed0bac2f8e7bd63d45f3022a62868598950502ed033f5c",
    "FTX-1_IFDSP_V0110.SFL": "477afb2ae9f8d04ed5c7f1036eb7f84e23c98593edc9458db14be6351335f3e0",
}
MAIN_BASE = 0xFFE80000
MAIN_END = 1 << 32
BUTTON_TABLE = 0xFFF0E62A


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def verify(data, expected, label):
    actual = sha256(data)
    if actual != expected:
        raise ValueError(f"{label}: expected SHA-256 {expected}, got {actual}")


def read_inputs(zip_path):
    if zip_path is None:
        images = {name: (ROOT / "work/fw" / name).read_bytes() for name in list(STOCK_HASHES)[:2]}
        ifdsp = ROOT / "work/fw/FTX-1_IFDSP_V0110.SFL"
        if ifdsp.is_file():
            images[ifdsp.name] = ifdsp.read_bytes()
    else:
        with ZipFile(zip_path) as archive:
            images = {name: archive.read(name) for name in STOCK_HASHES}
    for name, data in images.items():
        verify(data, STOCK_HASHES[name], name)
    return images


def main_rom(records):
    rom = bytearray(b"\xff" * (MAIN_END - MAIN_BASE))
    for kind, address, data, _ in records:
        if kind == "3" and MAIN_BASE <= address < MAIN_END:
            end = address + len(data)
            if end > MAIN_END:
                raise ValueError(f"MAIN record exceeds flash at {address:#x}")
            rom[address - MAIN_BASE:end - MAIN_BASE] = data
    return rom


def changed_runs(before, after):
    start = None
    for offset, (old, new) in enumerate(zip(before, after, strict=True)):
        if old != new:
            if start is None:
                start = offset
        elif start is not None:
            yield [hex(MAIN_BASE + start), before[start:offset].hex(), after[start:offset].hex()]
            start = None
    if start is not None:
        yield [hex(MAIN_BASE + start), before[start:].hex(), after[start:].hex()]


def prepare(sq9pd, images):
    commit = subprocess.check_output(
        ["git", "-C", str(sq9pd), "rev-parse", "HEAD"], text=True,
    ).strip()
    if commit != SQ9PD_COMMIT:
        raise ValueError(f"sq9pd checkout must be at {SQ9PD_COMMIT}, got {commit}")
    # Read the pinned source directly from Git so working-tree edits cannot affect the result.
    js = subprocess.check_output(
        ["git", "-C", str(sq9pd), "show", f"{SQ9PD_COMMIT}:site/patch-data.js"],
        encoding="utf-8",
    )
    upstream = json.loads(js.split(" = ", 1)[1].strip().removesuffix(";"))
    parts = {part["component"]: part for part in upstream["components"]}
    decoded = {}
    for name, part in parts.items():
        raw = images[part["filename"]]
        verify(raw, part["input_sha256"], f"{name} upstream input")
        key = bytes.fromhex(upstream["key_hex"])
        before = bytes((byte - key[i % len(key)]) & 0xff for i, byte in enumerate(raw[576:]))
        verify(before, part["decoded_input_sha256"], f"{name} decoded input")
        after = bytearray(before)
        for offset, old_hex, new_hex in part["payload_patches"]:
            old, new = bytes.fromhex(old_hex), bytes.fromhex(new_hex)
            end = offset + len(old)
            if len(new) != len(old) or after[offset:end] != old:
                raise ValueError(f"{name} upstream byte mismatch at {offset:#x}")
            after[offset:end] = new
        verify(after, part["decoded_output_sha256"], f"{name} decoded output")
        header = bytearray(raw[:576])
        for offset, old_hex, new_hex in part["header_patches"]:
            old, new = bytes.fromhex(old_hex), bytes.fromhex(new_hex)
            end = offset + len(old)
            if len(new) != len(old) or header[offset:end] != old:
                raise ValueError(f"{name} upstream header mismatch at {offset:#x}")
            header[offset:end] = new
        encoded = bytes((byte + key[i % len(key)]) & 0xff for i, byte in enumerate(after))
        image = bytes(header) + encoded
        verify(image, part["output_sha256"], f"{name} upstream output")
        decoded[name] = before, image

    codec = sfl_codec()
    _, before_records = read_main(codec, images[parts["MAIN"]["filename"]])
    _, after_records = read_main(codec, decoded["MAIN"][1])
    before_rom, after_rom = main_rom(before_records), main_rom(after_records)
    main_runs = list(changed_runs(before_rom, after_rom))
    display_runs = [[hex(offset), old, new] for offset, old, new in parts["DISPLAY"]["payload_patches"]]
    if (len(main_runs), len(display_runs)) != (322, 47):
        raise ValueError("Unexpected sq9pd MAIN/DISPLAY run counts")
    button_offset = BUTTON_TABLE - MAIN_BASE
    data = {
        "source": "https://github.com/sq9pd/Yaesu-FTX-1-mod",
        "commit": SQ9PD_COMMIT,
        "release": upstream["release"],
        "main": {
            "button_table_70_addr": hex(BUTTON_TABLE),
            "button_table_70_hex": after_rom[button_offset:button_offset + 70].hex(),
            "decoded_output_sha256": parts["MAIN"]["decoded_output_sha256"],
            "runs": main_runs,
        },
        "display": {
            "stock_sha256": parts["DISPLAY"]["decoded_input_sha256"],
            "patched_sha256": parts["DISPLAY"]["decoded_output_sha256"],
            "runs": display_runs,
        },
    }

    fw_dir = ROOT / "work/fw"
    fw_dir.mkdir(parents=True, exist_ok=True)
    for filename, raw in images.items():
        path = fw_dir / filename
        if path.exists():
            verify(path.read_bytes(), STOCK_HASHES[filename], path)
        else:
            with path.open("xb") as output:
                output.write(raw)
    dec = ROOT / "work/dec"
    display_path = fw_dir / parts["DISPLAY"]["filename"]
    codec_path = ROOT / "work/tools/ft710-internals/decode_sfl.py"
    subprocess.run(
        [sys.executable, "-I", str(codec_path), "extract", str(display_path), str(dec / "display")],
        check=True,
    )
    verify((dec / "display/display.bin").read_bytes(), data["display"]["stock_sha256"], "extracted DISPLAY")
    (dec / "main-map.bin").write_bytes(before_rom)
    (dec / "main-map.srec").write_text(
        "".join(codec.format_srecord(*record[:3]) + "\n" for record in before_records),
        encoding="ascii",
    )

    if "FTX-1_IFDSP_V0110.SFL" in images:
        name = "FTX-1_IFDSP_V0110.SFL"
        output = dec / f"{name}.bin"
        subprocess.run(
            [sys.executable, "-I", str(codec_path), "extract", str(fw_dir / name), str(dec / "ifdsp")],
            check=True,
        )
        output.write_bytes((dec / "ifdsp/ifdsp.bin").read_bytes())
        verify(output.read_bytes(), "89033b8c0eac5a79893031eb0b6ca3b91e4f42f55fd519ace15b506da4a446e0",
               "decoded IFDSP")

    result = ROOT / "patch/sq9pd_mod_data.json"
    result.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"Verified baseline files and generated {result.relative_to(ROOT)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", type=Path, help="Official JP update ZIP. Omit to use work/fw/")
    parser.add_argument("--sq9pd", type=Path, default=ROOT / "work/tools/Yaesu-FTX-1-mod")
    args = parser.parse_args()
    try:
        prepare(args.sq9pd, read_inputs(args.zip))
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
