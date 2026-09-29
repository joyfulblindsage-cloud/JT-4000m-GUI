"""Small, UI-independent bridge between JT-4000M CC packets and editor keys.

It deliberately performs no polling, threading, or Tk calls.  The GUI owns
its event loop and invokes ``decode_incoming`` for each packet it receives;
that keeps this protocol boundary deterministic and fully testable offline.
"""
from __future__ import annotations

from dataclasses import dataclass

from .midi import cc_to_parameter, parameter_to_cc
from .model import BY_KEY
from .transport import MidiTransport, PortInfo, TransportReport


@dataclass(frozen=True)
class MidiParameterUpdate:
    """One validated editor update decoded from an incoming channel CC."""

    key: str
    value: int
    channel: int


class MidiSyncBridge:
    """Translate only established, channel-matching parameter CC messages."""

    def __init__(self, transport: MidiTransport, *, channel: int = 1,
                 output: PortInfo | None = None):
        if not 1 <= channel <= 16:
            raise ValueError("MIDI channel must be 1..16.")
        self.transport = transport
        self.channel = channel
        self.output = output

    def send_parameter(self, key: str, value: int) -> TransportReport | None:
        """Transmit an established CC mapping, or return None for SysEx-only keys."""
        spec = BY_KEY.get(key)
        if spec is None:
            raise KeyError(f"Unknown parameter: {key}")
        if spec.cc is None:
            return None
        message = parameter_to_cc(key, value, self.channel)
        if self.output is None:
            raise RuntimeError("No MIDI output is selected.")
        return self.transport.send_cc(self.output, message.channel,
                                      message.controller, message.value)

    def decode_incoming(self, data: bytes) -> MidiParameterUpdate | None:
        """Return a model-safe update for one matching three-byte CC packet.

        Other MIDI traffic, other channels and unknown CCs are intentionally
        ignored: they must never mutate the current patch accidentally.
        """
        if len(data) != 3 or data[0] & 0xF0 != 0xB0:
            return None
        channel = (data[0] & 0x0F) + 1
        if channel != self.channel:
            return None
        decoded = cc_to_parameter(data[1], data[2])
        if decoded is None:
            return None
        key, value = decoded
        return MidiParameterUpdate(key, value, channel)
