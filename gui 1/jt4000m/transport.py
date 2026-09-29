"""P1.5 — minimal hardware MIDI transport abstraction (OFFLINE-safe).

This module is a thin façade over the EXISTING project backends; it adds no
new MIDI library and reimplements no MIDI I/O:

  * Windows: ``jt4000m.midi_winmm`` (ctypes WinMM) — lazy import only, so
    importing this module never touches winmm.dll on any platform;
  * other platforms: optional ``python-rtmidi`` if installed, otherwise the
    transport reports "no backend available" honestly instead of pretending.

Evidence discipline (critical): every send*() method returns a TransportReport
that describes ONLY what the MIDI API acknowledged (TX level). It never claims
the synthesizer applied anything: device_response is always NOT_VERIFIED here.
Device behavior must be proven separately by A/B SysEx capture + experiment.py.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Iterator


@dataclass(frozen=True)
class PortInfo:
    index: int
    name: str
    direction: str  # "input" | "output"


@dataclass(frozen=True)
class TransportReport:
    """Honest record of one TX operation at the TRANSPORT level only."""
    op: str                 # "cc" | "sysex"
    port: PortInfo
    tx_bytes: bytes
    api_ok: bool            # True = the MIDI API accepted the message
    error: str = ""
    device_response: str = "NOT VERIFIED"  # TX success NEVER implies RX/effect

    def format(self) -> str:
        hexed = " ".join(f"{b:02X}" for b in self.tx_bytes)
        lines = [
            f"TX ({len(self.tx_bytes)} bytes):",
            f"  {hexed}",
            "Transport:",
            f"  {'OK' if self.api_ok else 'FAILED'}"
            + (f" — {self.error}" if self.error else ""),
            f"Output endpoint: [{self.port.index}] {self.port.name}",
            "Device response:",
            "  NOT VERIFIED",
            "",
            "NOTE: TRANSPORT VERIFIED != DEVICE BEHAVIOR VERIFIED.",
            "      The synth may or may not have applied the parameter;",
            "      prove it with an A/B SysEx capture (experiment compare).",
        ]
        return "\n".join(lines)


def _load_backend():
    """Return (backend_name, backend_module_or_None, note)."""
    import os
    if os.name == "nt":
        try:
            from . import midi_winmm as be
            return "winmm", be, ""
        except Exception as e:  # pragma: no cover - Windows-only path
            return "none", None, f"winmm unavailable: {e}"
    try:  # optional, only if the user installed it; never required for tests
        import rtmidi as be  # type: ignore
        return "rtmidi", be, ""
    except Exception as e:
        return "none", None, (
            "no MIDI backend on this platform (python-rtmidi not installed; "
            f"import error: {e}). Offline analysis commands still work."
        )


class MidiTransport:
    """Backend-agnostic list/open/send/receive operations.

    Construction is always safe (no device access). Opening ports and sending
    are explicit user actions from the CLI only — never from unit tests.

    For offline testing a fake backend object can be injected explicitly via
    the constructor; default construction NEVER touches real MIDI devices.
    """

    def __init__(self, *, backend=None, backend_name: str | None = None):
        if backend is not None:
            self.backend_name = backend_name or "injected"
            self._be = backend
            self.note = ""
        else:
            self.backend_name, self._be, self.note = _load_backend()
        self.available = self._be is not None
        self._in_port = None
        self._in_index: int | None = None

    # ------------------------------------------------------------- discovery
    def list_inputs(self) -> list[PortInfo]:
        return self._list("input")

    def list_outputs(self) -> list[PortInfo]:
        return self._list("output")

    def _list(self, direction: str) -> list[PortInfo]:
        if not self.available:
            return []
        if self.backend_name == "winmm":
            ports = (self._be.list_inputs() if direction == "input"
                     else self._be.list_outputs())
            return [PortInfo(p.index, p.name, direction) for p in ports]
        # rtmidi backend — enumerating can fail on systems without a working
        # MIDI subsystem (e.g. no ALSA sequencer). Report honestly instead of
        # crashing; the CLI turns this into an ap.error() with the reason.
        # rtmidi / injected backends expose the same port-object API shape.
        mod = self._be
        cls = mod.MidiIn if direction == "input" else mod.MidiOut
        try:
            probe = cls()
        except Exception as e:
            raise RuntimeError(
                f"MIDI backend '{direction}' enumeration failed: {e}") from e
        try:
            names = probe.get_ports()
        finally:
            try:
                probe.close_port()
            except Exception:
                pass
            del probe
        return [PortInfo(i, n, direction) for i, n in enumerate(names)]

    def find(self, needle: str, direction: str | None = None) -> list[PortInfo]:
        """Case-insensitive substring match by name (never assume numeric idx)."""
        needle = needle.lower()
        out: list[PortInfo] = []
        if direction in (None, "input"):
            out += [p for p in self.list_inputs() if needle in p.name.lower()]
        if direction in (None, "output"):
            out += [p for p in self.list_outputs() if needle in p.name.lower()]
        return out

    # ------------------------------------------------------------------ open
    def open_output(self, port: PortInfo):
        if not self.available:
            raise RuntimeError(self.note or "no MIDI backend available")
        if self.backend_name == "winmm":
            return port  # winmm helpers open/close per call; index identifies it
        handle = self._be.MidiOut()
        handle.open_port(port.index)
        return handle

    def open_input(self, port: PortInfo):
        if not self.available:
            raise RuntimeError(self.note or "no MIDI backend available")
        if self.backend_name == "winmm":
            self._in_port, self._in_index = "winmm-callback", port.index
            return port
        handle = self._be.MidiIn()
        handle.open_port(port.index)
        handle.set_buffer_size(65536)
        self._in_port, self._in_index = handle, port.index
        return handle

    # ------------------------------------------------------------------ send
    def send_cc(self, port: PortInfo, channel: int, controller: int,
                value: int) -> TransportReport:
        from .midi import make_cc
        msg = make_cc(channel, controller, value)  # validates ranges
        data = msg.bytes()
        ok, err = True, ""
        try:
            if self.backend_name == "winmm":
                self._be.send_short(port.index, data)
            elif self.backend_name == "rtmidi":
                self.open_output(port).send_message(list(data))
            else:
                ok = False
                err = self.note or "no MIDI backend available"
        except Exception as e:
            ok, err = False, str(e)
        return TransportReport("cc", port, data, ok, err)

    def send_sysex(self, port: PortInfo, data: bytes) -> TransportReport:
        ok, err = True, ""
        try:
            if self.backend_name == "winmm":
                self._be.send_sysex(port.index, bytes(bytearray(data)))
            elif self.backend_name == "rtmidi":
                self.open_output(port).send_message(list(data))
            else:
                ok = False
                err = self.note or "no MIDI backend available"
        except Exception as e:
            ok, err = False, str(e)
        return TransportReport("sysex", port, bytes(data), ok, err)

    # ---------------------------------------------------------------- receive
    def receive(self, timeout: float = 10.0,
                on_message: Callable[[float, bytes], None] | None = None
                ) -> Iterator[tuple[float, bytes]]:
        """Yield (timestamp_seconds, raw_message_bytes) until `timeout` elapses.

        winmm backend yields whole SysEx buffers via receive_sysex semantics;
        rtmidi backend polls the input queue. No messages => empty iterator
        (absence of RX is reported by the caller as 'Waiting for MIDI...',
        never as a Python error).
        """
        if not self.available:
            raise RuntimeError(self.note or "no MIDI backend available")
        deadline = time.monotonic() + timeout
        if self.backend_name == "winmm":
            # One buffered SysEx per call within remaining time (documented
            # limitation of the existing winmm helper; short messages are not
            # surfaced by that helper).
            remaining = max(0.05, deadline - time.monotonic())
            try:
                data = self._be.receive_sysex(self._in_index, timeout=remaining)
                ts = time.time()
                if on_message:
                    on_message(ts, data)
                yield ts, data
            except TimeoutError:
                return
        else:
            dev = self._in_port
            while time.monotonic() < deadline:
                msg = dev.get_message()
                if msg:
                    delta, data = msg
                    raw = bytes(data)
                    ts = time.time() - (time.monotonic() - (deadline - timeout)) \
                        + delta  # monotonic base + device timestamp offset
                    ts = time.time()
                    if on_message:
                        on_message(ts, raw)
                    yield ts, raw
                else:
                    time.sleep(0.01)

    def close(self):
        try:
            if self._in_port is not None and self.backend_name == "rtmidi":
                self._in_port.close_port()
        finally:
            self._in_port = None
            self._in_index = None
