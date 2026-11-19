"""Test WAV -> patched DMA entry -> ARM decoder -> firmware UI, from one SFL."""

import argparse
import array
from pathlib import Path

from build_ft8_menu import IMAGE_BASE, ROOT, TAIL_OFFSET
from preview_ft8 import LivePanel, Panel
from test_ft8_arm import recording_16k
from test_ft8_menu import check_image


DEFAULT_SFL = ROOT / "outputs/FTX-1_DISPLAY_V0110-ft8live-LAB.sfl"
DEFAULT_WAV = ROOT / "downloads/210703_133430.wav"
EXPECTED = {
    "CQ F5RXL IN94": "~10267 km",
    "K1JT HA0DU KN07": "~8949 km",
    "WM3PEN EA6VQ -09": None,
    "XE2X HA2NP RR73": None,
}
TX_MESSAGE = "CQ W9XYZ PM95"


def capture_slot(panel, samples):
    for start in range(0, len(samples), 1999):
        panel.capture(samples[start:start + 1999])
        assert panel.poll() == 1
    assert panel.poll() == 0
    panel.refresh()


def key_tap(panel, char):
    """Tap a keyboard key by character using the shared layout."""
    layout = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    if char in layout:
        index = layout.index(char)
    else:
        index = {" ": 36, "<": 37, ">": 38}[char]
    row, col = divmod(index, 10)
    panel.tap(68 + col * 46 + 23, 200 + row * 34 + 17)


def tx_line(panel, index):
    panel.tap(554 + 90, 262 + index * 17 + 8)


