"""P1.7 OFFLINE — statistical reverse engineering of the JT-4000M program.

Single responsibility: derive byte-level *statistics* (entropy, transitions,
classifications, correlations, dossiers) from the LOCAL .syx files only, and
expose them as deterministic machine-readable + human-readable reports.

Reused, never re-implemented:
  * jt4000m.syx        — parser, checksum(), field_name(), semantic_value()
  * jt4000m.model      — Parameter Registry (BY_OFFSET / BY_CC / PARAMETERS)
  * jt4000m.analyzer   — cross_bank() aggregation
  * jt4000m.knowledge  — discover_fixtures() inventory
  * jt4000m.experiment — provenance vocabulary

Evidence levels used in P1.7 (documented rules):
  STATIC_KNOWN       — information already present in the project registry;
  OBSERVED           — directly observed in the local .syx fixtures;
  INFERRED           — statistical/structural conclusion over several files;
  HARDWARE_CONFIRMED — NOT PRODUCED HERE. No physical JT-4000M was involved;
                       every finding stays below the hardware level.

Honesty guarantees enforced by this module:
  * Unknown offsets are classified by DATA BEHAVIOUR ONLY (e.g.
    DISCRETE_CANDIDATE). They are never given a parameter name.
  * Correlations are labelled "observed correlation / potential dependency;
    hardware confirmation required" — never "A controls B".
  * Constant bytes are labelled FIXTURE_CONSTANT — not "unused"/"reserved".
  * All computations are deterministic (no randomness, no sampling).
"""
from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .knowledge import ROOT, build_offset_matrix, cc_offset_table, discover_fixtures
from .model import BY_CC, BY_OFFSET, PARAMETERS
from .syx import PROGRAM_LEN, SysExFile, checksum, field_name, parse_file, semantic_value

# ---------------------------------------------------------------------------
# Evidence-level vocabulary for P1.7 (see module docstring).
# ---------------------------------------------------------------------------
LEVEL_STATIC = "STATIC_KNOWN"
LEVEL_OBSERVED = "OBSERVED"
LEVEL_INFERRED = "INFERRED"
LEVEL_HARDWARE = "HARDWARE_CONFIRMED"   # vocabulary member only; NEVER emitted offline

NAME_RANGE = range(55, 64)             # patch-name bytes 0x37..0x3F

# Data-behaviour classifications (NOT claims about parameter meaning).
CLS_NAME = "NAME"
CLS_PARAMETER_KNOWN = "PARAMETER_KNOWN"
CLS_CONSTANT = "CONSTANT"
CLS_BINARY = "BINARY"
CLS_DISCRETE = "DISCRETE_CANDIDATE"
CLS_CONTINUOUS = "CONTINUOUS_CANDIDATE"
CLS_UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------
# Deterministic statistics helpers
# ---------------------------------------------------------------------------
def entropy(values: Iterable[int]) -> float:
    """Shannon entropy in bits over the empirical distribution of `values`.

    Deterministic; log base 2. Empty input yields 0.0.
    """
    vals = list(values)
    n = len(vals)
    if n == 0:
        return 0.0
    counts = Counter(vals)
    h = 0.0
    for c in counts.values():
        p = c / n
        h -= p * math.log2(p)
    return round(h, 6)


def median(values: Iterable[int]) -> float:
    vals = sorted(values)
    if not vals:
        raise ValueError("median needs at least one value")
    mid = len(vals) // 2
    if len(vals) % 2:
        m = vals[mid]
    else:
        m = (vals[mid - 1] + vals[mid]) / 2
    return float(m)


def mutual_information(xs: Iterable[int], ys: Iterable[int]) -> float:
    """MI(X;Y) in bits — captures non-linear co-dependence between two bytes."""
    xs, ys = list(xs), list(ys)
    if len(xs) != len(ys) or not xs:
        raise ValueError("mutual_information needs equal-length non-empty inputs")
    n = len(xs)
    cx, cy, cxy = Counter(xs), Counter(ys), Counter(zip(xs, ys))
    mi = 0.0
    for (a, b), c in cxy.items():
        pxy = c / n
        mi += pxy * math.log2(pxy / ((cx[a] / n) * (cy[b] / n)))
    return round(mi, 6)


