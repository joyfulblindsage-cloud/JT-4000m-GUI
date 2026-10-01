from __future__ import annotations
from dataclasses import dataclass

from .model import BY_CC, ParameterSpec


@dataclass(frozen=True)
class CCMessage:
    channel: int
    controller: int
    value: int

    def bytes(self) -> bytes:
        if not 1 <= self.channel <= 16:
            raise ValueError("MIDI channel must be 1..16.")
        if not 0 <= self.controller <= 127:
            raise ValueError("MIDI CC number must be 0..127.")
        if not 0 <= self.value <= 127:
            raise ValueError("MIDI CC value must be 0..127.")
        return bytes([0xB0 | (self.channel - 1), self.controller, self.value])


@dataclass(frozen=True)
class ProgramChange:
    """One MIDI Program Change message (status 0xCn).

    `channel` is 1-based (editor convention), `program` is the raw MIDI
    value 0..127.  P1.22: this is a transport-level representation only —
    it carries no claim about which slot the physical JT-4000M selects.
    """

    channel: int
    program: int

    @property
    def bytes(self) -> bytes:
        if not 1 <= self.channel <= 16:
            raise ValueError("MIDI channel must be 1..16.")
        if not 0 <= self.program <= 127:
            raise ValueError("Program number must be 0..127.")
        return bytes((0xC0 | (self.channel - 1), self.program))


def make_program_change(channel: int, program: int) -> ProgramChange:
    return ProgramChange(channel, program)


def parse_program_change(data: bytes) -> ProgramChange | None:
    """Return a ProgramChange for one exact 0xCn status byte packet.

    Returns None for anything that is not a well-formed two-byte program
    change on some channel.  No guessing, no partial matching.
    """
    if len(data) != 2 or data[0] & 0xF0 != 0xC0:
        return None
    return ProgramChange(channel=(data[0] & 0x0F) + 1, program=data[1])


# ---- P1.22: PC -> editor slot mapping --------------------------------------
# The project has NO hardware evidence for how the physical JT-4000M maps
# incoming Program Change numbers to its 32 slots.  What IS documented in
# this repository is the editor-side invariant: a bank always contains
# exactly 32 programs, EditorModel slots are 1..32, and MIDI PC values are
# 0-based.  We therefore adopt the minimal 0-based->1-based convention:
#     PC 0..31  ->  slot 1..32
#     PC 32..127 -> unmapped (rejected; never silently clamped/wrapped)
# This is an ASSUMPTION pending hardware verification (P1.22 §12): do not
# promote it to confirmed protocol knowledge without device evidence.
JT4000M_PROGRAM_COUNT = 32


def program_change_to_slot(program: int) -> int | None:
    """Map a MIDI PC value to an editor slot index, or None if unmapped."""
    if 0 <= program < JT4000M_PROGRAM_COUNT:
        return program + 1
    return None


def slot_to_program_change(slot: int) -> int:
    """Inverse of program_change_to_slot for valid editor slots 1..32."""
    if not 1 <= slot <= JT4000M_PROGRAM_COUNT:
        raise ValueError(f"Editor slot must be 1..{JT4000M_PROGRAM_COUNT}.")
    return slot - 1


def make_cc(channel: int, controller: int, value: int) -> CCMessage:
    return CCMessage(channel, controller, value)


def parameter_to_cc(key: str, value: int, channel: int = 1) -> CCMessage:
    from .model import BY_KEY
    spec = BY_KEY.get(key)
    if spec is None:
        raise KeyError(f"Unknown parameter: {key}")
    if spec.cc is None:
        raise ValueError(f"Parameter {key} has no established MIDI CC mapping.")
    if not spec.minimum <= value <= spec.maximum:
        raise ValueError(f"{key} must be between {spec.minimum} and {spec.maximum}.")
    return CCMessage(channel, spec.cc, value)


def parameter_for_cc(controller: int) -> ParameterSpec | None:
    return BY_CC.get(controller)


def cc_to_parameter(controller: int, value: int) -> tuple[str, int] | None:
    spec = parameter_for_cc(controller)
    if spec is None:
        return None
    if not 0 <= value <= 127:
        raise ValueError("MIDI CC value must be 0..127.")
    # The device's documented CC convention for this one boolean is a
    # threshold, while its SysEx record stores the canonical 0/1 value.
    # Convert at this boundary so a received physical knob/button event can
    # always be applied through the same validated editor model as an offline
    # SysEx edit.
    if spec.key == "ring_mod_toggle":
        value = 0 if value <= 64 else 1
    return spec.key, value
