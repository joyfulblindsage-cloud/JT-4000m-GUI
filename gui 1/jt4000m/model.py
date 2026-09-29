from __future__ import annotations
from dataclasses import dataclass
from typing import Any

from .syx import (LFO_DEST_NAMES, LFO_WAVE_NAMES, NAME_END, NAME_START,
                  PORTAMENTO_MODE_NAMES, Program, WAVE_NAMES, field_name,
                  semantic_value)

# Enum value -> label maps. These only contain values established by the
# project's analysis; unknown values render as "Unknown (0xNN)" in the UI.
# NOTE: CC numbers on ParameterSpec below are documentation carried over from
# the existing parameter map; this editor NEVER sends MIDI and does not treat
# them as verified beyond what the project already recorded.
ENUM_OPTIONS: dict[str, dict[int, str]] = {
    "osc1_wave": WAVE_NAMES,
    "osc2_wave": WAVE_NAMES,
    "lfo1_wave": LFO_WAVE_NAMES,
    "lfo2_wave": LFO_WAVE_NAMES,
    "lfo1_destination": LFO_DEST_NAMES,
    "portamento_mode": PORTAMENTO_MODE_NAMES,
    # Ring Mod toggle: banks observed so far store clean 0/1 values here.
    # The manual-style split (<=64 OFF / >=65 ON) is kept for raw-value
    # display; individual >1 values still render as Unknown (0xNN).
    "ring_mod_toggle": {0: "OFF", 1: "ON"},
}


@dataclass(frozen=True)
class ParameterSpec:
    key: str
    label: str
    offset: int | None
    cc: int | None = None
    kind: str = "continuous"
    minimum: int = 0
    maximum: int = 127
    default: int = 0
    orientation: str = "0-based"
    confidence: str = "working"
    notes: str = ""
    section: str = "OTHER"


