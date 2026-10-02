"""Small, UI-independent bridge between JT-4000M CC packets and editor keys.

It deliberately performs no polling, threading, or Tk calls.  The GUI owns
its event loop and invokes ``decode_incoming`` for each packet it receives;
that keeps this protocol boundary deterministic and fully testable offline.
"""
from __future__ import annotations

from dataclasses import dataclass

from .midi import (cc_to_parameter, parameter_to_cc, parse_program_change,
                   program_change_to_slot)
from .model import BY_KEY
from .transport import MidiTransport, PortInfo, TransportReport


@dataclass(frozen=True)
class MidiParameterUpdate:
    """One validated editor update decoded from an incoming channel CC."""

    key: str
    value: int
    channel: int


@dataclass(frozen=True)
class MidiProgramSelect:
    """P1.22: one decoded Program Change mapped to an editor slot.

    This is SELECTION ONLY.  It carries no patch data, creates no history
    entry and never marks the session dirty.  The PC->slot mapping is the
    documented offline convention (PC 0..31 -> slot 1..32) and remains
    UNVERIFIED against physical hardware.
    """

    slot: int
    program: int
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

    def send_program_change(self, slot: int) -> TransportReport:
        """P1.25: transmit one Program Change selecting editor `slot` (1..32).

        Selection-only TX: it never touches EditorModel state, history or
        dirty flags — the model stays MIDI-free (same boundary discipline as
        ``send_parameter`` above).  The PC value comes from the existing
        documented offline convention ``slot_to_program_change`` (slot 1..32
        -> PC 0..31); invalid slots raise ValueError before any transmission.
        The returned TransportReport is TX-level only: ``device_response``
        stays NOT VERIFIED — transport success NEVER proves the synth
        changed program.
        """
        from .midi import slot_to_program_change

        program = slot_to_program_change(slot)   # validates slot 1..32 first
        if self.output is None:
            raise RuntimeError("No MIDI output is selected.")
        return self.transport.send_program_change(self.output, self.channel,
                                                  program)

    def decode_program_change(self, data: bytes) -> MidiProgramSelect | None:
        """P1.22: decode one incoming Program Change into a slot selection.

        Returns None — never raises — for anything that is not a
        well-formed 0xCn packet on the bridge's channel, and for PC values
        outside the documented 0..31 range (no invented 32..127 mapping).
        The result is SELECTION ONLY; callers must apply it via
        EditorModel.select_patch(), which does not touch history/dirty/bank.
        """
        change = parse_program_change(data)
        if change is None or change.channel != self.channel:
            return None
        slot = program_change_to_slot(change.program)
        if slot is None:
            return None
        return MidiProgramSelect(slot=slot, program=change.program,
                                 channel=change.channel)