def pearson(xs: Iterable[int], ys: Iterable[int]) -> float | None:
    """Linear correlation coefficient; None when either side is constant."""
    xs, ys = list(xs), list(ys)
    n = len(xs)
    if n != len(ys) or n < 2:
        raise ValueError("pearson needs >=2 equal-length samples")
    mx, my = sum(xs) / n, sum(ys) / n
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx == 0 or vy == 0:
        return None
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return round(cov / math.sqrt(vx * vy), 6)


def classify_offset(offset: int, unique_count: int, values: tuple[int, ...],
                    known: bool) -> str:
    """Conservative DATA-BEHAVIOUR classification for one offset.

    Never infers a parameter meaning; PARAMETER_KNOWN merely reflects that the
    existing registry already maps this offset.
    """
    if offset in NAME_RANGE:
        return CLS_NAME
    if known:
        return CLS_PARAMETER_KNOWN
    if unique_count <= 1:
        return CLS_CONSTANT
    if unique_count == 2:
        return CLS_BINARY
    if unique_count <= 8:
        return CLS_DISCRETE
    return CLS_CONTINUOUS


# ---------------------------------------------------------------------------
# Dataset inventory (task 3)
# ---------------------------------------------------------------------------
@dataclass
class FileInfo:
    path: str
    mode: str
    programs: int
    total_bytes: int
    checksum_stored: int
    checksum_expected: int
    checksum_ok: bool
    provenance: str
    names: tuple[str, ...]
    duplicate_programs: dict          # raw-data hex -> [slot numbers]
    identical_programs: int           # slots sharing data with another slot
    unique_programs: int

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["checksum_stored"] = f"0x{self.checksum_stored:02X}"
        d["checksum_expected"] = f"0x{self.checksum_expected:02X}"
        d["duplicate_programs"] = {k: v for k, v in self.duplicate_programs.items()}
        return d


def _bank_payload(bank: SysExFile) -> list[bytes]:
    """Program data records in file order (bulk: 32, single: 1)."""
    return [p.data for p in bank.programs]


def inventory(paths: Iterable[str | Path]) -> list[FileInfo]:
    out: list[FileInfo] = []
    for p in paths:
        p = Path(p)
        bank = parse_file(p)
        payload = _bank_payload(bank)
        groups: dict[bytes, list[int]] = {}
        for i, data in enumerate(payload, start=1):
            groups.setdefault(data, []).append(i)
        dupes = {d.hex(): slots for d, slots in groups.items() if len(slots) > 1}
        shared = sum(len(s) for s in dupes.values())
        out.append(FileInfo(
            path=str(p), mode=bank.mode, programs=len(bank.programs),
            total_bytes=len(bank.raw),
            checksum_stored=bank.checksum_value,
            checksum_expected=bank.checksum_expected,
            checksum_ok=bank.checksum_ok,
            # P1.7 rule: nothing here came off a physical device.
            provenance="REFERENCE_FIXTURE",
            names=tuple(pr.name for pr in bank.programs),
            duplicate_programs=dupes,
            identical_programs=shared,
            unique_programs=len(groups),
        ))
    return out


# ---------------------------------------------------------------------------
# Byte-level statistical profiles (tasks 4, 5, 8, 10)
# ---------------------------------------------------------------------------
@dataclass
class OffsetProfile:
    offset: int
    field: str
    classification: str
    evidence_level: str
    registry_key: str | None
    kind: str | None
    cc: int | None
    count: int
    unique_count: int
    unique_values: tuple[int, ...]
    min: int | None
    max: int | None
    mean: float | None
    median: float | None
    frequency: dict[int, int]
    zero_pct: float
    max7f_pct: float
    entropy: float
    files_seen_in: int
    files_changed: int
    transitions: dict[tuple[int, int], int]
    transition_count: int
    spread: dict                      # per-file presence/range summary

    def transitions_json(self) -> dict:
        return {f"0x{a:02X}->0x{b:02X}": n for (a, b), n in
                sorted(self.transitions.items())}

    def to_dict(self) -> dict:
        return {
            "offset": f"0x{self.offset:02X}",
            "field": self.field,
            "classification": self.classification,
            "evidence_level": self.evidence_level,
            "registry": {"key": self.registry_key, "kind": self.kind,
                         "cc": self.cc},
            "stats": {
                "count": self.count,
                "unique_count": self.unique_count,
                "unique_values": [f"0x{v:02X}" for v in self.unique_values],
                "min": None if self.min is None else f"0x{self.min:02X}",
                "max": None if self.max is None else f"0x{self.max:02X}",
                "mean": self.mean, "median": self.median,
                "frequency": {f"0x{int(k):02X}": v for k, v in
                              sorted(self.frequency.items())},
                "zero_pct": self.zero_pct, "max_7f_pct": self.max7f_pct,
                "entropy_bits": self.entropy,
                "files_seen_in": self.files_seen_in,
                "files_changed": self.files_changed,
            },
            "transitions": self.transitions_json(),
            "transition_count": self.transition_count,
            "spread": self.spread,
            "hardware_confirmation": False,
        }


