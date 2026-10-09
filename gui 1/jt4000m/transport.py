"""P1.5 — minimal hardware MIDI transport abstraction (OFFLINE-safe).

This module is a thin façade over the EXISTING project backends; it adds no
new MIDI library and reimplements no MIDI I/O:

  * Windows: try jt4000m.midi_winmm first, then optional python-rtmidi if
    WinMM cannot be loaded;
  * other platforms: optional python-rtmidi if installed.
  If neither backend is available, the transport reports that honestly.

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


def _load_backend(platform: str | None = None):
    """Return (backend_name, backend_module_or_None, note).

    On Windows prefer the native backend, but fall back to python-rtmidi if
    WinMM cannot be imported. The platform argument is injectable for tests.
    """
    import importlib
    import os

    platform = platform or os.name
    failures = []
    if platform == "nt":
        try:
            be = importlib.import_module(f"{__package__}.midi_winmm")
            return "winmm", be, ""
        except Exception as exc:  # pragma: no cover - Windows-only path
            failures.append(f"winmm unavailable: {exc}")

    try:  # optional, never required for offline analysis or tests
        be = importlib.import_module("rtmidi")
        note = "; ".join(failures)
        if note:
            note += "; using python-rtmidi fallback"
        return "rtmidi", be, note
    except Exception as exc:
        failures.append(f"python-rtmidi unavailable: {exc}")
        return "none", None, (
            "no MIDI backend available (" + "; ".join(failures) +
            "). Offline analysis commands still work."
        )


class MidiTransport:
    """Backend-agnostic list/open/send/receive operations.

    Construction is always safe (no device access). Opening ports and sending
    are explicit user actions from the GUI or CLI — never from unit tests.

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
        self._out_port = None
        self._out_index: int | None = None

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
        if self._out_port is not None and self._out_index == port.index:
            return self._out_port
        if self._out_port is not None:
            try:
                self._out_port.close_port()
            finally:
                self._out_port = None
                self._out_index = None
        handle = self._be.MidiOut()
        handle.open_port(port.index)
        self._out_port, self._out_index = handle, port.index
        return handle

    def open_input(self, port: PortInfo):
        if not self.available:
            raise RuntimeError(self.note or "no MIDI backend available")
        if self.backend_name == "winmm":
            handle = self._be.open_input(port.index)
        else:
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

    def send_program_change(self, port: PortInfo, channel: int,
                            program: int) -> TransportReport:
        """P1.25: TX one Program Change through the SAME backend dispatch as
        ``send_cc`` (winmm short message / rtmidi-shaped backend).

        Encoding/validation reuse the existing ``midi.ProgramChange`` — no new
        abstraction.  Like every send*() here, the report is TX-level only:
        api_ok means the MIDI API accepted the bytes, device_response stays
        NOT VERIFIED.
        """
        from .midi import make_program_change
        msg = make_program_change(channel, program)  # validates ranges
        data = msg.bytes
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
        return TransportReport("program_change", port, data, ok, err)

    # ---------------------------------------------------------------- receive
    def receive(self, timeout: float = 10.0,
                on_message: Callable[[float, bytes], None] | None = None
                ) -> Iterator[tuple[float, bytes]]:
        """Yield queued short MIDI and SysEx messages until timeout.

        Both backends expose a non-blocking get_message method. WinMM's
        native callback only queues data; this polling path performs decoding
        and keeps GUI work on the Tk thread.
        """
        if not self.available:
            raise RuntimeError(self.note or "no MIDI backend available")
        dev = self._in_port
        if dev is None:
            raise RuntimeError("No MIDI input is open.")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            msg = dev.get_message()
            if msg:
                _delta, data = msg
                raw = bytes(data)
                ts = time.time()
                if on_message:
                    on_message(ts, raw)
                yield ts, raw
            else:
                time.sleep(0.01)

    def close(self):
        try:
            if self._in_port is not None:
                if self.backend_name == "winmm":
                    self._in_port.close()
                else:
                    self._in_port.close_port()
        finally:
            self._in_port = None
            self._in_index = None
            if self._out_port is not None and self.backend_name == "rtmidi":
                try:
                    self._out_port.close_port()
                finally:
                    self._out_port = None
                    self._out_index = None
