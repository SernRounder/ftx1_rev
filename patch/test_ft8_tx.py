"""Build and run the host TX round-trip test (encode -> synth -> decode)."""

import subprocess
import tempfile
from pathlib import Path


PATCH = Path(__file__).resolve().parent
ROOT = PATCH.parent
LIB = ROOT / "work/ft8_lib"

if __name__ == "__main__":
    from test_ft8_rx import CORE_SOURCES

    with tempfile.TemporaryDirectory(prefix="ftx1-ft8tx-") as tmp:
        exe = Path(tmp) / "test_ft8_tx.exe"
        subprocess.run([
            "gcc", "-O2", "-I", str(ROOT), "-I", str(LIB), "-I", str(PATCH),
            "-include", str(ROOT / "scripts/stpcpy_shim.h"),
            str(PATCH / "test_ft8_tx.c"), str(PATCH / "payload/ft8_adif.c"),
            str(PATCH / "payload/ft8_dma_tx.c"), *map(str, CORE_SOURCES),
            "-lm", "-o", str(exe),
        ], check=True)
        subprocess.run([str(exe)], check=True)