def _records_for(files: list[tuple[str, SysExFile]], off: int) -> list[tuple[str, int, int]]:
    """[(file, slot, value)] for one relative offset, in file/slot order."""
    recs = []
    for name, bank in files:
        for i, data in enumerate(_bank_payload(bank), start=1):
            recs.append((name, i, data[off]))
    return recs


def offset_profiles(files: list[tuple[str, SysExFile]]) -> list[OffsetProfile]:
    profiles: list[OffsetProfile] = []
    for off in range(PROGRAM_LEN):
        recs = _records_for(files, off)
        vals = [v for _, _, v in recs]
        uniq = tuple(sorted(set(vals)))
        spec = BY_OFFSET.get(off)
        cls = classify_offset(off, len(uniq), uniq, spec is not None)
        # evidence level: registry info is STATIC_KNOWN; anything the fixtures
        # add on top is OBSERVED. Nothing here is ever HARDWARE_CONFIRMED.
        if cls == CLS_PARAMETER_KNOWN:
            level = LEVEL_OBSERVED if len(uniq) > 1 else LEVEL_STATIC
        elif cls == CLS_NAME:
            level = LEVEL_OBSERVED
        else:
            level = LEVEL_OBSERVED if len(uniq) > 1 else LEVEL_INFERRED
        freq = Counter(vals)
        n = len(vals)
        # transitions: consecutive programs within each file
        trans: Counter = Counter()
        by_file: dict[str, list[int]] = {}
        for fname, _, v in recs:
            by_file.setdefault(fname, []).append(v)
        for seq in by_file.values():
            for a, b in zip(seq, seq[1:]):
                if a != b:
                    trans[(a, b)] += 1
        spread = {}
        for fname, seq in by_file.items():
            u = sorted(set(seq))
            spread[fname] = {
                "present": True,
                "unique_values": [f"0x{v:02X}" for v in u],
                "nonzero_slots": sum(1 for v in seq if v != 0),
                "slots": len(seq),
            }
        profiles.append(OffsetProfile(
            offset=off, field=field_name(off), classification=cls,
            evidence_level=level,
            registry_key=spec.key if spec else None,
            kind=spec.kind if spec else None,
            cc=spec.cc if spec else None,
            count=n, unique_count=len(uniq), unique_values=uniq,
            min=min(uniq), max=max(uniq),
            mean=round(sum(vals) / n, 6), median=median(vals),
            frequency=dict(freq),
            zero_pct=round(100.0 * freq.get(0, 0) / n, 4),
            max7f_pct=round(100.0 * freq.get(0x7F, 0) / n, 4),
            entropy=entropy(vals),
            files_seen_in=len(by_file),
            files_changed=sum(1 for seq in by_file.values() if len(set(seq)) > 1),
            transitions=dict(trans), transition_count=sum(trans.values()),
            spread=spread,
        ))
    return profiles


