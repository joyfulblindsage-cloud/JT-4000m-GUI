from __future__ import annotations
from dataclasses import dataclass
from .syx import SysExFile, field_name, semantic_value

@dataclass(frozen=True)
class ByteDiff:
    absolute_offset: int
    relative_offset: int
    program: int | None
    old: int
    new: int
    field: str


def raw_diff(a: SysExFile, b: SysExFile) -> list[ByteDiff]:
    if len(a.raw) != len(b.raw):
        raise ValueError(f"Raw files have different sizes: {len(a.raw)} vs {len(b.raw)}")
    out=[]
    for i,(x,y) in enumerate(zip(a.raw,b.raw)):
        if x == y: continue
        program = relative = None
        field = "Service"
        if a.mode == b.mode == "bulk" and 8 <= i < 8 + 32*64:
            n=i-8; program=n//64+1; relative=n%64
            field=field_name(relative)
        elif a.mode == b.mode == "single" and 8 <= i < 8 + 64:
            program = 1; relative = i-8; field=field_name(relative)
        elif i < 8:
            field = "Header"
        elif i == len(a.raw)-1:
            field = "F7"
        elif i == len(a.raw)-2:
            field = "Checksum"
        elif a.mode == "single" and i == 72:
            field = "Reserved"
        out.append(ByteDiff(i, relative, program, x,y,field))
    return out


def semantic_diff(a: SysExFile, b: SysExFile) -> list[ByteDiff]:
    if len(a.programs) != len(b.programs):
        raise ValueError("Cannot semantic-diff single and bulk dumps; both files must have the same program count.")
    out=[]
    for pa,pb in zip(a.programs,b.programs):
        if pa.data == pb.data: continue
        for rel,(x,y) in enumerate(zip(pa.data,pb.data)):
            if x != y:
                out.append(ByteDiff(pb.source_offset+rel,rel,pa.index,x,y,field_name(rel)))
    return out


def format_change(d: ByteDiff) -> str:
    old = semantic_value(d.relative_offset, d.old)
    new = semantic_value(d.relative_offset, d.new)
    if 55 <= d.relative_offset <= 63:
        return f"{old} -> {new}"
    delta = d.new - d.old
    return f"{old} -> {new} (Δ {delta:+d})"


# --------------------------------------------------------------------------
# P1 — program/bank comparison helpers built on the SAME ByteDiff/formatting
# logic as semantic_diff above. No second diff system is introduced.
# --------------------------------------------------------------------------

def _as_program(obj):
    """Accept a syx.Program or a patch.JTProgram without importing patch."""
    to_program = getattr(obj, "to_program", None)
    return to_program() if callable(to_program) else obj


def program_diff(a, b) -> list[ByteDiff]:
    """Byte-level differences between two programs (raw records preserved).

    Uses the existing field_name()/semantic_value() mapping so unknown bytes
    are reported as 'Byte 0xNN' — never renamed into invented parameters.
    """
    pa, pb = _as_program(a), _as_program(b)
    out = []
    for rel, (x, y) in enumerate(zip(pa.data, pb.data)):
        if x != y:
            out.append(ByteDiff(pb.source_offset + rel, rel, pa.index, x, y,
                                field_name(rel)))
    return out


def bank_diff(a, b) -> list[ByteDiff]:
    """Per-slot differences between two 32-program banks.

    Accepts Bank objects (patch.Bank) or SysExFile bulk dumps; both sides
    must have the same number of programs.
    """
    progs_a = a.programs
    progs_b = b.programs
    if len(progs_a) != len(progs_b):
        raise ValueError(
            f"Cannot compare banks with different program counts: {len(progs_a)} vs {len(progs_b)}.")
    out = []
    for pqa, pqb in zip(progs_a, progs_b):
        da, db = _as_program(pqa), _as_program(pqb)
        if da.data == db.data:
            continue
        for rel, (x, y) in enumerate(zip(da.data, db.data)):
            if x != y:
                out.append(ByteDiff(db.source_offset + rel, rel, da.index, x, y,
                                    field_name(rel)))
    return out
