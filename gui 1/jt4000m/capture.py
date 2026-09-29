"""P1.6 — capture buffer: raw MIDI bytes received from a device -> files.

Design rules (from the P1.6 brief):
  * SysEx bytes are stored EXACTLY as received — no re-encoding, no added or
    stripped F0/F7, no checksum "fixing".
  * Provenance of a written capture is always CAPTURED_FROM_DEVICE; bundled
    analysis banks remain REFERENCE_FIXTURE and are never relabelled.
  * Malformed / non-SysEx traffic is not silently dropped: it is counted and
    typed so the operator sees what actually arrived.
  * Absence of RX is a VALID result (NO_RX), never a Python error.

This module performs NO MIDI I/O: the CLI feeds it messages observed on a
transport input port.  That keeps all of it offline-testable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .experiment import PROVENANCE_DEVICE

F0 = 0xF0
F7 = 0xF7


def classify_rx(data: bytes) -> str:
    """Honest message-type label for one received MIDI packet."""
    if not data:
        return "EMPTY"
    if data[0] == F0:
        if data[-1] == F7:
            return "SYSEX_COMPLETE"
        return "SYSEX_INCOMPLETE"          # truncated / still streaming
    status = data[0] & 0xF0
    names = {0x80: "NOTE_OFF", 0x90: "NOTE_ON", 0xA0: "POLY_AT",
             0xB0: "CONTROL_CHANGE", 0xC0: "PROGRAM_CHANGE",
             0xD0: "CHANNEL_AT", 0xE0: "PITCH_BEND"}
    return names.get(status, f"UNKNOWN_0x{data[0]:02X}")


@dataclass
class CaptureRecord:
    at: float           # wall-clock timestamp (time.time())
    kind: str           # classify_rx() label
    data: bytes         # raw bytes exactly as received


@dataclass
class CaptureBuffer:
    """Collects RX packets during a listen/capture session."""
    records: list[CaptureRecord] = field(default_factory=list)

    def add(self, ts: float, data: bytes) -> CaptureRecord:
        rec = CaptureRecord(at=ts, kind=classify_rx(bytes(data)),
                            data=bytes(data))
        self.records.append(rec)
        return rec

    # ------------------------------------------------------------- summaries
    @property
    def total(self) -> int:
        return len(self.records)

    def counts_by_kind(self) -> dict:
        out: dict[str, int] = {}
        for r in self.records:
            out[r.kind] = out.get(r.kind, 0) + 1
        return out

    @property
    def sysex_complete(self) -> list[CaptureRecord]:
        return [r for r in self.records if r.kind == "SYSEX_COMPLETE"]

    # ---------------------------------------------------------------- output
    def save_last_sysex(self, path: str | Path) -> Path | None:
        """Write the LAST complete SysEx dump byte-for-byte as captured.

        Returns None when no complete SysEx was received (the caller reports
        NO_RX honestly; nothing is written).
        """
        dumps = self.sysex_complete
        if not dumps:
            return None
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(dumps[-1].data)
        return p

    def save_all(self, path: str | Path) -> Path:
        """Save EVERY received packet (incl. malformed) to a JSONL file for
        forensics: one line per message with timestamp/kind/hex/raw length."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as fh:
            for r in self.records:
                fh.write(_jsonl_line({
                    "at": r.at,
                    "kind": r.kind,
                    "len": len(r.data),
                    "hex": r.data.hex(" "),
                }) + "\n")
        return p

    def result_label(self) -> str:
        """Documented outcome vocabulary for the live-session report."""
        if self.total == 0:
            return "NO_RX"
        if self.sysex_complete:
            return "DEVICE RX OBSERVED"
        return "RX_NON_SYSEX_ONLY"


def _jsonl_line(d: dict) -> str:
    import json
    return json.dumps(d, ensure_ascii=False)


# Re-export so callers get provenance without importing experiment.py twice.
CAPTURE_PROVENANCE = PROVENANCE_DEVICE