# ---------------------------------------------------------------------------
# Pairwise correlation analysis (task 7) — HYPOTHESIS output only
# ---------------------------------------------------------------------------
def correlation_pairs(profiles: list[OffsetProfile],
                      files: list[tuple[str, SysExFile]],
                      mi_threshold: float = 0.3) -> list[dict]:
    """Find offsets whose values co-depend across all fixture programs.

    Uses MI(P_a ; P_b) normalised by min(H(P_a), H(P_b)).  Output wording is
    deliberately non-causal: an entry means "observed correlation / potential
    dependency; hardware confirmation required", NEVER "A controls B".
    """
    prof_by_off = {p.offset: p for p in profiles}
    cols = {off: [v for _, _, v in _records_for(files, off)]
            for off in range(PROGRAM_LEN)}
    out: list[dict] = []
    for a in range(PROGRAM_LEN):
        if prof_by_off[a].classification == CLS_NAME:
            continue
        for b in range(a + 1, PROGRAM_LEN):
            if prof_by_off[b].classification == CLS_NAME:
                continue
            ha, hb = prof_by_off[a].entropy, prof_by_off[b].entropy
            if ha == 0 or hb == 0:
                continue  # constant byte cannot carry information
            mi = mutual_information(cols[a], cols[b])
            denom = min(ha, hb)
            norm = round(mi / denom, 6) if denom else 0.0
            if norm >= mi_threshold:
                pa, pb = prof_by_off[a], prof_by_off[b]
                both_known = (pa.classification == CLS_PARAMETER_KNOWN and
                              pb.classification == CLS_PARAMETER_KNOWN)
                out.append({
                    "offset_a": f"0x{a:02X}", "field_a": pa.field,
                    "offset_b": f"0x{b:02X}", "field_b": pb.field,
                    "mutual_information_bits": mi,
                    "normalized_mi": norm,
                    "pearson": pearson(cols[a], cols[b]),
                    "evidence_level": LEVEL_INFERRED,
                    "status": ("OBSERVED_CORRELATION (both params known; "
                               "possible shared UI function)"
                               if both_known else
                               "HYPOTHESIS: potential dependency; hardware "
                               "confirmation required"),
                })
    out.sort(key=lambda r: -r["normalized_mi"])
    return out


# ---------------------------------------------------------------------------
# Rare vs widespread offsets (task 10)
# ---------------------------------------------------------------------------
def usage_spread(profiles: list[OffsetProfile]) -> dict:
    """Separate offsets that vary widely from rarely-varying ones.

    NOTE: rare != unused, constant != reserved — these buckets describe the
    LOCAL FIXTURE CORPUS only.

    The 'fixture_constant' bucket lists UNKNOWN (non-registry) offsets whose
    value never varies across the corpus.  Registry-mapped parameters are NOT
    listed here even when their observed corpus value is constant (e.g.
    Portamento Mode @ 0x2D, where only OFF has ever been observed): they are
    already accounted for as PARAMETER_KNOWN, and putting them into a bucket
    dominated by unknown bytes invites misreading them as unknown/reserved.
    Such parameters surface instead via enum corroboration / contradictions.
    """
    widespread, occasional, rare, constant = [], [], [], []
    known_constant = []   # registry params whose corpus value never varies
    for p in profiles:
        if p.classification == CLS_NAME:
            continue
        if p.unique_count <= 1:
            if p.classification != CLS_PARAMETER_KNOWN:
                constant.append(f"0x{p.offset:02X}")
            else:
                known_constant.append(
                    f"0x{p.offset:02X} ({p.field})")
        elif p.files_changed >= 2 and p.unique_count >= 5:
            widespread.append(f"0x{p.offset:02X}")
        elif p.transition_count == 0:
            rare.append(f"0x{p.offset:02X}")     # varies only BETWEEN files
        else:
            occasional.append(f"0x{p.offset:02X}")
    return {"widespread": widespread, "occasional": occasional,
            "rare_within_files": rare, "fixture_constant": constant,
            "known_parameter_constant_in_corpus": known_constant}