# SysEx offsets come from the current project semantic map. MIDI CC values are
# documented independently by Behringer and the MIDI Guide database. Where a
# CC exists but its SysEx offset is not yet established, offset stays None.
PARAMETERS: tuple[ParameterSpec, ...] = (
    ParameterSpec("osc1_wave", "OSC1 Wave", 0, 24, "enum", section="OSCILLATORS"),
    ParameterSpec("osc2_wave", "OSC2 Wave", 1, 25, "enum", default=0, section="OSCILLATORS"),
    ParameterSpec("osc1_pwm_fm", "OSC1 PWM / Supersaw Detune / FM Feedback", 2, 113, section="OSCILLATORS", default=64),
    ParameterSpec("osc2_pwm", "OSC2 PWM", 3, 114, section="OSCILLATORS", default=64),
    ParameterSpec("osc_balance", "OSC Balance", 8, 29, section="OSCILLATORS", default=64),
    ParameterSpec("osc1_coarse", "OSC1 Coarse Tune", 4, 115, "continuous", orientation="centered", section="OSCILLATORS"),
    ParameterSpec("osc1_fine", "OSC1 Fine Tune", 5, 111, "continuous", orientation="centered", section="OSCILLATORS"),
    ParameterSpec("osc2_coarse", "OSC2 Coarse Tune", 6, 116, "continuous", orientation="centered", section="OSCILLATORS"),
    ParameterSpec("osc2_fine", "OSC2 Fine Tune", 7, 112, "continuous", orientation="centered", section="OSCILLATORS"),
    # NOTE: the duplicate osc_balance entry (offset 8) was removed here; it was
    # a data conflict recorded in the P1.6 knowledge report CONFLICTS section.
    ParameterSpec("filter_cutoff", "VCF Cutoff", 12, 74, section="FILTER"),
    ParameterSpec("filter_resonance", "VCF Resonance", 13, 71, section="FILTER"),
    ParameterSpec("filter_env_amount", "Filter Envelope Amount", 22, 47, section="FILTER"),
    ParameterSpec("vcf_attack", "VCF EG Attack", 14, 85, section="VCF ENVELOPE"),
    ParameterSpec("vcf_decay", "VCF EG Decay", 15, 86, section="VCF ENVELOPE"),
    ParameterSpec("vcf_sustain", "VCF EG Sustain", 16, 87, section="VCF ENVELOPE"),
    ParameterSpec("vcf_release", "VCF EG Release", 17, 88, section="VCF ENVELOPE"),
    ParameterSpec("vca_attack", "VCA EG Attack", 18, 81, section="VCA ENVELOPE"),
    ParameterSpec("vca_decay", "VCA EG Decay", 19, 82, section="VCA ENVELOPE"),
    ParameterSpec("vca_sustain", "VCA EG Sustain", 20, 83, section="VCA ENVELOPE"),
    ParameterSpec("vca_release", "VCA EG Release", 21, 84, section="VCA ENVELOPE"),
    ParameterSpec("lfo1_wave", "LFO1 Wave", 47, 54, "enum", section="LFO"),
    ParameterSpec("lfo2_wave", "LFO2 Wave", 48, 55, "enum", section="LFO"),
    ParameterSpec("lfo1_rate", "LFO1 Rate", 49, 72, section="LFO"),
    ParameterSpec("lfo1_amount", "LFO1 Amount", 50, 70, section="LFO"),
    ParameterSpec("lfo2_rate", "LFO2 Rate", 51, 73, section="LFO"),
    ParameterSpec("lfo2_amount", "LFO2 Amount", 52, 28, section="LFO"),
    ParameterSpec("lfo1_destination", "LFO1 Destination", 53, 56, "enum", section="LFO"),
    # Observed banks store clean 0/1 values at offset 0x2B, so the toggle is
    # exposed as an enum (OFF/ON) in the editor; the manual-style CC split
    # (0-64 off / 65-127 on) is documented in notes but not invented here.
    ParameterSpec("ring_mod_toggle", "Ring Modulation On/Off", 43, 96, "enum",
                  notes="Observed banks use 0/1; CC convention 0-64 off, 65-127 on",
                  section="MODULATION"),
    ParameterSpec("ring_mod_amount", "Ring Modulation Amount", 44, 95, section="MODULATION"),
    ParameterSpec("portamento_mode", "Portamento Mode", 45, None, "enum", notes="CC mapping not established", section="MODULATION"),
    # Offset 0x2E (46) is documented in the project field map as Portamento
    # Amount; it has no independently confirmed MIDI CC.
    ParameterSpec("portamento_amount", "Portamento Amount", 46, None, section="MODULATION"),
    # CC-only parameters: real MIDI CC numbers are documented externally, but
    # their SysEx offsets are not yet established. They stay read-only here.
    ParameterSpec("modulation", "Modulation (CC only)", None, 1, "continuous", notes="SysEx offset not yet established", section="UNMAPPED"),
    ParameterSpec("portamento_time", "Portamento Time (CC only)", None, 5, "continuous", notes="SysEx offset not yet established", section="UNMAPPED"),
)

BY_KEY = {p.key: p for p in PARAMETERS}
BY_OFFSET = {p.offset: p for p in PARAMETERS if p.offset is not None}
BY_CC = {p.cc: p for p in PARAMETERS if p.cc is not None}


def parameter_specs() -> tuple[ParameterSpec, ...]:
    return PARAMETERS


def enum_options(key: str) -> list[tuple[int, str]]:
    """Return (value, label) pairs for an enum parameter.

    Only values established by the project are labelled; unknown values are
    shown as ``Unknown (0xNN)`` instead of invented names. Enum parameters
    offer exactly the confirmed value set — no invented range is exposed in
    dropdowns. Banks containing other raw values still load and display them
    via ``display_value`` / the raw table.
    """
    labels = ENUM_OPTIONS.get(key, {})
    if not labels:
        # No confirmed enum table exists for this key: expose nothing rather
        # than inventing options. The editor falls back to numeric controls.
        return []
    return [(v, labels[v]) for v in sorted(labels)]


