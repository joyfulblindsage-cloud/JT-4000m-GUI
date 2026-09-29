from __future__ import annotations
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .model import set_name, set_parameter
from .syx import (
    BULK_CMD,
    HEADER_PREFIX,
    Program,
    SysExFile,
    serialize_bulk,
    serialize_single,
)


@dataclass(frozen=True)
class JTProgram:
    """Editable patch model that preserves the complete original 64-byte record."""
    index: int
    data: bytes
    source_offset: int = 0

    @classmethod
    def from_program(cls, program: Program) -> "JTProgram":
        return cls(program.index, bytes(program.data), program.source_offset)

    def to_program(self) -> Program:
        return Program(self.index, bytes(self.data), self.source_offset)

    @property
    def name(self) -> str:
        return self.to_program().name

    def get_parameter(self, key: str) -> int:
        from .model import get_parameter
        return get_parameter(self.to_program(), key)

    def set_parameter(self, key: str, value: int) -> "JTProgram":
        p = set_parameter(self.to_program(), key, value)
        return JTProgram.from_program(p)

    def reset_parameter(self, key: str) -> "JTProgram":
        from .model import reset_parameter
        return JTProgram.from_program(reset_parameter(self.to_program(), key))

    def set_name(self, name: str) -> "JTProgram":
        p = set_name(self.to_program(), name)
        return JTProgram.from_program(p)


@dataclass(frozen=True)
class Bank:
    """A 32-program JT-4000M bank with immutable patch records."""
    programs: tuple[JTProgram, ...]
    # The exact 8-byte SysEx header captured from the file this bank was
    # loaded from (F0 00 20 32 <dev> <cmd...>). Saved banks reuse it so the
    # output frame is byte-for-byte compatible with the input format.
    # Defaults to the standard bulk header for freshly created banks.
    source_header: bytes = HEADER_PREFIX + bytes([BULK_CMD])

    def __post_init__(self) -> None:
        if len(self.programs) != 32:
            raise ValueError("A JT-4000M bank must contain exactly 32 programs.")
        if len(self.source_header) != 8 or self.source_header[0] != 0xF0 or self.source_header[7] != BULK_CMD:
            raise ValueError("source_header must be an 8-byte bulk dump header ending in command 0x10.")
        for i, p in enumerate(self.programs, 1):
            if p.index != i:
                raise ValueError(f"Program indices must be 1..32; got {p.index} at position {i}.")
            if len(p.data) != 64:
                raise ValueError(f"Program {p.index} must contain exactly 64 bytes.")

    @classmethod
    def from_sysex(cls, syx: SysExFile) -> "Bank":
        if syx.mode != "bulk":
            raise ValueError(
                "Bank.from_sysex requires a bulk (32-program) dump; "
                f"got mode '{syx.mode}'. Open a single .syx as a program instead."
            )
        return cls(tuple(JTProgram.from_program(p) for p in syx.programs),
                   source_header=syx.header)

    @classmethod
    def from_program(cls, program: Program) -> "Bank":
        """Build a full 32-slot bank around one single-dump program.

        The program is placed at its own slot index; the remaining slots are
        filled with the observed all-zero record (same layout Bank.empty()
        uses). Software-only convenience so single dumps can be shown in the
        32-preset list without inventing any hardware behaviour.
        """
        bank = cls.empty()
        jt = JTProgram.from_program(program)
        return bank._replace_slot(jt.index, jt)

    def get(self, index: int) -> JTProgram:
        if not 1 <= index <= 32:
            raise IndexError("Program index must be 1..32.")
        return self.programs[index - 1]

    def replace(self, index: int, program: JTProgram) -> "Bank":
        """Return a new bank with one slot replaced.

        The source header is preserved so an edited loaded bank still saves
        back in exactly the frame format it came from.
        """
        return self._replace_slot(index, program)

    def _replace_slot(self, index: int, program: JTProgram) -> "Bank":
        if not 1 <= index <= 32:
            raise IndexError("Program index must be 1..32.")
        if program.index != index:
            program = JTProgram(index, program.data, program.source_offset)
        items = list(self.programs)
        items[index - 1] = program
        return Bank(tuple(items), source_header=self.source_header)

    def get_parameter(self, index: int, key: str) -> int:
        return self.get(index).get_parameter(key)

    def set_parameter(self, index: int, key: str, value: int) -> "Bank":
        return self.replace(index, self.get(index).set_parameter(key, value))

    def reset_parameter(self, index: int, key: str) -> "Bank":
        return self.replace(index, self.get(index).reset_parameter(key))

    def set_name(self, index: int, name: str) -> "Bank":
        return self.replace(index, self.get(index).set_name(name))

    def copy_program(self, source: int, target: int) -> "Bank":
        """Duplicate one program's data into another slot (software only)."""
        return self.replace(target, JTProgram(target, self.get(source).data, self.get(target).source_offset))

    @classmethod
    def empty(cls) -> "Bank":
        """A fresh 32-slot bank filled with the observed all-zero INIT record."""
        blank = bytes(64)
        return cls(tuple(JTProgram(i, blank, 8 + (i - 1) * 64) for i in range(1, 33)))

    def to_sysex(self, *, header: bytes | None = None) -> bytes:
        """Serialize the bank as a bulk dump preserving the original layout.

        The 8-byte header captured at load time (including any non-default
        device-ID bytes) is reused automatically, so an edited bank round-trips
        with the exact same frame structure; only the payload and the checksum
        change. The checksum is recomputed by ``serialize_bulk`` using the
        existing observed algorithm — nothing about the SYX format is invented.
        """
        if header is None:
            header = self.source_header
        return serialize_bulk(tuple(p.to_program() for p in self.programs), header=header)

    def save(self, path) -> bytes:
        """Write the bank to a local .syx file (software-only, no MIDI).

        Uses an atomic write-to-temp-then-rename strategy so a failed or
        interrupted save can never leave a half-written file behind. Returns
        the exact bytes written. The payload is re-parsed before writing so
        we never persist something our own parser would reject.
        """
        from .syx import parse
        payload = self.to_sysex()
        parse(payload)  # regression guard: what we write must be parseable
        path = Path(path)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent or "."), suffix=".syx.tmp")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, str(path))
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return payload

    @classmethod
    def load(cls, path: str) -> "Bank":
        """Load a local .syx file (no MIDI).

        Bulk files produce a real 32-program bank. Single-dump files produce a
        32-slot bank containing that program at its slot (see from_program),
        so callers always receive a complete bank model.
        """
        from .syx import parse_file
        syx = parse_file(path)
        if syx.mode == "bulk":
            return cls.from_sysex(syx)
        return cls.from_program(syx.programs[0])


def program_to_single(program: JTProgram, *, header: bytes | None = None, reserved: bytes = b"\x00") -> bytes:
    return serialize_single(program.to_program(), header=header, reserved=reserved)