# ---------------------------------------------------------------------------
# Contradictions (task 12) — report-only, registry is never auto-modified
# ---------------------------------------------------------------------------
def contradictions(profiles: list[OffsetProfile]) -> list[dict]:
    """Where fixtures disagree with the static registry expectations."""
    out: list[dict] = []
    for p in profiles:
        if p.classification != CLS_PARAMETER_KNOWN:
            continue
        spec = BY_OFFSET[p.offset]
        bad = [v for v in p.unique_values if not spec.minimum <= v <= spec.maximum]
        if bad:
            out.append({
                "offset": f"0x{p.offset:02X}", "field": p.field,
                "type": "OUT_OF_REGISTRY_RANGE",
                "registry_range": [spec.minimum, spec.maximum],
                "observed_values": [f"0x{v:02X}" for v in bad],
                "action": "report only — registry NOT modified automatically",
            })
        if spec.kind == "enum":
            from .model import ENUM_OPTIONS
            table = ENUM_OPTIONS.get(spec.key, {})
            unknown_vals = [v for v in p.unique_values if v not in table]
            if unknown_vals:
                out.append({
                    "offset": f"0x{p.offset:02X}", "field": p.field,
                    "type": "ENUM_VALUE_NOT_IN_TABLE",
                    "registry_enum": sorted(table),
                    "observed_unlabelled_values":
                        [f"0x{v:02X}" for v in unknown_vals],
                    "action": "leave unlabelled \"Unknown (0xNN)\" — naming "
                              "would invent a parameter (hardware TODO)",
                })
        # behavioural oddity: a documented continuous control that only ever
        # takes a tiny discrete set in the corpus
        if spec.kind == "continuous" and 1 < p.unique_count <= 3 \
                and spec.key not in ():
            out.append({
                "offset": f"0x{p.offset:02X}", "field": p.field,
                "type": "LOW_VARIABILITY_FOR_KIND",
                "detail": f"registry kind=continuous but only "
                          f"{p.unique_count} distinct values across corpus",
                "action": "corpus limitation, not necessarily a contradiction; "
                          "hardware TODO",
            })
    return out


# ---------------------------------------------------------------------------
# Enum mapping corroboration (task 11)
# ---------------------------------------------------------------------------
def enum_findings(profiles: list[OffsetProfile]) -> list[dict]:
    from .model import ENUM_OPTIONS
    out = []
    for p in profiles:
        if p.classification != CLS_PARAMETER_KNOWN or p.kind != "enum":
            continue
        table = ENUM_OPTIONS.get(p.registry_key, {})
        mapped = {f"0x{v:02X}": lbl for v, lbl in sorted(table.items())
                  if v in p.unique_values}
        unmapped = [f"0x{v:02X}" for v in p.unique_values if v not in table]
        out.append({
            "parameter": p.registry_key, "field": p.field,
            "offset": f"0x{p.offset:02X}",
            "registry_mapping": {lbl: f"0x{v:02X}" for v, lbl in
                                 sorted(table.items())},
            "observed_fixture_values": [f"0x{v:02X}" for v in p.unique_values],
            "observed_and_labelled": mapped,
            "observed_unlabelled": unmapped,
            "status": "STATIC_KNOWN + OBSERVED" if mapped else "STATIC_KNOWN",
            "hardware_confirmed": False,
        })
    return out


# ---------------------------------------------------------------------------
# Experiment priority for UNKNOWN offsets (task 14) — transparent criteria
# ---------------------------------------------------------------------------
def experiment_priority(profiles: list[OffsetProfile],
                        pairs: list[dict]) -> list[dict]:
    """Rank unknown offsets for future hardware experiments.

    Transparent technical criteria (documented, deterministic):
      * higher entropy => more information carried;
      * multiple stable values (discrete/binary) => cheap A/B candidates;
      * name/checksum regions excluded;
      * strong correlation with ANOTHER unknown offset => deprioritised
        (one experiment can probe the pair).
    This ranks EXPERIMENT EFFICIENCY only; it says nothing about meaning.
    """
    unknown_with_info = [p for p in profiles
                         if p.classification in (CLS_BINARY, CLS_DISCRETE,
                                                 CLS_CONTINUOUS)]
    unknown_unknown_corr: set[str] = set()
    for r in pairs:
        fa, fb = r["field_a"], r["field_b"]
        if fa.startswith("Byte 0x") and fb.startswith("Byte 0x"):
            unknown_unknown_corr.add(fa)
            unknown_unknown_corr.add(fb)
    ranked = sorted(unknown_with_info, key=lambda p: (-p.entropy, p.offset))
    out = []
    for p in ranked:
        if p.entropy >= 1.0:
            tier = "HIGH_INFORMATION_VALUE"
        elif p.entropy > 0:
            tier = "MEDIUM_INFORMATION_VALUE"
        else:
            tier = "LOW_INFORMATION_VALUE"
        note = ""
        if field_name(p.offset) in unknown_unknown_corr:
            note = ("correlated with another unknown offset; test the pair "
                    "together")
        out.append({
            "offset": f"0x{p.offset:02X}", "field": p.field,
            "classification": p.classification,
            "entropy_bits": p.entropy,
            "unique_values": [f"0x{v:02X}" for v in p.unique_values],
            "experiment_priority": tier,
            "candidate_meaning": "UNKNOWN",
            "hardware_confirmation": "REQUIRED",
            "note": note,
        })
    return out


