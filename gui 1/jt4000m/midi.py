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
