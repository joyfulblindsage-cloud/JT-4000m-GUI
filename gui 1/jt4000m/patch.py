from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable

from .model import set_name, set_parameter
from .syx import Program, SysExFile, serialize_bulk, serialize_single


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

    def __post_init__(self) -> None:
        if len(self.programs) != 32:
            raise ValueError("A JT-4000M bank must contain exactly 32 programs.")
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
        return cls(tuple(JTProgram.from_program(p) for p in syx.programs))

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
        return bank.replace(jt.index, jt)

    def get(self, index: int) -> JTProgram:
        if not 1 <= index <= 32:
            raise IndexError("Program index must be 1..32.")
        return self.programs[index - 1]

    def replace(self, index: int, program: JTProgram) -> "Bank":
        if not 1 <= index <= 32:
            raise IndexError("Program index must be 1..32.")
        if program.index != index:
            program = JTProgram(index, program.data, program.source_offset)
        items = list(self.programs)
        items[index - 1] = program
        return Bank(tuple(items))

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
        return serialize_bulk(tuple(p.to_program() for p in self.programs), header=header)

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
