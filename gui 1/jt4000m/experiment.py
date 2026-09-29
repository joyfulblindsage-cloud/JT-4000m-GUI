"""P1.5 — Hardware Experiment Protocol (offline analysis; NO MIDI I/O).

This module turns BEFORE/AFTER SysEx captures of the physical JT-4000M into
structured, honest evidence records. It never sends anything to a device and
never auto-promotes parameters in the Parameter Registry.

Evidence levels (documented rules, no invented confidence):
  * KNOWN_PARAMETER          — offset exists in the project Parameter Registry
                               (confidence "registry": static mapping only).
  * PATCH_NAME               — offsets 55..63 (Name[0..8]) changed.
  * CHECKSUM                 — trailing checksum byte (recomputed at export).
  * HEADER / SERVICE         — frame bytes outside program payload.
  * UNKNOWN_OFFSET           — not in the registry: reported as
                               "Byte 0xNN", confidence "observed". NEVER
                               renamed into an invented parameter.
  * EXPERIMENTALLY_CONFIRMED — assigned ONLY when compare_experiment() is run
                               with an explicit hypothesis (a single known
                               parameter key) AND the observed change set
                               contains exactly that parameter's offset. Any
                               additional changed byte => AMBIGUOUS, and both
                               offsets are listed; we never pick one silently.

Provenance must be declared explicitly and never conflated:
  REFERENCE_FIXTURE      — a .syx file from the project fixtures (NOT proof
                           of anything the current device did);
  CAPTURED_FROM_DEVICE   — a dump actually received from the JT-4000M.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .diff import ByteDiff, program_diff
from .model import BY_KEY
from .syx import Program, field_name, parse_file, semantic_value

# ---------------------------------------------------------------------------
# Classification constants (stable strings — used by reports/tests/registry)
# ---------------------------------------------------------------------------
CLASS_KNOWN = "KNOWN_PARAMETER"
CLASS_NAME = "PATCH_NAME"
CLASS_CHECKSUM = "CHECKSUM"
CLASS_HEADER = "HEADER"
CLASS_SERVICE = "SERVICE"
CLASS_UNKNOWN = "UNKNOWN_OFFSET"

CONF_REGISTRY = "registry"                      # static mapping knows this offset
CONF_OBSERVED = "observed"                      # byte changed; meaning unknown
CONF_EXPERIMENTAL = "experimentally_confirmed"  # A/B experiment isolated it
CONF_AMBIGUOUS = "ambiguous"                    # experiment produced extra changes

EVIDENCE_AB_SYSEX = "A/B_SYSEX"

PROVENANCE_FIXTURE = "REFERENCE_FIXTURE"
PROVENANCE_DEVICE = "CAPTURED_FROM_DEVICE"
PROVENANCE_GENERATED = "SOFTWARE_GENERATED"


def detect_provenance(path: str | Path | None,
                      sessions_dir: str | Path | None = None) -> str:
    """P1.6 — honest provenance detection for an .syx file path.

    Rules (documented, no guessing):
      * CAPTURED_FROM_DEVICE only if the exact absolute path appears as a
        recorded 'capture' file in a session log (sessions/*.json written by
        `midi capture`).  Bundled banks are NEVER promoted automatically.
      * everything else stays REFERENCE_FIXTURE (default label).
    This is a convenience for `experiment compare --*-prov auto`; the operator
    can still override explicitly with device/fixture.
    """
    if path is None:
        return PROVENANCE_FIXTURE
    target = str(Path(path).resolve())
    base = Path(sessions_dir) if sessions_dir else Path.cwd() / "sessions"
    if not base.is_dir():
        return PROVENANCE_FIXTURE
    import json as _json
    for f in sorted(base.glob("*.json")):
        try:
            data = _json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        for rec in data.get("files", []):
            if rec.get("kind") == "capture" and \
                    rec.get("provenance") == PROVENANCE_DEVICE:
                try:
                    if str(Path(rec.get("path", "")).resolve()) == target:
                        return PROVENANCE_DEVICE
                except OSError:
                    continue
    return PROVENANCE_FIXTURE


def _load_program(path: str | Path, program_index: int) -> tuple[Program, str]:
    """Load a program record from a local .syx file (bulk slot or single dump).

    Returns (Program, mode). Bulk files select slot `program_index`; single
    dumps always contain exactly one program (index arg must be 1).
    """
    syx = parse_file(path)
    if syx.mode == "single":
        if program_index != 1:
            raise ValueError(
                f"{path} is a single-dump file; it has only program 1 "
                f"(requested {program_index}).")
        return syx.programs[0], syx.mode
    if not 1 <= program_index <= len(syx.programs):
        raise ValueError(f"Program {program_index} out of range for {path}.")
    return syx.programs[program_index - 1], syx.mode


@dataclass(frozen=True)
class Capture:
    """One named SysEx capture (file on disk + provenance label)."""
    path: str
    provenance: str = PROVENANCE_FIXTURE
    note: str = ""

    def load(self, program: int = 1) -> Program:
        prog, _mode = _load_program(self.path, program)
        return prog


def classify_offset(offset: int) -> str:
    """Classify one relative program offset by the EXISTING registry only."""
    if 55 <= offset <= 63:
        return CLASS_NAME
    spec = next((p for p in BY_KEY.values() if p.offset == offset), None)
    return CLASS_KNOWN if spec is not None else CLASS_UNKNOWN


def key_for_offset(offset: int) -> str | None:
    for p in BY_KEY.values():
        if p.offset == offset:
            return p.key
    return None


@dataclass
class OffsetChange:
    """One changed byte inside the compared program record."""
    offset: int                 # relative 0x00..0x3F
    old: int
    new: int
    classification: str         # see CLASS_* above
    field: str                  # existing field_name() — never re-mapped here
    parameter_key: str | None
    old_semantic: str
    new_semantic: str
    confidence: str             # see CONF_* above

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ExperimentResult:
    """Structured outcome of an A/B SysEx comparison for one program slot."""
    before_path: str
    after_path: str
    program: int
    before_provenance: str
    after_provenance: str
    changes: list
    hypothesis_key: str | None = None
    verdict: str = "OBSERVED"       # CONFIRMED | AMBIGUOUS | NO_CHANGE | OBSERVED...
    expected_cc: int | None = None  # documented CC if the registry has one
    notes: list = field(default_factory=list)
    timestamp: str = ""
    service_changes: dict = field(default_factory=dict)

    # ------------------------------------------------------------- factories
    @classmethod
    def compare(cls, before: str | Path, after: str | Path, *,
                program: int = 1,
                hypothesis: str | None = None,
                before_provenance: str = PROVENANCE_FIXTURE,
                after_provenance: str = PROVENANCE_FIXTURE,
                notes: Iterable[str] = ()) -> "ExperimentResult":
        pa, _mode_a = _load_program(before, program)
        pb, _mode_b = _load_program(after, program)
        diffs = program_diff(pa, pb)

        changes: list[OffsetChange] = []
        service: dict = {}
        for d in diffs:
            if d.relative_offset is None:
                service[d.field.lower()] = (d.old, d.new)
                continue
            klass = classify_offset(d.relative_offset)
            key = key_for_offset(d.relative_offset)
            conf = CONF_REGISTRY if klass == CLASS_KNOWN else CONF_OBSERVED
            changes.append(OffsetChange(
                offset=d.relative_offset, old=d.old, new=d.new,
                classification=klass, field=field_name(d.relative_offset),
                parameter_key=key,
                old_semantic=semantic_value(d.relative_offset, d.old),
                new_semantic=semantic_value(d.relative_offset, d.new),
                confidence=conf))

        # ------------------------------------------- verdict rules (documented)
        verdict = "OBSERVED"
        result_notes = list(notes)
        if not changes:
            verdict = "NO_CHANGE"
        if hypothesis is not None:
            spec = BY_KEY.get(hypothesis)
            if spec is None:
                raise KeyError(f"Unknown hypothesis parameter: {hypothesis}")
            if spec.offset is None:
                raise ValueError(
                    f"{hypothesis} has no established SysEx offset; cannot "
                    "run an A/B experiment against it.")
            target = [c for c in changes if c.offset == spec.offset]
            others = [c for c in changes
                      if c.offset != spec.offset and c.classification != CLASS_NAME]
            name_only = bool(changes) and all(
                c.classification == CLASS_NAME for c in changes)
            if not target and not others:
                verdict = "NAME_ONLY" if name_only else "NO_CHANGE"
                result_notes.append("Hypothesised parameter byte did not change.")
            elif not target and others:
                # Hypothesis NOT supported; other bytes changed. We refuse to
                # attribute the effect to any of them automatically.
                verdict = "NOT_CONFIRMED"
                for c in changes:
                    if c.classification == CLASS_UNKNOWN:
                        c.confidence = CONF_AMBIGUOUS
                extra = ", ".join(f"0x{c.offset:02X}" for c in others)
                result_notes.append(
                    f"Hypothesised offset 0x{spec.offset:02X} unchanged, but "
                    f"other offsets changed ({extra}); NO automatic "
                    "attribution is made.")
            elif target and not others:
                verdict = "CONFIRMED"
                for c in target:
                    c.confidence = CONF_EXPERIMENTAL
                result_notes.append(
                    "Only the hypothesised offset changed (name bytes treated "
                    "as PATCH_NAME); parameter mapping EXPERIMENTALLY CONFIRMED.")
            else:
                verdict = "AMBIGUOUS"
                for c in changes:
                    if c.classification == CLASS_UNKNOWN:
                        c.confidence = CONF_AMBIGUOUS
                extra = ", ".join(f"0x{c.offset:02X}" for c in others)
                result_notes.append(
                    f"Additional unexpected offsets changed ({extra}); NOT "
                    "attributing the effect to any single byte automatically.")

        expected_cc = BY_KEY[hypothesis].cc if hypothesis else None
        return cls(
            before_path=str(before), after_path=str(after), program=program,
            before_provenance=before_provenance, after_provenance=after_provenance,
            changes=changes, hypothesis_key=hypothesis, verdict=verdict,
            expected_cc=expected_cc, notes=result_notes,
            timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            service_changes=service)

    # --------------------------------------------------------------- helpers
    @property
    def detected_offsets(self) -> list:
        return [c.offset for c in self.changes]

    def summary_text(self) -> str:
        lines = [
            f"A/B SysEx experiment — program {self.program:02d}",
            f"BEFORE: {self.before_path} [{self.before_provenance}]",
            f"AFTER : {self.after_path} [{self.after_provenance}]",
        ]
        if self.hypothesis_key:
            cc = (f"CC {self.expected_cc}" if self.expected_cc is not None
                  else "CC: not established")
            lines.append(f"Hypothesis: {self.hypothesis_key} (expected {cc})")
        lines.append(f"Verdict: {self.verdict}")
        if self.changes:
            lines.append("Changes:")
            for c in self.changes:
                sem = "" if c.classification == CLASS_NAME else \
                    f"  ({c.old_semantic} -> {c.new_semantic})"
                lines.append(
                    f"  0x{c.offset:02X}: {c.old:02X} -> {c.new:02X}  "
                    f"{c.field}  [{c.classification}] "
                    f"confidence={c.confidence}{sem}")
        else:
            lines.append("Changes: none")
        for n in self.notes:
            lines.append(f"Note: {n}")
        return "\n".join(lines)

    # ---------------------------------------------------------------- export
    def to_dict(self) -> dict:
        return {
            "schema": "jt4000m-experiment/1",
            "timestamp": self.timestamp,
            "program": self.program,
            "before": {"path": self.before_path,
                       "provenance": self.before_provenance},
            "after": {"path": self.after_path,
                      "provenance": self.after_provenance},
            "hypothesis": self.hypothesis_key,
            "expected_cc": self.expected_cc,
            "verdict": self.verdict,
            "evidence": EVIDENCE_AB_SYSEX if self.changes else "NONE",
            "changes": [c.to_dict() for c in self.changes],
            "detected_offsets": [f"0x{o:02X}" for o in self.detected_offsets],
            "service_changes": {k: list(v)
                                for k, v in self.service_changes.items()},
            "notes": self.notes,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    def to_markdown(self) -> str:
        d = self.to_dict()
        lines = [
            "# JT-4000M Experiment Report",
            "",
            f"- timestamp: `{d['timestamp']}`",
            f"- program: `{d['program']:02d}`",
            f"- before: `{d['before']['path']}` ({d['before']['provenance']})",
            f"- after: `{d['after']['path']}` ({d['after']['provenance']})",
            f"- hypothesis: `{d['hypothesis'] or '—'}`",
            "- expected CC: " + (str(d["expected_cc"])
                                 if d["expected_cc"] is not None
                                 else "not established"),
            f"- verdict: **{d['verdict']}**",
            f"- evidence: `{d['evidence']}`",
            "",
            "| offset | old | new | field | class | confidence | semantic |",
            "|--------|-----|-----|-------|-------|------------|----------|",
        ]
        for c in d["changes"]:
            lines.append(
                f"| 0x{c['offset']:02X} | {c['old']:02X} | {c['new']:02X} | "
                f"{c['field']} | {c['classification']} | {c['confidence']} | "
                f"{c['old_semantic']} → {c['new_semantic']} |")
        if d["notes"]:
            lines += ["", "## Notes"] + [f"- {n}" for n in d["notes"]]
        lines += ["", "> TRANSPORT VERIFIED and DEVICE BEHAVIOR VERIFIED are",
                  "> different claims; this report describes captured state",
                  "> differences only."]
        return "\n".join(lines)

    def save(self, stem: str | Path, formats=("json", "md")) -> list:
        stem = Path(stem)
        out: list[Path] = []
        if "json" in formats:
            p = stem.with_suffix(".json")
            p.write_text(self.to_json(), encoding="utf-8"); out.append(p)
        if "md" in formats:
            p = stem.with_suffix(".md")
            p.write_text(self.to_markdown(), encoding="utf-8"); out.append(p)
        return out


# Public alias requested in the P1.5 spec:
def compare_experiment(before, after, **kw) -> ExperimentResult:
    """Compare A.syx vs B.syx for one program slot -> structured evidence."""
    return ExperimentResult.compare(before, after, **kw)


# ---------------------------------------------------------------------------
# Evidence log (registry integration WITHOUT mutating the static registry)
# ---------------------------------------------------------------------------

DEFAULT_LOG_PATH = (Path(__file__).resolve().parent.parent
                    / "experiments" / "evidence_log.jsonl")


def append_evidence(result: ExperimentResult,
                    log_path: str | Path | None = None) -> Path:
    """Append one JSONL evidence record per changed offset.

    The Parameter Registry itself is NEVER rewritten automatically: hardware
    confirmations live in this append-only log and are joined with the
    registry at read time (see registry_status()).
    """
    path = Path(log_path or DEFAULT_LOG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for c in result.changes:
            rec = {
                "timestamp": result.timestamp,
                "kind": "offset_change",
                "offset": c.offset,
                "field": c.field,
                "parameter_key": c.parameter_key,
                "classification": c.classification,
                "confidence": c.confidence,
                "old": c.old,
                "new": c.new,
                "old_semantic": c.old_semantic,
                "new_semantic": c.new_semantic,
                "verdict": result.verdict,
                "hypothesis": result.hypothesis_key,
                "evidence": EVIDENCE_AB_SYSEX,
                "before": {"path": result.before_path,
                           "provenance": result.before_provenance},
                "after": {"path": result.after_path,
                          "provenance": result.after_provenance},
            }
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return path


def read_evidence(log_path: str | Path | None = None) -> list:
    path = Path(log_path or DEFAULT_LOG_PATH)
    if not path.exists():
        return []
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


def registry_status(log_path: str | Path | None = None) -> list:
    """Parameter Registry view enriched with evidence levels.

    Levels (per offset):
      known                     — present in the static registry (mapping only;
                                  NOT proof of behavior);
      experimentally_confirmed  — an A/B experiment with a matching hypothesis
                                  produced CONFIRMED verdict for this offset;
      observed                  — offset changed in some logged capture but is
                                  not in the registry (candidate; needs more
                                  experiments);
    Promotion rule (documented): an entry becomes experimentally_confirmed ONLY
    via an explicit-hypothesis A/B experiment whose verdict was CONFIRMED.
    Static mapping alone can NEVER produce that level.
    """
    records = read_evidence(log_path)
    confirmed: dict = {}
    observed: dict = {}
    for r in records:
        off = r["offset"]
        if r.get("confidence") == CONF_EXPERIMENTAL:
            confirmed[off] = r
        elif r.get("classification") == CLASS_UNKNOWN:
            observed.setdefault(off, r)

    out: list = []
    seen_offsets: set = set()
    for spec in BY_KEY.values():
        if spec.offset is None:
            continue
        seen_offsets.add(spec.offset)
        level = CONF_EXPERIMENTAL if spec.offset in confirmed else "known"
        out.append({"offset": spec.offset, "key": spec.key, "label": spec.label,
                    "level": level, "evidence": confirmed.get(spec.offset)})
    for off, r in sorted(observed.items()):
        if off in seen_offsets or 55 <= off <= 63:
            continue
        out.append({"offset": off, "key": None, "label": field_name(off),
                    "level": "observed", "evidence": r})
    return out