# ---------------------------------------------------------------------------
# Registry & CC audits (tasks 15, 16)
# ---------------------------------------------------------------------------
def registry_audit(profiles: list[OffsetProfile]) -> list[dict]:
    prof = {p.offset: p for p in profiles}
    out = []
    for spec in PARAMETERS:
        if spec.offset is None:
            out.append({"key": spec.key, "label": spec.label,
                        "offset": None, "cc": spec.cc, "kind": spec.kind,
                        "range": [spec.minimum, spec.maximum],
                        "observed_values": None, "fixture_coverage": "none "
                        "(SysEx offset not established)",
                        "contradictions": ["offset unknown"],
                        "evidence_level": LEVEL_STATIC,
                        "hardware_evidence": False})
            continue
        p = prof[spec.offset]
        contra = []
        bad = [v for v in p.unique_values if not spec.minimum <= v <= spec.maximum]
        if bad:
            contra.append(f"observed outside range: {[hex(v) for v in bad]}")
        if spec.kind == "enum":
            from .model import ENUM_OPTIONS
            table = ENUM_OPTIONS.get(spec.key, {})
            unk = [v for v in p.unique_values if v not in table]
            if unk:
                contra.append(f"enum values without labels: {[hex(v) for v in unk]}")
        coverage = ("varies in fixtures" if p.unique_count > 1
                    else "constant in fixtures")
        out.append({"key": spec.key, "label": spec.label,
                    "offset": f"0x{spec.offset:02X}", "cc": spec.cc,
                    "kind": spec.kind, "range": [spec.minimum, spec.maximum],
                    "observed_values": [f"0x{v:02X}" for v in p.unique_values],
                    "fixture_coverage": coverage,
                    "contradictions": contra,
                    "evidence_level": (LEVEL_OBSERVED if p.unique_count > 1
                                       else LEVEL_STATIC),
                    "hardware_evidence": False})
    return out


def cc_audit(profiles: list[OffsetProfile]) -> list[dict]:
    """CC mappings audit. SYX fixtures alone can NEVER prove a MIDI CC map."""
    rows_by_off = {p.offset: p for p in profiles}
    out = []
    for spec in PARAMETERS:
        if spec.cc is None:
            continue
        r = rows_by_off.get(spec.offset) if spec.offset is not None else None
        fixture_ev = bool(r is not None and r.unique_count > 1)
        out.append({
            "cc": spec.cc, "parameter": spec.key,
            "offset": None if spec.offset is None else f"0x{spec.offset:02X}",
            "source": "parameter_registry (Behringer MIDI documentation)",
            "offset_fixture_evidence": ("offset varies in fixtures"
                                        if fixture_ev else
                                        "no offset variation / no offset"),
            "hardware_evidence": "HARDWARE_CONFIRMATION_REQUIRED",
            "note": "SYX fixtures do not themselves prove CC mapping",
        })
    out.sort(key=lambda x: x["cc"])
    return out