def display_value(key: str, raw: int) -> str:
    """Semantic display string for a raw byte value."""
    spec = BY_KEY[key]
    if spec.kind == "enum":
        labels = ENUM_OPTIONS.get(key, {})
        if raw in labels:
            return labels[raw]
        if spec.key == "ring_mod_toggle":
            # Manual-style convention documented by the project: 0-64 off,
            # 65-127 on. Individual unconfirmed values stay marked Unknown.
            side = "OFF" if raw <= 64 else "ON"
            return f"{side} (Unknown (0x{raw:02X}))"
        return f"Unknown (0x{raw:02X})"
    if spec.kind == "boolean":
        return "ON" if raw >= 65 else ("OFF" if raw <= 64 else f"0x{raw:02X}")
    if spec.orientation == "centered":
        return f"{raw - 64:+d}"
    return str(raw)


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
    if not isinstance(value, int):
        raise ValueError(f"{key} must be an integer.")
    if not spec.minimum <= value <= spec.maximum:
        raise ValueError(f"{key} must be between {spec.minimum} and {spec.maximum}.")
    if spec.kind == "enum":
        # Only values established by the project's enum tables are writable.
        # Unknown/undocumented values stay visible in the raw table but cannot
        # be introduced through the editor — nothing is invented here.
        labels = ENUM_OPTIONS.get(key, {})
        if not labels:
            raise ValueError(f"{key}: no confirmed enum values exist yet (hardware TODO).")
        if value not in labels:
            raise ValueError(
                f"{key}: value {value} is not a confirmed enum option "
                f"(allowed: {sorted(labels)})."
            )
    data = bytearray(program.data)
    data[spec.offset] = value
    return Program(program.index, bytes(data), program.source_offset)


def reset_parameter(program: Program, key: str) -> Program:
    """Restore one parameter to its documented default value."""
    spec = BY_KEY[key]
    return set_parameter(program, key, spec.default)


def editable_parameters() -> tuple[ParameterSpec, ...]:
    """All parameters with an established SysEx offset (editor-visible set).

    CC-only specs (offset=None) are intentionally excluded — their SysEx
    location is not established, so they are never rendered as editable.
    """
    return tuple(p for p in PARAMETERS if p.offset is not None)


def writable_parameters() -> tuple[ParameterSpec, ...]:
    """Editable parameters the editor may actually change offline.

    Excludes enum parameters that have no confirmed value table yet (e.g.
    portamento_mode: only OFF is observed; nothing else is invented).
    (The historical osc_balance duplicate entry was removed from PARAMETERS
    in P1.6; the seen-set below stays as a cheap safety net.)
    """
    seen: set[str] = set()
    out: list[ParameterSpec] = []
    for p in editable_parameters():
        if p.key in seen:
            continue
        if p.kind == "enum" and not ENUM_OPTIONS.get(p.key):
            continue  # no confirmed enum values -> not writable (hardware TODO)
        seen.add(p.key)
        out.append(p)
    return tuple(out)


def get_parameter(program: Program, key: str) -> int:
    """Read the raw byte value of a parameter from a program."""
    spec = BY_KEY.get(key)
    if spec is None:
        raise KeyError(f"Unknown parameter: {key}")
    if spec.offset is None:
        raise ValueError(f"Parameter {key} has no established SysEx offset.")
    return program.data[spec.offset]


def set_name(program: Program, name: str) -> Program:
    # The JT-4000M name field is 9 bytes (offsets 54..63 / 0x36..0x3F — the
    # LAST nine bytes of the 64-byte record), space padded.
    # Names longer than 9 characters are truncated; non-ASCII characters are
    # replaced with '?' so every byte stays valid MIDI 7-bit data.
    raw = bytearray()
    for ch in name[:9]:
        try:
            b = ch.encode("ascii")
        except UnicodeEncodeError:
            b = b"?"
        raw.extend(b)
    data = bytearray(program.data)
    data[NAME_START:NAME_END] = bytes(raw).ljust(9, b" ")
    return Program(program.index, bytes(data), program.source_offset)
