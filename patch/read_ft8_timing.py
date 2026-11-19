"""Convert the DISPLAY FT8TIME.BIN debug log to CSV with microsecond timing."""

import argparse
import csv
import struct
import sys
from pathlib import Path


RECORD = struct.Struct("<IIHH")
EVENTS = (
    "pcm", "fft", "costas_search", "heap_sort", "candidate", "llr",
    "normalize", "ldpc", "crc", "unpack", "snr_and_distance", "auto_and_qso",
    "publish", "scheduler_yield", "scan", "sd_flush", "lost",
    "tx_stop_sent", "main_rx_confirmed", "rx_timeout", "first_dma_callback",
    "first_pcm_queued", "pcm_queue_drop", "pcm_gap", "slot_audio", "slot_status", "rx_ready",
    "rx_sealed", "rx_batch", "rx_draw",
    "tx_fault", "tx_request", "tx_keyed", "scan_reject", "rx_sync",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    args = parser.parse_args()
    writer = csv.writer(sys.stdout, lineterminator="\n")
    writer.writerow(("start_us", "elapsed_us", "stage", "detail", "status"))
    with args.log.open("rb") as stream:
        while raw := stream.read(RECORD.size):
            if len(raw) != RECORD.size:
                parser.error("incomplete record at end of log")
            start, elapsed, event, detail = RECORD.unpack(raw)
            index = event - 0x8101
            if index < 0 or index >= len(EVENTS):
                parser.error(f"unknown event {event:#x} at byte {stream.tell() - RECORD.size}")
            stage = EVENTS[index]
            status = ""
            if stage in ("candidate", "costas_search"):
                detail, flag = detail & 0x7fff, detail >> 15
                status = (("crc_failed", "crc_ok") if stage == "candidate" else
                          ("streaming", "final"))[flag]
            elif stage == "ldpc":
                detail, errors = detail >> 8, detail & 255
                status = f"parity_errors={errors}"
            elif stage in ("crc", "unpack"):
                status = "ok" if detail else "failed"
            elif stage == "slot_audio":
                detail, code = detail & 0x3fff, detail >> 14
                status = ("scan_started", "tx_or_rx_handoff", "insufficient_pcm",
                          "scan_not_started")[code]
            elif stage == "tx_fault":
                why = detail >> 12
                status = ("unknown", "synth_open", "slot_late_ms", "start_rejected_reason",
                          "lease_expired_blocks_due", "worker_catchup_blocks_due", "synth_block",
                          "submit_block", "drain_failed_reason")[why]
                detail &= 4095
            elif stage == "pcm_gap":
                status = "reset" if detail >> 15 else "silence_inserted"
                detail &= 32767
            elif stage == "scan_reject":
                status = ("unknown", "insufficient_pcm", "scan_too_recent", "cutoff", "previous_slot")[detail >> 13]
                detail = (detail & 8191) * 2
            elif stage == "rx_sync":
                status = "first_processed_frame_end_ms" if detail else "rolling"
                detail = max(0, detail - 1)
            elif stage == "rx_batch":
                slot = "15/45" if detail >> 15 else "00/30"
                status = f"slot={slot} rows={(detail >> 10) & 31}"
                detail &= 1023  # low bits of the on-screen batch
            elif stage == "rx_draw":
                status = f"00/30_rows={detail & 15} 15/45_rows={(detail >> 4) & 15}"
                detail = (detail >> 8) + 1  # visible page
            writer.writerow((start, elapsed, stage, detail, status))


if __name__ == "__main__":
    main()