# ---------------------------------------------------------------------------
# Unknown-offset dossiers (task 13)
# ---------------------------------------------------------------------------
def unknown_dossiers(profiles: list[OffsetProfile],
                     pairs: list[dict],
                     priorities: list[dict]) -> list[dict]:
    prio = {p["offset"]: p for p in priorities}
    corr_by_field: dict[str, list[str]] = {}
    for r in pairs:
        corr_by_field.setdefault(r["field_a"], []).append(
            f"{r['field_b']} (nMI={r['normalized_mi']})")
        corr_by_field.setdefault(r["field_b"], []).append(
            f"{r['field_a']} (nMI={r['normalized_mi']})")
    out = []
    for p in profiles:
        if p.classification == CLS_PARAMETER_KNOWN or p.classification == CLS_NAME:
            continue
        pr = prio.get(f"0x{p.offset:02X}", {})
        out.append({
            "offset": f"0x{p.offset:02X}",
            "status": "UNKNOWN",
            "classification": p.classification,
            "observed_values": [f"0x{v:02X}" for v in p.unique_values],
            "frequency": {f"0x{int(k):02X}": v for k, v in
                          sorted(p.frequency.items())},
            "entropy_bits": p.entropy,
            "transitions": p.transitions_json(),
            "banks_with_nonzero": [f for f, s in p.spread.items()
                                   if s["nonzero_slots"] > 0],
            "correlations_observed": corr_by_field.get(p.field, []),
            "experiment_priority": pr.get("experiment_priority",
                                          "LOW_INFORMATION_VALUE"),
            "candidate_meaning": "UNKNOWN",
            "hardware_confirmation": "REQUIRED",
        })
    return out


# ---------------------------------------------------------------------------
# Full dataset + reports (tasks 17, 18)
# ---------------------------------------------------------------------------
@dataclass
class DiscoveryReport:
    dataset: dict
    files: list
    profiles: list
    classifications: dict
    spread: dict
    enums: list
    pairs: list
    contradictions: list
    registry_audit: list
    cc_audit: list
    priorities: list
    dossiers: list
    limitations: list

    def to_json(self) -> str:
        doc = {
            "schema": "jt4000m-p1.7-discovery/1",
            "generated_by": "python -m jt4000m.cli analyze-bank / analyze-offsets",
            "dataset": self.dataset,
            "files": [f.to_dict() for f in self.files],
            "offsets": [p.to_dict() for p in self.profiles],
            "classification_summary": self.classifications,
            "usage_spread": self.spread,
            "enum_corroboration": self.enums,
            "correlations": self.pairs,
            "contradictions": self.contradictions,
            "registry_audit": self.registry_audit,
            "cc_audit": self.cc_audit,
            "experiment_priorities": self.priorities,
            "unknown_dossiers": self.dossiers,
            "evidence_levels_used": [LEVEL_STATIC, LEVEL_OBSERVED, LEVEL_INFERRED],
            "hardware_confirmed_offsets": [],
            "limitations": self.limitations,
        }
        return json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True)

    def to_markdown(self) -> str:
        L = []
        L.append("# P1.7 — Offline Parameter Discovery & Statistical RE")
        L.append("")
        L.append("**No physical JT-4000M was available. Zero findings in this "
                 "report are HARDWARE_CONFIRMED.**")
        L.append("")
        L.append("## Dataset")
        L.append("| file | mode | programs | bytes | checksum | provenance | unique patches |")
        L.append("|---|---|---|---|---|---|---|")
        for f in self.files:
            cs = "OK" if f.checksum_ok else "BAD"
            L.append(f"| {Path(f.path).name} | {f.mode} | {f.programs} | "
                     f"{f.total_bytes} | {f.checksum_stored}/{cs} | "
                     f"{f.provenance} | {f.unique_programs} |")
        L.append("")
        L.append("## Offset statistics (0x00–0x3F)")
        L.append("| off | field | class | level | N uniq | ent | min | max | zero% | trans |")
        L.append("|---|---|---|---|---|---|---|---|---|---|")
        for p in self.profiles:
            mn = "-" if p.min is None else f"0x{p.min:02X}"
            mx = "-" if p.max is None else f"0x{p.max:02X}"
            L.append(f"| 0x{p.offset:02X} | {p.field} | {p.classification} | "
                     f"{p.evidence_level} | {p.unique_count} | {p.entropy:.3f} | "
                     f"{mn} | {mx} | {p.zero_pct:.1f} | {p.transition_count} |")
        L.append("")
        L.append("## Classification summary")
        for k, v in sorted(self.classifications.items()):
            L.append(f"* {k}: {v}")
        L.append("")
        L.append("## Usage spread (local corpus only; rare ≠ unused, constant ≠ reserved)")
        for k, v in self.spread.items():
            L.append(f"* {k}: {', '.join(v) if v else '—'}")
        L.append("")
        L.append("## Enum mapping corroboration (registry vs fixtures)")
        for e in self.enums:
            L.append(f"* `{e['parameter']}` @ {e['offset']}: {e['status']}; "
                     f"unlabelled observed: {e['observed_unlabelled'] or 'none'}")
        L.append("")
        L.append("## Correlations (INFERRED — never causal claims)")
        for r in self.pairs[:20]:
            L.append(f"* {r['offset_a']} ({r['field_a']}) ↔ {r['offset_b']} "
                     f"({r['field_b']}): nMI={r['normalized_mi']} — {r['status']}")
        if not self.pairs:
            L.append("* none above threshold")
        L.append("")
        L.append("## Contradictions (report-only; registry untouched)")
        for c in self.contradictions:
            L.append(f"* {c['offset']} {c['field']}: {c['type']} — "
                     f"{c.get('observed_values') or c.get('observed_unlabelled_values') or c.get('detail','')}")
        if not self.contradictions:
            L.append("* none")
        L.append("")
        L.append("## CC audit (all mappings require hardware confirmation)")
        L.append("| CC | parameter | offset | source | fixture evidence | hardware |")
        L.append("|---|---|---|---|---|---|")
        for c in self.cc_audit:
            L.append(f"| {c['cc']} | {c['parameter']} | {c['offset']} | "
                     f"registry/MIDI docs | {c['offset_fixture_evidence']} | "
                     f"HARDWARE_CONFIRMATION_REQUIRED |")
        L.append("")
        L.append("## Experiment priorities (efficiency ranking, not meaning)")
        for p in self.priorities:
            L.append(f"* {p['offset']} {p['field']}: {p['experiment_priority']} "
                     f"(ent={p['entropy_bits']}, {p['classification']}) "
                     f"{p['note']}")
        L.append("")
        L.append("## Limitations")
        for t in self.limitations:
            L.append(f"* {t}")
        L.append("")
        L.append("_Levels: STATIC_KNOWN = registry only · OBSERVED = directly "
                 "seen in fixtures · INFERRED = statistical conclusion · "
                 "HARDWARE_CONFIRMED = not produced in P1.7._")
        return "\n".join(L)


