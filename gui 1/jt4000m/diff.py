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
