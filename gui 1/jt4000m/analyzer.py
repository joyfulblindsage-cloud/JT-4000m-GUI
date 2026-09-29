from __future__ import annotations
from collections import Counter
from dataclasses import dataclass
from .syx import SysExFile, field_name


ENUM_OFFSETS = {0, 1, 27, 43, 45, 47, 48, 53}
TEXT_OFFSETS = set(range(55, 64))
@dataclass(frozen=True)
class OffsetStats:
    relative_offset: int
    field: str
    values: tuple[int, ...]
    unique_values: tuple[int, ...]
    changed_programs: int
    invariant: bool


def analyze_bank(bank: SysExFile) -> list[OffsetStats]:
    if bank.mode != "bulk":
        raise ValueError("Cross-bank analysis requires bulk banks.")
    rows = []
    for off in range(64):
        vals = tuple(p.data[off] for p in bank.programs)
        uniq = tuple(sorted(set(vals)))
        rows.append(
            OffsetStats(
                off,
                field_name(off),
                vals,
                uniq,
                len(uniq) > 1,
                len(uniq) == 1,
            )
        )
    return rows


def _kind(offset: int, field: str, unique_count: int, value_range: int) -> str:
    """Conservative classification based only on the supplied banks and known map."""
    if offset in TEXT_OFFSETS:
        return "TEXT"
    if field.startswith("Byte 0x"):
        return "UNKNOWN"
    if unique_count == 1:
        return "INVARIANT"
    if offset in ENUM_OFFSETS:
        return "LIKELY_ENUM"
    # Numeric synth parameters with several observed levels are treated as
    # likely continuous controls, but this remains a hypothesis until tested
    # against hardware/MIDI captures.
    if unique_count >= 4 or value_range >= 12:
        return "LIKELY_CONTINUOUS"
    return "VARIABLE"


def cross_bank(banks: list[tuple[str, SysExFile]]):
    """Build a 64-byte cross-bank map with pooled values and frequencies.

    The analyzer deliberately does not invent meanings for unknown offsets.
    All frequencies are counts across all supplied programs (normally 96
    programs for three 32-program banks), while per-bank statistics are kept
    separately for comparison.
    """
    if not banks:
        raise ValueError("No banks supplied.")
    if any(b.mode != "bulk" for _, b in banks):
        raise ValueError("All cross-bank inputs must be bulk banks.")

    result = []
    for off in range(64):
        per_bank = []
        pooled = []
        for name, bank in banks:
            vals = tuple(p.data[off] for p in bank.programs)
            counts = Counter(vals)
            per_bank.append(
                {
                    "name": name,
                    "values": vals,
                    "unique_values": tuple(sorted(counts)),
                    "frequency": dict(sorted(counts.items())),
                    "min": min(vals),
                    "max": max(vals),
                }
            )
            pooled.extend(vals)

        counts = Counter(pooled)
        unique = tuple(sorted(counts))
        field = field_name(off)
        result.append(
            {
                "offset": off,
                "field": field,
                "kind": _kind(off, field, len(unique), max(unique) - min(unique)),
                "unique_count": len(unique),
                "unique_values": unique,
                "min": min(unique),
                "max": max(unique),
                "frequency": dict(sorted(counts.items())),
                "banks": per_bank,
            }
        )
    return result
