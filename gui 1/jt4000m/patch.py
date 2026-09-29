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
            raise ValueError("Bank.from_sysex requires a bulk dump.")
        return cls(tuple(JTProgram.from_program(p) for p in syx.programs))

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

    def set_name(self, index: int, name: str) -> "Bank":
        return self.replace(index, self.get(index).set_name(name))

    def to_sysex(self, *, header: bytes | None = None) -> bytes:
        return serialize_bulk(tuple(p.to_program() for p in self.programs), header=header)

    @classmethod
    def load(cls, path: str) -> "Bank":
        from .syx import parse_file
        return cls.from_sysex(parse_file(path))


def program_to_single(program: JTProgram, *, header: bytes | None = None, reserved: bytes = b"\x00") -> bytes:
    return serialize_single(program.to_program(), header=header, reserved=reserved)
