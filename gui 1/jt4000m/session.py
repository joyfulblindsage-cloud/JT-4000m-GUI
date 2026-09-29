"""P1.6 — machine-readable live hardware session log.

Every live MIDI session (probe / cc / sysex-send / listen / capture) must be
recorded as structured JSON, not just printed to stdout.  This module defines
the schema and the append-only writer.  It performs NO MIDI I/O itself: the
CLI fills the record from real transport results and saves it here.

Evidence discipline (levels are strictly separated, never conflated):

  * TRANSPORT VERIFIED      — a send action's MIDI API returned OK (tx_ok).
                              This NEVER implies the synth applied anything.
  * DEVICE RX OBSERVED      — at least one message was actually received from
                              the device on a MIDI input port (rx_messages>0).
  * DEVICE BEHAVIOR VERIFIED— NOT decided here; only an A/B experiment over
                              CAPTURED_FROM_DEVICE dumps can grant that level
                              (see experiment.py verdicts).

Provenance labels reuse experiment.py constants so there is exactly ONE
vocabulary in the project:
  REFERENCE_FIXTURE      — bundled analysis files (ALL EMPTY.syx, ...); they
                           were NOT proven to come from a physical device.
  CAPTURED_FROM_DEVICE   — bytes actually received from the JT-4000M.
"""
from __future__ import annotations

import json
import platform
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .experiment import PROVENANCE_DEVICE, PROVENANCE_FIXTURE  # noqa: F401

SCHEMA_VERSION = 1

# Verification levels (documented vocabulary — no invented synonyms).
TRANSPORT_VERIFIED = "TRANSPORT VERIFIED"
TRANSPORT_FAILED = "TRANSPORT FAILED"
DEVICE_RX_OBSERVED = "DEVICE RX OBSERVED"
NO_RX = "NO_RX"

SESSIONS_DIRNAME = "sessions"


def new_session_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + \
        uuid.uuid4().hex[:8]


class SessionLog:
    """Accumulates one live-session record; save() writes sessions/<id>.json."""

    def __init__(self, backend: str, *, session_id: str | None = None,
                 now: datetime | None = None):
        self.session_id = session_id or new_session_id()
        self.started_at = (now or datetime.now(timezone.utc))
        self.platform = platform.platform()
        self.backend = backend
        self.input_port: dict | None = None
        self.output_port: dict | None = None
        self.actions: list[dict] = []
        self.files: list[dict] = []
        self.notes: list[str] = []

    # ------------------------------------------------------------- recording
    def set_ports(self, *, input_port=None, output_port=None):
        if input_port is not None:
            self.input_port = _port_dict(input_port)
        if output_port is not None:
            self.output_port = _port_dict(output_port)

    def add_action(self, name: str, *, tx_bytes: bytes | None = None,
                   api_ok: bool | None = None, rx_count: int | None = None,
                   detail: dict | None = None, error: str = ""):
        rec: dict = {"action": name}
        if tx_bytes is not None:
            rec["tx_len"] = len(tx_bytes)
            rec["tx_hex_head"] = " ".join(
                f"{b:02X}" for b in tx_bytes[:16])
        if api_ok is not None:
            rec["transport"] = (TRANSPORT_VERIFIED if api_ok
                                else TRANSPORT_FAILED)
        if rx_count is not None:
            rec["rx_messages"] = rx_count
        if error:
            rec["error"] = error
        if detail:
            rec["detail"] = detail
        rec["at"] = datetime.now(timezone.utc).isoformat()
        self.actions.append(rec)
        return rec

    def add_file(self, path: str | Path, kind: str,
                 provenance: str = PROVENANCE_FIXTURE,
                 checksum_status: str = "", size: int | None = None,
                 messages: int | None = None):
        p = Path(path)
        rec = {
            "path": str(p),
            "kind": kind,                       # e.g. "capture", "fixture"
            "provenance": provenance,           # device vs reference fixture
            "size": size if size is not None
                    else (p.stat().st_size if p.exists() else None),
        }
        if checksum_status:
            rec["checksum"] = checksum_status
        if messages is not None:
            rec["messages"] = messages
        self.files.append(rec)
        return rec

    def note(self, text: str):
        self.notes.append(text)

    # ------------------------------------------------------------ derivation
    @property
    def tx_messages(self) -> int:
        return sum(1 for a in self.actions if "tx_len" in a)

    @property
    def rx_messages(self) -> int:
        return sum(a.get("rx_messages", 0) for a in self.actions)

    def verification_levels(self) -> list[str]:
        """Honest, rule-based levels derived from recorded facts.

        Documented rules (no guessing):
          TRANSPORT VERIFIED  iff some action has transport == TRANSPORT_VERIFIED
          DEVICE RX OBSERVED  iff total rx_messages > 0
          DEVICE BEHAVIOR VERIFIED is NEVER emitted here — it requires an A/B
          experiment on CAPTURED_FROM_DEVICE data (experiment.py owns it).
        """
        out = []
        if any(a.get("transport") == TRANSPORT_VERIFIED for a in self.actions):
            out.append(TRANSPORT_VERIFIED)
        if self.rx_messages > 0:
            out.append(DEVICE_RX_OBSERVED)
        return out

    # ------------------------------------------------------------------ io
    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "session_id": self.session_id,
            "timestamp": self.started_at.isoformat(),
            "platform": self.platform,
            "backend": self.backend,
            "input_port": self.input_port,
            "output_port": self.output_port,
            "actions": self.actions,
            "tx_messages": self.tx_messages,
            "rx_messages": self.rx_messages,
            "files": self.files,
            "verification": self.verification_levels(),
            "notes": self.notes,
        }

    def save(self, base_dir: str | Path | None = None) -> Path:
        base = Path(base_dir) if base_dir else Path.cwd() / SESSIONS_DIRNAME
        base.mkdir(parents=True, exist_ok=True)
        path = base / f"{self.session_id}.json"
        path.write_text(json.dumps(self.to_dict(), indent=2,
                                   ensure_ascii=False),
                        encoding="utf-8")
        return path


def load_session(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _port_dict(port) -> dict:
    # Accepts transport.PortInfo or anything with index/name/direction.
    return {
        "index": getattr(port, "index", None),
        "name": getattr(port, "name", None),
        "direction": getattr(port, "direction", None),
    }