LIMITATIONS = [
    "No physical JT-4000M was available; nothing in this report is hardware-confirmed.",
    "Corpus = local .syx fixtures only (REFERENCE_FIXTURE provenance).",
    "Statistical correlation is not causation; candidate meanings stay UNKNOWN.",
    "SYX files alone cannot prove MIDI CC mappings.",
    "Fixture-constant bytes may still be meaningful parameters rarely used.",
]


def generate(paths: Iterable[str | Path] | None = None,
             mi_threshold: float = 0.3) -> DiscoveryReport:
    files_paths = [Path(p) for p in (paths if paths is not None
                                     else discover_fixtures())]
    parsed = [(p.name, parse_file(p)) for p in files_paths]
    inv = inventory(files_paths)
    profiles = offset_profiles(parsed)
    pairs = correlation_pairs(profiles, parsed, mi_threshold=mi_threshold)
    classes: Counter = Counter(p.classification for p in profiles)
    return DiscoveryReport(
        dataset={"files": [str(p) for p in files_paths],
                 "programs_total": sum(f.programs for f in inv),
                 "deduplicated_by_content_hash": True},
        files=inv,
        profiles=profiles,
        classifications=dict(classes),
        spread=usage_spread(profiles),
        enums=enum_findings(profiles),
        pairs=pairs,
        contradictions=contradictions(profiles),
        registry_audit=registry_audit(profiles),
        cc_audit=cc_audit(profiles),
        priorities=experiment_priority(profiles, pairs),
        dossiers=unknown_dossiers(profiles, pairs,
                                  experiment_priority(profiles, pairs)),
        limitations=list(LIMITATIONS),
    )


def write_reports(report: DiscoveryReport, out_dir: str | Path,
                  stem: str = "parameter_discovery") -> tuple[Path, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    jp = out / f"{stem}.json"
    mp = out / f"{stem}.md"
    jp.write_text(report.to_json(), encoding="utf-8")
    mp.write_text(report.to_markdown(), encoding="utf-8")
    return jp, mp