def check_tx_failures(image, silence):
    def ready():
        p = LivePanel(image)
        p.show_mode()
        p.tap(510, 380)
        assert p.sync_slot()
        assert not p.arm(TX_MESSAGE, 2853)
        assert p.arm(TX_MESSAGE, 1000)
        return p

    def assert_no_success(p):
        p.refresh()
        assert TX_MESSAGE not in p.labels
        assert not any(packet[0] == 0xE8 for packet in p.packets)

    p = ready()
    p.tx_allow_start = False
    capture_slot(p, silence)
    assert p.tx_events == [] and " TX FAULT" in p.labels
    assert_no_success(p)

    p = ready()
    p.tx_accept_audio = False
    capture_slot(p, silence)
    assert p.tx_events == ["on", "off"] and not p.audio_blocks
    assert_no_success(p)

    p = ready()
    capture_slot(p, silence)
    assert p.tx_events == ["on"]
    p.tap(691, 394)  # STOP while keyed, with no RX frame queued.
    assert p.tx_events == ["on", "off"]
    assert_no_success(p)

    p = ready()
    capture_slot(p, silence)
    p.capture(array.array("h"), count=2001)
    p.capture(silence[:800])
    assert p.poll() == 1 and p.tx_events == ["on", "off"]
    assert_no_success(p)

    p = ready()
    capture_slot(p, silence)
    Panel.tap(p, 625, 130)
    assert p.poll() == 0 and p.tx_events == ["on", "off"]
    assert_no_success(p)

    p = ready()
    Panel.tap(p, 625, 130)  # Leave and re-enter before worker services pending arm.
    Panel.tap(p, 510, 380)
    assert p.sync_slot()
    capture_slot(p, silence)
    assert p.tx_events == []

    p = ready()
    capture_slot(p, silence)
    p.advance_ms(250)  # Worker wakes too late to maintain PCM continuity.
    assert p.poll() == 0 and p.tx_events == ["on", "off"]
    assert_no_success(p)

    p = ready()
    capture_slot(p, silence[:-1999])
    p.capture(silence[-1999:])  # Slot-ending frame arrived on time.
    p.advance_ms(5000)         # Its worker did not.
    assert p.poll() == 1 and p.tx_events == []
    assert_no_success(p)

    p = ready()
    p.tx_drain_result = 0
    capture_slot(p, silence)
    while len(p.audio_blocks) < 259:
        p.capture(silence[:800])
        assert p.poll() == 1
    assert not p.arm(TX_MESSAGE, 1000)  # Waiting for sink drain, still keyed.
    p.tx_confirm_stop = False
    p.tap(691, 394)
    assert p.tx_events == ["on"] and " STOPPING" in p.labels
    assert not p.arm(TX_MESSAGE, 1000)
    p.advance_ms(13500)  # Simulation of the platform lease expiring without poll().
    assert p.tx_events == ["on", "lease-expired"]
    assert p.poll() == 0 and p.tx_deadline is None
    assert_no_success(p)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sfl", type=Path, default=DEFAULT_SFL)
    parser.add_argument("--screenshots", type=Path)
    args = parser.parse_args()
    build = ROOT / "patch/build"
    image = check_image(args.sfl, (build / "ft8_live.bin").read_bytes(), False,
                        decoder=(build / "ft8_rx.bin").read_bytes())
    plain = Panel(image)
    plain.show_mode()
    plain.tap(510, 380)
    assert "RX PLATFORM NOT READY" in plain.labels
    plain.cpu.mem_write(IMAGE_BASE + TAIL_OFFSET, bytes(4))
    plain.show_mode()
    plain.tap(510, 380)
    assert "DECODER NOT LOADED" in plain.labels

    disconnected = LivePanel(image, simulate_tx=False)
    disconnected.show_mode()
    disconnected.tap(510, 380)
    assert " TX OFFLINE" in disconnected.labels
    assert disconnected.sync_slot()
    assert not disconnected.arm(TX_MESSAGE, 1000)
    capture_slot(disconnected, array.array("h", [0]) * 240_000)
    assert disconnected.tx_events == [] and not disconnected.packets

    panel = LivePanel(image)
    assert panel.set_position(35588632, 139731042)
    panel.show_mode()
    mode = panel.screen()
    assert not panel.sync_slot()
    panel.tap(510, 380)
    assert "WAITING FOR SLOT" in panel.labels
    assert "MY GRID PM95uo" in panel.labels
    assert "LOC 12:00:30" in panel.labels
    assert "BAND ACTIVITY" in panel.labels
    assert "RX FREQUENCY" in panel.labels and "NEXT TX" in panel.labels
    assert "Tx1 [DX] [MY] PM95" in panel.labels and "FREE [EDIT]" in panel.labels
    assert "TAP A ROW" in panel.labels

    samples = recording_16k(DEFAULT_WAV)
    assert panel.sync_slot()
    panel.capture(array.array("h"), count=2001)
    panel.capture(samples[:1999])
    assert panel.poll() == 1
    panel.refresh()
    assert "AUDIO GAP - WAITING FOR SLOT" in panel.labels

    panel.capture(samples[:1999])  # A pre-boundary frame already in the queue.
    assert panel.sync_slot(skip=19)
    assert panel.poll() == 1  # Discard the pre-boundary frame.
    panel.refresh()
    assert "RECEIVING FT8 SLOT" in panel.labels
    # The start falls inside a frame and the next slot starts in the final frame.
    capture_slot(panel, array.array("h", [0] * 19) + samples + array.array("h", [0] * 37))
    assert "8" in panel.labels
    for message, distance in EXPECTED.items():
        assert message in panel.labels
        if distance is not None:
            assert distance in panel.labels

    # Row selection uses the transmitter (the second callsign).
    panel.tap(300, 225)  # second decoded row: WM3PEN EA6VQ -09 at 2159 Hz
    assert "EA6VQ" in panel.labels
    assert "FREQ 2159 Hz" in panel.labels

    # Keyboard: set MY CALL through the MY GRID label zone.
    panel.tap(328, 126)
    assert "MY CALL: _" in panel.labels
    panel.tap(625, 130)  # BACK closes the keyboard without leaving the page
    assert "MY CALL" not in panel.labels and "BAND ACTIVITY" in panel.labels
    panel.tap(328, 126)
    for char in "W9XYZ":
        key_tap(panel, char)
    assert "MY CALL: W9XYZ" in panel.labels
    key_tap(panel, "<")  # backspace then retype
    key_tap(panel, "Z")
    key_tap(panel, ">")  # enter commits
    assert "Tx6 CQ W9XYZ PM95" in panel.labels

    # Free text entry through the FREE line.
    tx_line(panel, 6)
    assert "FREE TEXT: _" in panel.labels
    for char in "HELLO WORLD":
        key_tap(panel, char)
    key_tap(panel, ">")
    assert "FREE HELLO WORLD" in panel.labels
    tx_line(panel, 5)  # back to CQ
    # FREE text arms too (encoder path: encode_free).
    tx_line(panel, 6)                 # reopens the FREE keyboard
    key_tap(panel, ">")               # commit unchanged text, close keyboard
    panel.tap(601, 394)
    assert " ARMED" in panel.labels
    panel.tap(691, 394)  # STOP before the boundary
    assert " ARMED" not in panel.labels
    tx_line(panel, 5)

    # Complete the next slot using exactly the unconsumed suffix from above.
    capture_slot(panel, array.array("h", [0]) * (240_000 - 37))
    assert "0" in panel.labels

    # ---- Transmit through the UI: arm, slot boundary, TX, round-trip decode ----
    silence = array.array("h", [0]) * 240_000
    panel.tap(601, 394)  # TX NEXT
    assert " ARMED" in panel.labels
    panel.tap(691, 394)  # STOP disarms again
    assert " ARMED" not in panel.labels
    capture_slot(panel, silence)  # no transmission was armed
    assert panel.tx_events == []

    panel.tap(601, 394)  # arm for real
    assert " ARMED" in panel.labels
    capture_slot(panel, silence)  # boundary slot: TX starts at its end
    capture_slot(panel, silence)  # TX slot: silence in, FT8 out
    assert "CQ W9XYZ PM95" in panel.labels          # TX history row appeared
    assert panel.tx_events == ["on", "off"]
    assert not panel.packets
    assert len(panel.audio_blocks) == 6 + 253       # lead blocks + 800-sample stream
    stereo = array.array("h")
    for block in panel.audio_blocks:
        stereo.frombytes(block)
    mono = stereo[0::2][:4800 + 202240]
    assert len(mono) == 4800 + 202240
    capture_slot(panel, mono[4800:] + array.array("h", [0]) * (240_000 - 202240))
    assert "CQ W9XYZ PM95" in panel.labels          # our own transmission decoded

    check_tx_failures(image, silence)

    # Overflow the eight-slot FIFO. The next accepted frame must expose the gap.
    for _ in range(9):
        panel.capture(samples[:1999])
    for _ in range(8):
        assert panel.poll() == 1
    panel.capture(samples[:1999])
    assert panel.poll() == 1
    panel.refresh()
    assert "AUDIO GAP - WAITING FOR SLOT" in panel.labels

    panel.tap(625, 130)
    assert panel.screen().tobytes() == mode.tobytes()
    assert not panel.sync_slot()
    panel.capture(samples[:1999])
    assert panel.poll() == 0
    panel.tap(510, 380)
    assert "WAITING FOR SLOT" in panel.labels
    panel.tap(625, 130)
    panel.tap(265, 174)
    assert panel.packets[-2:] == [bytes.fromhex("e001012100"), bytes.fromhex("e000012100")]
    if args.screenshots:
        args.screenshots.mkdir(parents=True, exist_ok=True)
        mode.save(args.screenshots / "ft8-live-mode.png")
        result = panel.screen()
        result.save(args.screenshots / "ft8-live-decoded.png")
    print("PASS: integrated DMA, UI, slot boundaries, TX round-trip, and recovery")


if __name__ == "__main__":
    main()
