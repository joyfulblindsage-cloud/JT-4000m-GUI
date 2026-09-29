from __future__ import annotations
from dataclasses import dataclass
from typing import Any

from .syx import Program, WAVE_NAMES, field_name, semantic_value


@dataclass(frozen=True)
class ParameterSpec:
    key: str
    label: str
    offset: int | None
    cc: int | None = None
    kind: str = "continuous"
    minimum: int = 0
    maximum: int = 127
    orientation: str = "0-based"
    confidence: str = "working"
    notes: str = ""


# SysEx offsets come from the current project semantic map. MIDI CC values are
# documented independently by Behringer and the MIDI Guide database. Where a
# CC exists but its SysEx offset is not yet established, offset stays None.
PARAMETERS: tuple[ParameterSpec, ...] = (
    ParameterSpec("modulation", "Modulation", None, 1, "continuous", notes="SysEx offset not yet established"),
    ParameterSpec("portamento_time", "Portamento Time", None, 5, "continuous", notes="SysEx offset not yet established"),
    ParameterSpec("osc_balance", "OSC Balance", 8, 29),
    ParameterSpec("osc1_wave", "OSC1 Wave", 0, 24, "enum"),
    ParameterSpec("osc1_pwm_fm", "OSC1 PWM / Supersaw Detune / FM Feedback", 2, 113),
    ParameterSpec("osc1_coarse", "OSC1 Coarse Tune", 4, 115, "continuous", orientation="centered"),
    ParameterSpec("osc1_fine", "OSC1 Fine Tune", 5, 111, "continuous", orientation="centered"),
    ParameterSpec("osc2_wave", "OSC2 Wave", 1, 25, "enum"),
    ParameterSpec("osc2_pwm", "OSC2 PWM", 3, 114),
    ParameterSpec("osc2_coarse", "OSC2 Coarse Tune", 6, 116, "continuous", orientation="centered"),
    ParameterSpec("osc2_fine", "OSC2 Fine Tune", 7, 112, "continuous", orientation="centered"),
    ParameterSpec("filter_cutoff", "VCF Cutoff", 12, 74),
    ParameterSpec("filter_resonance", "VCF Resonance", 13, 71),
    ParameterSpec("filter_env_amount", "Filter Envelope Amount", 22, 47),
    ParameterSpec("vcf_attack", "VCF EG Attack", 14, 85),
    ParameterSpec("vcf_decay", "VCF EG Decay", 15, 86),
    ParameterSpec("vcf_sustain", "VCF EG Sustain", 16, 87),
    ParameterSpec("vcf_release", "VCF EG Release", 17, 88),
    ParameterSpec("vca_attack", "VCA EG Attack", 18, 81),
    ParameterSpec("vca_decay", "VCA EG Decay", 19, 82),
    ParameterSpec("vca_sustain", "VCA EG Sustain", 20, 83),
    ParameterSpec("vca_release", "VCA EG Release", 21, 84),
    ParameterSpec("ring_mod_amount", "Ring Modulation Amount", 44, 95),
    ParameterSpec("ring_mod_toggle", "Ring Modulation On/Off", 43, 96, "boolean", notes="CC 0-64 off, 65-127 on"),
    ParameterSpec("portamento_mode", "Portamento Mode", 45, None, "enum", notes="CC mapping not established"),
    ParameterSpec("lfo1_wave", "LFO1 Wave", 47, 54, "enum"),
    ParameterSpec("lfo2_wave", "LFO2 Wave", 48, 55, "enum"),
    ParameterSpec("lfo1_rate", "LFO1 Rate", 49, 72),
    ParameterSpec("lfo1_amount", "LFO1 Amount", 50, 70),
    ParameterSpec("lfo2_rate", "LFO2 Rate", 51, 73),
    ParameterSpec("lfo2_amount", "LFO2 Amount", 52, 28),
    ParameterSpec("lfo1_destination", "LFO1 Destination", 53, 56, "enum"),
)

BY_KEY = {p.key: p for p in PARAMETERS}
BY_OFFSET = {p.offset: p for p in PARAMETERS if p.offset is not None}
BY_CC = {p.cc: p for p in PARAMETERS if p.cc is not None}


def parameter_specs() -> tuple[ParameterSpec, ...]:
    return PARAMETERS


def decode_program(program: Program) -> dict[str, Any]:
    out: dict[str, Any] = {"name": program.name}
    for spec in PARAMETERS:
        if spec.offset is None:
            continue
        value = program.data[spec.offset]
        out[spec.key] = value
        out[f"{spec.key}_display"] = semantic_value(spec.offset, value)
    return out


def set_parameter(program: Program, key: str, value: int) -> Program:
    spec = BY_KEY.get(key)
    if spec is None:
        raise KeyError(f"Unknown parameter: {key}")
    if spec.offset is None:
        raise ValueError(f"Parameter {key} has no established SysEx offset.")
    if not spec.minimum <= value <= spec.maximum:
        raise ValueError(f"{key} must be between {spec.minimum} and {spec.maximum}.")
    data = bytearray(program.data)
    data[spec.offset] = value
    return Program(program.index, bytes(data), program.source_offset)


def set_name(program: Program, name: str) -> Program:
    encoded = name.encode("ascii", errors="strict")
    if len(encoded) > 9:
        raise ValueError("Patch name must be at most 9 ASCII characters.")
    data = bytearray(program.data)
    data[55:64] = encoded.ljust(9, b" ")
    return Program(program.index, bytes(data), program.source_offset)
