from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

F0 = 0xF0
F7 = 0xF7
HEADER_PREFIX = bytes([0xF0, 0x00, 0x20, 0x32, 0x00, 0x01, 0x38])
SINGLE_CMD = 0x15
BULK_CMD = 0x10
HEADER_LEN = 8
PROGRAM_LEN = 64
SINGLE_RESERVED_LEN = 1
CHECKSUM_LEN = 1

FIELDS = {
    0: "OSC1 Wave", 1: "OSC2 Wave", 2: "OSC1 PWM / Detune / FM",
    3: "OSC2 PWM", 4: "OSC1 Coarse", 5: "OSC1 Fine",
    6: "OSC2 Coarse", 7: "OSC2 Fine", 8: "OSC Balance",
    12: "Filter Frequency", 13: "Filter Resonance",
    14: "VCF Attack", 15: "VCF Decay", 16: "VCF Sustain", 17: "VCF Release",
    18: "VCA Attack", 19: "VCA Decay", 20: "VCA Sustain", 21: "VCA Release",
    22: "VCF Amount", 43: "Ring Mod On/Off", 44: "Ring Mod Amount",
    45: "Portamento Mode", 46: "Portamento Amount", 47: "LFO1 Wave",
    48: "LFO2 Wave", 49: "LFO1 Speed", 50: "LFO1 Amount",
    51: "LFO2 Speed", 52: "LFO2 Amount", 53: "LFO1 Destination",
}
WAVE_NAMES = {0: "OFF", 1: "TRI", 2: "SQUARE", 3: "PULSE", 4: "SAW", 5: "RAMP", 6: "SUPER SAW"}

# Enum label tables established by the project so far. Values without a
# confirmed name are rendered as "Unknown (0xNN)" — never invented here.
# LFO waveforms and destinations use the JT-4000M manual's first-menu entries;
# individual value names still need hardware verification (Hardware TODO).
LFO_WAVE_NAMES = {0: "OFF", 1: "TRIANGLE", 2: "SQUARE", 3: "SAWTOOTH", 4: "RANDOM"}
LFO_DEST_NAMES = {0: "NONE", 1: "VCF", 2: "VCA", 3: "OSC"}
PORTAMENTO_MODE_NAMES = {0: "OFF"}


def checksum(data: bytes) -> int:
    """JT-4000M observed 7-bit two's-complement checksum."""
    return (-sum(data)) & 0x7F


def _check_common(raw: bytes) -> None:
    if len(raw) < HEADER_LEN + 2 or raw[0] != F0 or raw[-1] != F7:
        raise ValueError("Not a complete JT-4000M SysEx message (missing F0/F7).")
    if raw[:7] != HEADER_PREFIX:
        raise ValueError(f"Unexpected JT-4000M manufacturer/header prefix: {raw[:7].hex(' ')}")
    if any(b > 0x7F for b in raw[1:-1]):
        raise ValueError("SysEx data contains a non-7-bit byte.")


@dataclass(frozen=True)
class Program:
    index: int
    data: bytes
    source_offset: int

    @property
    def name(self) -> str:
        # The 9-byte name occupies relative offsets 55..63.
        return self.data[55:64].decode("ascii", errors="replace").rstrip(" \x00")

    def byte(self, offset: int) -> int:
        return self.data[offset]


@dataclass(frozen=True)
class SysExFile:
    raw: bytes
    mode: str
    header: bytes
    programs: tuple[Program, ...]
    checksum_value: int
    checksum_expected: int
    checksum_ok: bool
    reserved: bytes = b""


def parse(raw: bytes) -> SysExFile:
    _check_common(raw)
    command = raw[7]
    if command == SINGLE_CMD:
        # 8 header + 64 program + 1 reserved + 1 checksum + F7 = 75 bytes.
        expected_len = HEADER_LEN + PROGRAM_LEN + 1 + CHECKSUM_LEN + 1
        if len(raw) != expected_len:
            raise ValueError(f"Single dump must be {expected_len} bytes; got {len(raw)}.")
        data = raw[8:72]
        reserved = raw[72:73]
        chk = raw[73]
        expected = checksum(data)
        return SysExFile(raw, "single", raw[:8], (Program(1, data, 8),), chk, expected, chk == expected, reserved)
    if command == BULK_CMD:
        expected_len = HEADER_LEN + 32 * PROGRAM_LEN + CHECKSUM_LEN + 1
        if len(raw) != expected_len:
            raise ValueError(f"Bulk dump must be {expected_len} bytes; got {len(raw)}.")
        payload = raw[8:8 + 32 * PROGRAM_LEN]
        chk = raw[-2]
        expected = checksum(payload)
        programs = tuple(Program(i + 1, payload[i*64:(i+1)*64], 8 + i*64) for i in range(32))
        return SysExFile(raw, "bulk", raw[:8], programs, chk, expected, chk == expected)
    raise ValueError(f"Unknown JT-4000M SysEx command 0x{command:02X}; expected 0x10 bulk or 0x15 single.")


def parse_file(path: str | Path) -> SysExFile:
    return parse(Path(path).read_bytes())


def serialize_single(program: Program | bytes, *, header: bytes | None = None, reserved: bytes = b"\x00") -> bytes:
    data = program.data if isinstance(program, Program) else bytes(program)
    if len(data) != PROGRAM_LEN:
        raise ValueError("Program data must be exactly 64 bytes.")
    h = header or HEADER_PREFIX + bytes([SINGLE_CMD])
    if len(h) != 8:
        raise ValueError("Header must be 8 bytes.")
    if len(reserved) != 1:
        raise ValueError("Single-dump reserved field must be one byte.")
    return h + data + reserved + bytes([checksum(data)]) + bytes([F7])


def serialize_bulk(programs: Iterable[Program | bytes], *, header: bytes | None = None) -> bytes:
    items = list(programs)
    if len(items) != 32:
        raise ValueError("A bulk bank must contain exactly 32 programs.")
    payload = b"".join(p.data if isinstance(p, Program) else bytes(p) for p in items)
    if len(payload) != 32 * PROGRAM_LEN:
        raise ValueError("Each program must contain exactly 64 bytes.")
    h = header or HEADER_PREFIX + bytes([BULK_CMD])
    if len(h) != 8:
        raise ValueError("Header must be 8 bytes.")
    return h + payload + bytes([checksum(payload), F7])


def field_name(offset: int) -> str:
    if 55 <= offset <= 63:
        return f"Name[{offset - 55}]"
    return FIELDS.get(offset, f"Byte 0x{offset:02X}")


def semantic_value(offset: int, value: int) -> str:
    if offset in (0, 1):
        return WAVE_NAMES.get(value, f"Unknown (0x{value:02X})")
    if offset in (47, 48):
        return LFO_WAVE_NAMES.get(value, f"Unknown (0x{value:02X})")
    if offset == 53:
        return LFO_DEST_NAMES.get(value, f"Unknown (0x{value:02X})")
    if offset == 45:
        return PORTAMENTO_MODE_NAMES.get(value, f"Unknown (0x{value:02X})")
    if offset == 43:
        return "ON" if value >= 65 else ("OFF" if value <= 64 else f"0x{value:02X}")
    if 55 <= offset <= 63:
        return repr(chr(value) if 32 <= value <= 126 else "\\x%02X" % value)
    return f"0x{value:02X}"
