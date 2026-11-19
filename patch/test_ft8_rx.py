"""Build and test the streaming receive core against a stock ft8_lib recording."""

import subprocess
import tempfile
from pathlib import Path


PATCH = Path(__file__).resolve().parent
LIB = PATCH.parent / "work/ft8_lib"
CORE_SOURCES = (
    PATCH / "payload/ft8_rx.c",
    PATCH / "payload/ft8_tx.c",
    PATCH / "payload/ft8_locator.c",
    PATCH / "payload/ft8_distance.c",
    LIB / "common/monitor.c",
    LIB / "fft/kiss_fft.c",
    LIB / "fft/kiss_fftr.c",
    *(LIB / f"ft8/{name}.c" for name in ("constants", "crc", "decode", "encode", "ldpc", "message", "text")),
)
RECORDING = LIB / "test/wav/191111_110130.wav"


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="ftx1-ft8-") as tmp:
        exe = Path(tmp) / "test_ft8_rx.exe"
        subprocess.run([
            "gcc", "-O2", "-I", str(LIB), "-I", str(PATCH),
            "-include", str(PATCH.parent / "scripts/stpcpy_shim.h"),
            str(PATCH / "test_ft8_rx.c"), *map(str, CORE_SOURCES),
            str(LIB / "common/wave.c"), "-lm", "-o", str(exe),
        ], check=True)
        subprocess.run([str(exe), str(RECORDING)], check=True)
