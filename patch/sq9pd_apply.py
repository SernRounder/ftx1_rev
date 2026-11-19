"""Self-contained loader and verified applicator for sq9pd/Yaesu-FTX-1-mod diffs."""

import hashlib
import json
from pathlib import Path

DATA_PATH = Path(__file__).resolve().with_name("sq9pd_mod_data.json")


def load_sq9pd_data():
    try:
        return json.loads(DATA_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise FileNotFoundError("Generate the local sq9pd data with scripts/prepare_inputs.py. See docs/reproduce.md.") from error


def apply_sq9pd_display_payload(payload: bytearray, data=None) -> bytearray:
    """Apply all 47 sq9pd DISPLAY V01-10 runs in-place, verifying every original byte."""
    if data is None:
        data = load_sq9pd_data()
    disp = data["display"]
    end = 0
    parsed = []
    for pos_s, old_hex, new_hex in disp["runs"]:
        pos = int(pos_s, 16)
        old = bytes.fromhex(old_hex)
        new = bytes.fromhex(new_hex)
        if pos < end or len(old) != len(new) or pos + len(old) > len(payload):
            raise ValueError(f"Invalid DISPLAY sq9pd run at {pos:#x}")
        actual = bytes(payload[pos:pos + len(old)])
        if actual != old:
            raise ValueError(
                f"DISPLAY sq9pd original-byte mismatch at {pos:#x}: "
                f"expected {old.hex()}, got {actual.hex()}"
            )
        parsed.append((pos, len(old), new))
        end = pos + len(old)
    for pos, length, new in parsed:
        payload[pos:pos + length] = new
    return payload


def apply_sq9pd_display(image: bytearray, data=None) -> bytearray:
    """Apply all 47 sq9pd DISPLAY V01-10 runs onto stock DISPLAY V01-10 with SHA-256 checks."""
    if data is None:
        data = load_sq9pd_data()
    disp = data["display"]
    if hashlib.sha256(image).hexdigest() != disp["stock_sha256"]:
        raise ValueError("Expected stock DISPLAY V01-10 payload before applying sq9pd patches")
    apply_sq9pd_display_payload(image, data=data)
    if hashlib.sha256(image).hexdigest() != disp["patched_sha256"]:
        raise ValueError("DISPLAY payload SHA-256 mismatch after applying sq9pd patches")
    return image


def apply_sq9pd_main_rom(rom: bytearray, start_addr: int = 0xFFE80000, data=None) -> bytearray:
    """Apply all 322 sq9pd MAIN V01-13 runs onto a flat ROM buffer, verifying every original byte."""
    if data is None:
        data = load_sq9pd_data()
    parsed = []
    seen_end = 0
    for addr_s, old_hex, new_hex in data["main"]["runs"]:
        addr = int(addr_s, 16)
        old = bytes.fromhex(old_hex)
        new = bytes.fromhex(new_hex)
        off = addr - start_addr
        if len(old) != len(new) or off < 0 or off < seen_end or off + len(old) > len(rom):
            raise ValueError(f"Invalid MAIN sq9pd run at {addr:#x}")
        actual = bytes(rom[off:off + len(old)])
        if actual != old:
            raise ValueError(
                f"MAIN sq9pd original-byte mismatch at {addr:#x}: "
                f"expected {old.hex()}, got {actual.hex()}"
            )
        parsed.append((off, len(old), new))
        seen_end = off + len(old)
    for off, length, new in parsed:
        rom[off:off + length] = new
    return rom


def apply_sq9pd_main_records(records, data=None):
    """Apply all 322 sq9pd MAIN V01-13 binary runs onto parsed S-records.
    """
    if data is None:
        data = load_sq9pd_data()
    changed = {}
    for addr_s, old_hex, new_hex in data["main"]["runs"]:
        addr = int(addr_s, 16)
        old = bytes.fromhex(old_hex)
        new = bytes.fromhex(new_hex)
        if len(old) != len(new):
            raise ValueError(f"Mismatched MAIN sq9pd run length at {addr:#x}")
        for i, (o, n) in enumerate(zip(old, new, strict=True)):
            if addr + i in changed:
                raise ValueError(f"Duplicate MAIN sq9pd byte at {addr + i:#x}")
            changed[addr + i] = (o, n)

    seen = set()
    rebuilt = []
    for kind, address, payload, ok in records:
        updated = bytearray(payload)
        if kind == "3":
            for location in changed.keys() & range(address, address + len(payload)):
                old_b, new_b = changed[location]
                actual_b = payload[location - address]
                if location in seen or actual_b != old_b:
                    raise ValueError(
                        f"MAIN sq9pd original-byte mismatch at {location:#x}: "
                        f"expected {old_b:#04x}, got {actual_b:#04x}"
                    )
                updated[location - address] = new_b
                seen.add(location)
        rebuilt.append((kind, address, bytes(updated), ok))

    if seen != changed.keys():
        missing = sorted(changed.keys() - seen)
        raise ValueError(f"MAIN sq9pd address missing from baseline: {missing[0]:#x}")
    return rebuilt
