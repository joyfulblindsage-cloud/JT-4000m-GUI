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
# ---------------------------------------------------------------------------
# NAME FIELD BOUNDARY — fixture-verified (offline evidence, not hardware).
# The patch name occupies the LAST NINE bytes of the 64-byte program record:
# offsets 55..63 (0x37..0x3F).  NAME_START == PROGRAM_LEN - 9 == 55.
# Evidence (every .syx fixture in this repository, all 97 program records):
#   * ALL INIT SAW / EMPTY tails:  ... 00 00 01 | 00 | 'I' 'N' 'I' 'T' ' '
#     'S' 'A' 'W' ' '  — the trailing printable run ending at index 63
#     always STARTS at index 55.
#   * Synthmania: 'HOOLLEAD' likewise starts at 55.
#   * Byte 54 (0x36) is 0x00 in EVERY fixture program: it is a structural
#     zero byte, NOT part of the name and NOT a registry parameter
#     (FIXTURE-CONSTANT / UNKNOWN status; do not interpret its meaning
#     without hardware evidence).
#   * Byte 53 (0x35) is LFO1 Destination per the project FIELDS map
#     (values {0,1} observed); it is also not part of the name.
# A previous close-out attempt briefly moved the window to 54..63 on a
# miscounted comment ("PROGRAM_LEN - 9 == 54"); that was arithmetically
# wrong (64-9 == 55) and caused garbled/truncated names.  Do not repeat it.
# See tests/test_p19_api.py::TestNameBoundaryRawBytes for the raw-level
# regression guard over all fixtures.
# ---------------------------------------------------------------------------
NAME_START = PROGRAM_LEN - 9   # == 55 == 0x37 (first name byte)
NAME_END = PROGRAM_LEN         # exclusive; last name offset is 63 (0x3F)
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

# Fixture-observed wave value 0x07 appears in commercial banks (Synthmania
# 'FUNMYLEAD', 'CLAP') but has NO confirmed name anywhere in the project.
# It is deliberately left unlabelled ("Unknown (0x07)") — naming it would be
# inventing a parameter value (Hardware TODO). Recorded as an OPEN conflict by
# the P1.6 knowledge report.

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
    # Single-dump frames carry one reserved byte between the 64-byte program
    # record and the checksum (observed 0x00 in every fixture). Bulk programs
    # have no such byte; keep it here so parse -> serialize is lossless for
    # both modes without inventing any semantics for it.
    reserved: bytes = b""

    @property
    def name(self) -> str:
        # The 9-byte name occupies relative offsets 55..63 (0x37..0x3F) — the
        # LAST nine bytes of the 64-byte record.  Fixture evidence: ALL INIT
        # SAW record ends with
        #   ... 00 | 01 | 00 | 'I' 'N' 'I' 'T' ' ' 'S' 'A' 'W' ' '
        # i.e. byte 53 = LFO1 Destination, byte 54 = structural zero, and the
        # padded ASCII name starts at index 55.  Reading must use the same
        # NAME_START boundary as writing (model.set_name); a previous close-
        # out left this docstring claiming 54..63 while the slice itself was
        # already correct — keep read/write boundaries in lockstep or 9-char
        # names lose their last character.
        return self.data[NAME_START:NAME_END].decode("ascii", errors="replace").rstrip(" \x00")

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
        return SysExFile(raw, "single", raw[:8], (Program(1, data, 8, reserved),), chk, expected, chk == expected, reserved)
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


def serialize_single(program: Program | bytes, *, header: bytes | None = None, reserved: bytes | None = None) -> bytes:
    data = program.data if isinstance(program, Program) else bytes(program)
    if reserved is None:
        # Use the byte captured at parse time when serializing a parsed
        # Program; fall back to the observed fixture value 0x00 otherwise.
        reserved = program.reserved if isinstance(program, Program) and program.reserved else b"\x00"
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
    # FIELDS has priority over the NAME window: fixtures show byte 0x35
    # ('LFO1 Destination', e.g. ALL INIT SAW tail ... 01 | 00 | 'INIT SAW ')
    # behaving as a parameter, while the name starts at 0x36. If the two ever
    # overlap, the registry mapping wins and this must be treated as a
    # registry contradiction (report-only), never silently reclassified.
    if offset in FIELDS:
        return FIELDS[offset]
    if NAME_START <= offset < NAME_END:
        return f"Name[{offset - NAME_START}]"
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
    if NAME_START <= offset < NAME_END:
        return repr(chr(value) if 32 <= value <= 126 else "\\x%02X" % value)
    return f"0x{value:02X}"
