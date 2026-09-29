"""P1.6 OFFLINE — reverse-engineering knowledge base (no MIDI, no hardware).

Single responsibility: aggregate everything the LOCAL fixture files and the
EXISTING project modules prove about the 64-byte JT-4000M program structure,
without ever inventing parameters or promoting hypotheses to facts.

Reused (nothing is re-implemented here):
  * jt4000m.syx        — parser, checksum(), field_name(), semantic_value()
  * jt4000m.model      — Parameter Registry (BY_KEY / BY_OFFSET / BY_CC)
  * jt4000m.analyzer   — cross_bank() statistics
  * jt4000m.experiment — provenance labels + evidence log reader

Honesty rules enforced by this module:
  * Every finding carries an explicit confidence level; the hardware level
    exists in the vocabulary but can only be produced by CAPTURED_FROM_DEVICE
    evidence joined from the append-only experiment evidence log. Fixture
    analysis NEVER emits it.
  * Unknown offsets stay "UNKNOWN". Correlations are labelled HYPOTHESIS.
  * Offsets constant across fixtures are labelled FIXTURE_CONSTANT — never
    "reserved"/"unused"/"firmware constant".
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Iterable

from .analyzer import cross_bank
from .experiment import (CLASS_NAME, CONF_EXPERIMENTAL, EVIDENCE_AB_SYSEX,
                         PROVENANCE_DEVICE, read_evidence)
from .model import BY_CC, BY_KEY, BY_OFFSET, PARAMETERS, ParameterSpec
from .syx import FIELDS, PROGRAM_LEN, SysExFile, checksum, field_name, parse_file, semantic_value

ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Confidence levels (documented rules — no invented confidence)
# ---------------------------------------------------------------------------
CONF_STATIC = "static_mapping"            # registry/external doc only
CONF_FIXTURE = "fixture_observed"         # local .syx banks show consistent behavior
CONF_HW = "hardware_confirmed"            # ONLY via CAPTURED_FROM_DEVICE A/B evidence
CONF_HYPOTHESIS = "hypothesis"            # correlation observed; NOT a mapping claim

STATUS_UNKNOWN = "UNKNOWN"
STATUS_KNOWN = "KNOWN_PARAMETER"
STATUS_NAME = "PATCH_NAME"
STATUS_FIXTURE_CONSTANT = "FIXTURE_CONSTANT"

CC_SOURCE_STATIC = "STATIC_MIDI_MAPPING"          # external docs / registry
CC_SOURCE_FIXTURE = "FIXTURE_OBSERVED_SYSEX"      # offset corroborated by fixtures
CC_SOURCE_HW = "HARDWARE_CONFIRMED"               # must never appear offline

DEFAULT_FIXTURES: tuple[str, ...] = (
    "EMPTY.syx",
    "ALL EMPTY.syx",
    "ALL INIT SAW.syx",
    "ALL INIT SUPERSAW.syx",
    "INIT SAW.syx",
    "INIT SUPERSAW.syx",
    "Synthmania-EDM-Soundset-JT-4000.syx",
)


def discover_fixtures(base: str | Path = ROOT,
                     names: Iterable[str] | None = None) -> list[Path]:
    """All local .syx files (known names first, then any others found).

    Deduplicated by file CONTENT hash: the same bank may exist both in the
    project root and under fixtures/ — counting it twice would skew every
    cross-bank statistic.
    """
    base = Path(base)
    ordered: list[Path] = []
    for n in (names if names is not None else DEFAULT_FIXTURES):
        p = base / n
        if p.is_file():
            ordered.append(p)
    ordered.extend(sorted(p for p in base.rglob("*.syx") if p.is_file()))
    seen_hashes: set = set()
    out: list[Path] = []
    for p in ordered:
        digest = __import__("hashlib").sha256(p.read_bytes()).hexdigest()
        if digest in seen_hashes:
            continue
        seen_hashes.add(digest)
        out.append(p)
    return out


@dataclass
class OffsetRow:
    """Knowledge about ONE relative program offset (0x00..0x3F)."""
    offset: int
    field: str
    status: str                       # KNOWN_PARAMETER | PATCH_NAME | UNKNOWN
    parameter_key: str | None
    kind: str | None                  # enum/continuous/... from registry
    cc: int | None
    unique_count: int
    unique_values: tuple
    min: int | None
    max: int | None
    frequency: dict
    per_bank: dict                    # bank name -> {unique,min,max}
    fixture_constant: bool
    changed_programs: int             # how many programs differ from slot 1
    confidence: str
    evidence_sources: list
    notes: str = ""

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["offset"] = f"0x{self.offset:02X}"
        d["unique_values"] = [f"0x{v:02X}" for v in self.unique_values]
        d["min"] = None if self.min is None else f"0x{self.min:02X}"
        d["max"] = None if self.max is None else f"0x{self.max:02X}"
        d["frequency"] = {f"0x{int(k):02X}": v for k, v in self.frequency.items()}
        return d


def _bank_stats(banks: list[tuple[str, SysExFile]]) -> list[dict]:
    return cross_bank(banks)


def build_offset_matrix(banks: list[tuple[str, SysExFile]],
                        evidence: list | None = None) -> list[OffsetRow]:
    """Cross-bank statistics + registry join + honest confidence per offset."""
    stats = _bank_stats(banks)
    hw_offsets = _hardware_confirmed_offsets(evidence)
    total_progs = sum(len(b.programs) for _, b in banks)
    rows: list[OffsetRow] = []
    for r in stats:
        off = r["offset"]
        spec = BY_OFFSET.get(off)
        if 55 <= off <= 63:
            status, key, kind, cc = STATUS_NAME, None, "text", None
            conf = CONF_FIXTURE
        elif spec is not None:
            status, key, kind, cc = STATUS_KNOWN, spec.key, spec.kind, spec.cc
            conf = CONF_FIXTURE if r["unique_count"] > 1 else CONF_STATIC
        else:
            status, key, kind, cc = STATUS_UNKNOWN, None, None, None
            conf = CONF_FIXTURE if r["unique_count"] > 1 else STATUS_FIXTURE_CONSTANT
        if off in hw_offsets:
            conf = CONF_HW
        constant = r["unique_count"] == 1
        # how many programs differ from the first program at this offset
        first = banks[0][1].programs[0].data[off] if banks else 0
        changed = sum(1 for _, b in banks for p in b.programs if p.data[off] != first)
        sources = ["cross_bank:" + n for n, _ in banks]
        if spec is not None:
            sources.insert(0, "parameter_registry")
        if off in hw_offsets:
            sources.append("evidence_log:CAPTURED_FROM_DEVICE")
        notes = ""
        if status == STATUS_UNKNOWN and constant:
            notes = ("identical in every local fixture program; this does NOT "
                     "prove unused/reserved")
        rows.append(OffsetRow(
            offset=off, field=r["field"], status=status, parameter_key=key,
            kind=kind, cc=cc, unique_count=r["unique_count"],
            unique_values=r["unique_values"], min=r["min"], max=r["max"],
            frequency=r["frequency"],
            per_bank={b["name"]: {"unique": list(b["unique_values"]),
                                  "min": b["min"], "max": b["max"]}
                      for b in r["banks"]},
            fixture_constant=constant, changed_programs=changed,
            confidence=conf, evidence_sources=sources, notes=notes))
    return rows


def _hardware_confirmed_offsets(evidence: list | None) -> set:
    """Offsets with EXPERIMENTALLY_CONFIRMED records over DEVICE captures only.

    Fixture-provenance experiments NEVER count here (they validate protocol,
    not device behavior).
    """
    out: set = set()
    for rec in evidence or []:
        if rec.get("confidence") != CONF_EXPERIMENTAL:
            continue
        prov = {rec.get("before", {}).get("provenance"),
                rec.get("after", {}).get("provenance")}
        if prov == {PROVENANCE_DEVICE}:
            out.add(rec["offset"])
    return out


# ---------------------------------------------------------------------------
# CC <-> SysEx offset table
# ---------------------------------------------------------------------------

def cc_offset_table(offset_rows: list[OffsetRow]) -> list[dict]:
    """Join registry CC numbers with SysEx offsets and fixture corroboration.

    Statuses (documented):
      STATIC_MAPPING           — CC documented externally, offset not seen to
                                 vary in local fixtures (or no offset at all);
      FIXTURE_OBSERVED_SYSEX   — both CC and offset exist AND the offset
                                 varies across local fixtures;
      HARDWARE_CONFIRMED       — reserved level; never emitted offline.
    """
    rows_by_off = {r.offset: r for r in offset_rows}
    out: list[dict] = []
    for spec in PARAMETERS:
        if spec.cc is None:
            continue
        r = rows_by_off.get(spec.offset) if spec.offset is not None else None
        if r is not None and r.confidence == CONF_HW:
            status = CC_SOURCE_HW
        elif r is not None and r.unique_count > 1:
            status = CC_SOURCE_FIXTURE
        else:
            status = CC_SOURCE_STATIC
        out.append({
            "key": spec.key, "label": spec.label, "cc": spec.cc,
            "sysex_offset": None if spec.offset is None else f"0x{spec.offset:02X}",
            "cc_range": [spec.minimum, spec.maximum],
            "sysex_range": None if r is None else [r.min, r.max],
            "source": "parameter_registry (Behringer MIDI documentation)",
            "status": status,
            "notes": spec.notes,
        })
    return out


# ---------------------------------------------------------------------------
# Correlation analysis (known parameter -> unknown offset), HYPOTHESIS only
# ---------------------------------------------------------------------------

def correlations(offset_rows: list[OffsetRow],
                 banks: list[tuple[str, SysExFile]],
                 threshold: float = 0.8) -> list[dict]:
    """Detect offsets that change together with known parameters.

    Output is explicitly labelled HYPOTHESIS; a correlation is never treated
    as proof of a mapping, even at 100%.
    """
    out: list[dict] = []
    known = [r for r in offset_rows if r.status == STATUS_KNOWN]
    unknown = [r for r in offset_rows if r.status == STATUS_UNKNOWN]
    flat = [(bi, pi, p.data) for bi, (_, b) in enumerate(banks)
            for pi, p in enumerate(b.programs)]
    for u in unknown:
        if u.unique_count < 2:
            continue
        best = None
        for k in known:
            both_changed = 0
            u_changed = 0
            for _bi, _pi, data in flat:
                ub = data[u.offset] != banks[0][1].programs[0].data[u.offset]
                kb = data[k.offset] != banks[0][1].programs[0].data[k.offset]
                u_changed += ub
                both_changed += (ub and kb)
            if u_changed == 0:
                continue
            jacc = both_changed / (u_changed + sum(
                1 for *_x, d in flat
                if d[k.offset] != banks[0][1].programs[0].data[k.offset])
                - both_changed)
            if jacc >= threshold and (best is None or jacc > best[1]):
                best = (k.parameter_key, jacc)
        if best:
            out.append({
                "unknown_offset": f"0x{u.offset:02X}",
                "correlated_with": best[0],
                "jaccard": round(best[1], 3),
                "status": "HYPOTHESIS",
                "note": "co-changes in fixtures; NOT a confirmed mapping; "
                        "needs hardware A/B verification",
            })
    return out


# ---------------------------------------------------------------------------
# Name encoding study (0x37..0x3F)
# ---------------------------------------------------------------------------

def name_study(banks: list[tuple[str, SysExFile]]) -> dict:
    """Empirical ASCII/name-field observations across local fixtures."""
    names = [p.name for _, b in banks for p in b.programs]
    raw_bytes = Counter()
    maxlen = 0
    padded_space = padded_zero = trailing_mixed = 0
    for _, b in banks:
        for p in b.programs:
            nb = p.data[55:64]
            raw_bytes.update(nb)
            stripped = nb.rstrip(b"\x00")
            maxlen = max(maxlen, len(stripped.rstrip(b" ")))
            if stripped.endswith(b" ") or (stripped != nb and b" " in nb[len(stripped):]):
                padded_space += 1
            if len(nb) - len(stripped) > 0 and nb[len(stripped):] == b"\x00" * (9 - len(stripped)):
                padded_zero += 1
            tail = nb[len(stripped):]
            if tail and set(tail) - {0x00, 0x20}:
                trailing_mixed += 1
    non_ascii = sorted(v for v in raw_bytes if v > 0x7F)
    control = sorted(v for v in raw_bytes if v < 0x20 and v != 0x00)
    return {
        "name_offsets": "0x37..0x3F (9 bytes)",
        "programs_analyzed": len(names),
        "distinct_names": len(set(names)),
        "max_used_length": maxlen,
        "padding_0x00_programs": padded_zero,
        "padding_0x20_programs": padded_space,
        "mixed_trailing_programs": trailing_mixed,
        "non_ascii_bytes_observed": [f"0x{v:02X}" for v in non_ascii],
        "control_bytes_observed": [f"0x{v:02X}" for v in control],
        "all_bytes_7bit": not non_ascii,
        "empty_name_programs": sum(1 for n in names if n == ""),
        "conclusion": ("9-byte fixed field inside program record; padding style "
                       "varies between fixtures (0x00 vs 0x20) — exact device "
                       "padding rule needs hardware verification"),
    }


# ---------------------------------------------------------------------------
# Checksum study (structure only; algorithm untouched)
# ---------------------------------------------------------------------------

def checksum_report(paths: Iterable[str | Path]) -> list[dict]:
    out = []
    for p in paths:
        s = parse_file(p)
        if s.mode == "bulk":
            covered = "payload bytes 0x008..0x807 (32*64 program bytes)"
        else:
            covered = "program bytes 0x008..0x047 (64 bytes)"
        recomputed = checksum(s.raw[8:-2])
        out.append({
            "file": Path(p).name,
            "mode": s.mode,
            "size": len(s.raw),
            "stored_checksum": f"0x{s.checksum_value:02X}",
            "calculated_checksum": f"0x{s.checksum_expected:02X}",
            "recomputed_from_raw": f"0x{recomputed:02X}",
            "status": "OK" if s.checksum_ok else "BAD",
            "covered_bytes": covered,
        })
    return out


# ---------------------------------------------------------------------------
# Conflict detection between sources
# ---------------------------------------------------------------------------

def conflicts(offset_rows: list[OffsetRow]) -> list[dict]:
    """Deliberately hunt for disagreements between registry, field map and
    observed fixture values. Nothing auto-resolves; resolution stays empty."""
    out: list[dict] = []
    # 1) syx.FIELDS vs model registry coverage
    reg_offsets = set(BY_OFFSET)
    map_offsets = set(FIELDS)
    only_map = sorted(map_offsets - reg_offsets)
    only_reg = sorted(reg_offsets - map_offsets)
    if only_map or only_reg:
        out.append({
            "topic": "registry-vs-field-map coverage",
            "source_a": "jt4000m.syx.FIELDS",
            "source_b": "jt4000m.model.PARAMETERS",
            "observed": f"only in FIELDS: {[hex(o) for o in only_map]}, "
                        f"only in registry: {[hex(o) for o in only_reg]}",
            "resolution": "",
            "status": "OPEN",
        })
    # 2) duplicate keys in PARAMETERS (osc_balance appears twice historically)
    dup = [k for k, c in Counter(p.key for p in PARAMETERS).items() if c > 1]
    if dup:
        out.append({
            "topic": "duplicate registry keys",
            "source_a": "PARAMETERS tuple",
            "source_b": "BY_KEY dict (last entry wins)",
            "observed": f"duplicated keys: {dup}",
            "resolution": "",
            "status": "OPEN",
        })
    # 3) enum offsets whose observed values exceed the established tables
    from .model import ENUM_OPTIONS
    for r in offset_rows:
        if r.status != STATUS_KNOWN or r.kind != "enum":
            continue
        opts = ENUM_OPTIONS.get(r.parameter_key, {})
        bad = [v for v in r.unique_values if v not in opts]
        if bad:
            out.append({
                "topic": f"{r.field}: enum values outside confirmed table",
                "source_a": "ENUM_OPTIONS (project tables)",
                "source_b": "fixture data",
                "observed": f"unlabelled values {[hex(v) for v in bad]} at 0x{r.offset:02X}",
                "resolution": "",
                "status": "OPEN (hardware TODO: verify enum table)",
            })
    # 4) analyzer's ENUM_OFFSETS includes 27 which has no field mapping
    from .analyzer import ENUM_OFFSETS
    stray = sorted(o for o in ENUM_OFFSETS if o not in map_offsets and o not in reg_offsets)
    if stray:
        out.append({
            "topic": "analyzer heuristic vs field map",
            "source_a": "analyzer.ENUM_OFFSETS",
            "source_b": "syx.FIELDS",
            "observed": f"ENUM_OFFSETS contains unmapped offsets {[hex(o) for o in stray]}",
            "resolution": "",
            "status": "OPEN (heuristic only; 0x1B remains UNKNOWN)",
        })
    return out


# ---------------------------------------------------------------------------
# Evidence database (derived artifact — single source of truth stays the code)
# ---------------------------------------------------------------------------

def build_evidence_db(base: str | Path = ROOT,
                      fixture_names: Iterable[str] | None = None) -> dict:
    banks = [(p.name, parse_file(p)) for p in discover_fixtures(base, fixture_names)
             if parse_file(p).mode == "bulk"]
    ev = read_evidence(Path(base) / "experiments" / "evidence_log.jsonl") \
        if (Path(base) / "experiments" / "evidence_log.jsonl").exists() else []
    rows = build_offset_matrix(banks, evidence=ev)
    return {
        "schema": "jt4000m-parameter-evidence/1",
        "generated_by": "python -m jt4000m.cli knowledge report",
        "provenance_note": ("ALL findings below derive from REFERENCE_FIXTURE "
                            "files. No result here is hardware-confirmed unless "
                            "the evidence log contains CAPTURED_FROM_DEVICE "
                            "records."),
        "fixtures": [{"file": n, "mode": "bulk", "programs": len(b.programs)}
                     for n, b in banks],
        "parameters": [
            {
                "key": r.parameter_key,
                "label": r.field,
                "sysex_offset": r.offset,
                "cc": r.cc,
                "kind": r.kind,
                "source": r.evidence_sources,
                "confidence": r.confidence,
                "hardware_confirmed": r.confidence == CONF_HW,
                "observed_values": [f"0x{v:02X}" for v in r.unique_values],
                "notes": r.notes,
            }
            for r in rows if r.status == STATUS_KNOWN
        ],
        "name_field": {"offsets": "0x37..0x3F", "confidence": CONF_FIXTURE,
                       "study": name_study(banks)},
        "unknown_offsets": [
            {"offset": r.offset, "field": r.field,
             "status": STATUS_FIXTURE_CONSTANT if r.fixture_constant else STATUS_UNKNOWN,
             "unique_values": [f"0x{v:02X}" for v in r.unique_values],
             "confidence": r.confidence,
             "notes": r.notes}
            for r in rows if r.status == STATUS_UNKNOWN
        ],
    }


# ---------------------------------------------------------------------------
# Top-level knowledge report
# ---------------------------------------------------------------------------

@dataclass
class KnowledgeReport:
    fixtures: list
    offsets: list          # OffsetRow list
    cc_table: list
    corr: list
    name: dict
    checksums: list
    conflicts: list
    hardware_confirmed_count: int

    def counts(self) -> dict:
        offs = self.offsets
        return {
            "known_parameters": sum(1 for r in offs if r.status == STATUS_KNOWN),
            "fixture_observed": sum(1 for r in offs
                                    if r.confidence == CONF_FIXTURE),
            "static_cc_mappings": sum(1 for r in self.cc_table
                                      if r["status"] == CC_SOURCE_STATIC),
            "fixture_observed_cc": sum(1 for r in self.cc_table
                                       if r["status"] == CC_SOURCE_FIXTURE),
            "hardware_confirmed": self.hardware_confirmed_count,
            "unknown_offsets": sum(1 for r in offs if r.status == STATUS_UNKNOWN),
            "fixture_constant_offsets": sum(1 for r in offs if r.fixture_constant),
            "name_offsets": 9,
            "conflicts": len(self.conflicts),
            "correlation_hypotheses": len(self.corr),
        }


def generate(base: str | Path = ROOT,
             fixture_names: Iterable[str] | None = None) -> KnowledgeReport:
    paths = discover_fixtures(base, fixture_names)
    parsed = [(p.name, parse_file(p)) for p in paths]
    bulk = [(n, s) for n, s in parsed if s.mode == "bulk"]
    ev_path = Path(base) / "experiments" / "evidence_log.jsonl"
    ev = read_evidence(ev_path) if ev_path.exists() else []
    rows = build_offset_matrix(bulk, evidence=ev)
    hw = sum(1 for r in rows if r.confidence == CONF_HW)
    return KnowledgeReport(
        fixtures=[{"file": n, "mode": s.mode, "programs": len(s.programs),
                   "checksum_ok": s.checksum_ok} for n, s in parsed],
        offsets=rows,
        cc_table=cc_offset_table(rows),
        corr=correlations(rows, bulk),
        name=name_study(bulk),
        checksums=checksum_report(paths),
        conflicts=conflicts(rows),
        hardware_confirmed_count=hw,
    )
