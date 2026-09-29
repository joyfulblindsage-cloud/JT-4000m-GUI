"""P1.8 — Offline editor data model (no GUI, no MIDI, no hardware).

This module is a thin, presentation-independent *view layer* over the
existing domain model. It deliberately does NOT create a second patch/bank
model: ``PatchState`` wraps the existing immutable ``JTProgram``, and bank
operations keep returning real ``Bank`` objects.

Layer responsibilities (unchanged boundaries):
  syx.py         byte representation, packet structure, checksum
  model.py       parameter registry (definitions) + validation
  patch.py       JTProgram / Bank domain model
  discovery.py   offline evidence vocabulary (STATIC_KNOWN/OBSERVED/INFERRED)
  experiment.py  provenance vocabulary (REFERENCE_FIXTURE/CAPTURED_FROM_DEVICE)
  editor_model   THIS MODULE: definition/value/evidence views for a future GUI

Evidence levels used here are exactly the P1.7 vocabulary re-exported from
``discovery``; nothing in this module can ever produce HARDWARE_CONFIRMED
(see ``ParameterDefinition.evidence_level`` — the value is filtered through
``_OFFLINE_LEVELS``).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from . import discovery
from .experiment import PROVENANCE_FIXTURE, detect_provenance
from .model import (BY_KEY, BY_OFFSET, ENUM_OPTIONS, ParameterSpec,
                    display_value, writable_parameters)
from .patch import Bank, JTProgram
from .syx import PROGRAM_LEN, field_name

# Re-export the single project-wide evidence vocabulary (no second system).
LEVEL_STATIC = discovery.LEVEL_STATIC      # STATIC_KNOWN  (registry only)
LEVEL_OBSERVED = discovery.LEVEL_OBSERVED  # OBSERVED      (seen in fixtures)
LEVEL_INFERRED = discovery.LEVEL_INFERRED  # INFERRED      (statistical)
LEVEL_HARDWARE = discovery.LEVEL_HARDWARE  # vocabulary member ONLY; never emitted
_OFFLINE_LEVELS = frozenset({LEVEL_STATIC, LEVEL_OBSERVED, LEVEL_INFERRED})

NAME_RANGE = range(55, 64)                 # name bytes 0x37..0x3F


@dataclass(frozen=True)
class ParameterDefinition:
    """Editor-facing view of one registry entry. Never instantiated directly
    by callers — use ``definition_for(key)`` so evidence stays consistent."""
    key: str
    label: str
    offset: int | None            # None stays None if not established
    cc: int | None                # documented CC; NOT proof of anything
    kind: str
    minimum: int
    maximum: int
    default: int | None
    enum_options: tuple[tuple[int, str], ...]
    orientation: str
    group: str                    # metadata from registry `section` field
    notes: str
    editable: bool                # has an established SysEx offset
    writable: bool                # editable AND (not enum OR has confirmed table)
    source: str                   # "parameter_registry"
    evidence_level: str           # STATIC_KNOWN / OBSERVED / INFERRED only
    hardware_confirmed: bool      # structurally always False offline

    def to_dict(self) -> dict:
        return {
            "key": self.key, "label": self.label,
            "offset": f"0x{self.offset:02X}" if self.offset is not None else None,
            "cc": self.cc, "kind": self.kind,
            "minimum": self.minimum, "maximum": self.maximum,
            "default": self.default,
            "enum_options": [{"value": v, "label": l} for v, l in self.enum_options],
            "orientation": self.orientation, "group": self.group,
            "notes": self.notes, "editable": self.editable, "writable": self.writable,
            "source": self.source, "evidence_level": self.evidence_level,
            "hardware_confirmed": self.hardware_confirmed,
        }


def _corpus_observed_offsets() -> frozenset[int]:
    """Offsets whose VALUE variation is observed in the local fixture corpus.

    Uses the deterministic P1.7 discovery pipeline on the auto-discovered,
    deduplicated corpus. Purely informational; failures degrade to 'nothing
    observed' rather than guessing.
    """
    try:
        paths = [f.path for f in discovery.inventory(discovery_fixtures())]
        files = [(Path(p).name, discovery.parse_file(p)) for p in paths]
        profiles = discovery.offset_profiles(files)
        return frozenset(p.offset for p in profiles
                         if p.evidence_level == LEVEL_OBSERVED
                         and p.classification != discovery.CLS_NAME)
    except Exception:
        return frozenset()


def discovery_fixtures():
    from .knowledge import discover_fixtures
    return discover_fixtures()


_CORPUS_CACHE: dict[str, frozenset[int]] = {}


def _observed_offsets(refresh: bool = False) -> frozenset[int]:
    key = "v1"
    if refresh or key not in _CORPUS_CACHE:
        _CORPUS_CACHE[key] = _corpus_observed_offsets()
    return _CORPUS_CACHE[key]


def definition_for(key: str, *, observed: frozenset[int] | None = None) -> ParameterDefinition:
    spec = BY_KEY.get(key)
    if spec is None:
        raise KeyError(f"Unknown parameter: {key}")
    if observed is None:
        observed = _observed_offsets()
    level = LEVEL_STATIC
    if spec.offset is not None and spec.offset in observed:
        level = LEVEL_OBSERVED
    return ParameterDefinition(
        key=spec.key, label=spec.label, offset=spec.offset, cc=spec.cc,
        kind=spec.kind, minimum=spec.minimum, maximum=spec.maximum,
        default=spec.default,
        enum_options=tuple(ENUM_OPTIONS.get(spec.key, {}).items()),
        orientation=spec.orientation, group=spec.section, notes=spec.notes,
        editable=spec.offset is not None,
        writable=spec.key in _WRITABLE_KEYS,
        source="parameter_registry",
        evidence_level=_filter_hardware(level),
        hardware_confirmed=False,
    )


def _filter_hardware(level: str) -> str:
    """Guard rail: this layer can NEVER emit HARDWARE_CONFIRMED."""
    return level if level in _OFFLINE_LEVELS else LEVEL_STATIC


_WRITABLE_KEYS = frozenset(p.key for p in writable_parameters())


def all_definitions(*, refresh_corpus: bool = False) -> list[ParameterDefinition]:
    obs = _observed_offsets(refresh=refresh_corpus)
    return [definition_for(k, observed=obs) for k in BY_KEY]


def definitions_by_group(*, refresh_corpus: bool = False) -> dict[str, list[ParameterDefinition]]:
    """Group metadata comes from the registry `section` field — no fragile
    key-prefix heuristics."""
    out: dict[str, list[ParameterDefinition]] = {}
    for d in all_definitions(refresh_corpus=refresh_corpus):
        out.setdefault(d.group, []).append(d)
    return out


@dataclass(frozen=True)
class ParameterValue:
    """One parameter's value inside one concrete patch.

    Definition and value are separate concerns: the same ParameterDefinition
    describes every patch; ParameterValue carries raw/semantic/display per
    patch. Unknown values NEVER become None: raw survives, semantic becomes
    UNKNOWN_VALUE, display becomes 'Unknown (0xNN)' via the existing decoder.
    """
    key: str
    raw: int
    semantic: str          # symbolic label or "UNKNOWN_VALUE"
    display: str           # human string (may be "Unknown (0x07)")
    known: bool            # True if raw maps to a registry-established value
    editable: bool
    writable: bool
    evidence_level: str
    hardware_confirmed: bool

    def to_dict(self) -> dict:
        return {"key": self.key, "raw": self.raw, "raw_hex": f"0x{self.raw:02X}",
                "semantic": self.semantic, "display": self.display,
                "known": self.known, "editable": self.editable,
                "writable": self.writable, "evidence_level": self.evidence_level,
                "hardware_confirmed": self.hardware_confirmed}


def _symbolic(spec: ParameterSpec, raw: int) -> tuple[str, bool]:
    """Return (semantic_symbol_or_UNKNOWN_VALUE, known_flag). No invention."""
    if spec.kind == "enum":
        labels = ENUM_OPTIONS.get(spec.key, {})
        if raw in labels:
            return labels[raw], True
        return "UNKNOWN_VALUE", False
    return str(raw), True


def value_for(patch: JTProgram, key: str, *, observed: frozenset[int] | None = None) -> ParameterValue:
    spec = BY_KEY.get(key)
    if spec is None:
        raise KeyError(f"Unknown parameter: {key}")
    if spec.offset is None:
        raise ValueError(f"Parameter {key} has no established SysEx offset.")
    raw = patch.data[spec.offset]
    sem, known = _symbolic(spec, raw)
    d = definition_for(key, observed=observed if observed is not None else _observed_offsets())
    return ParameterValue(key=key, raw=raw, semantic=sem,
                          display=display_value(key, raw), known=known,
                          editable=d.editable, writable=d.writable,
                          evidence_level=d.evidence_level,
                          hardware_confirmed=False)


@dataclass(frozen=True)
class PatchState:
    """Editor-facing wrapper around ONE existing JTProgram (no duplication).

    The underlying program bytes remain authoritative: unknown bytes stay in
    ``program.data`` and are exposed read-only via ``unknown_bytes``. All
    mutations go through the existing validated model functions and return
    new PatchState objects wrapping new JTPrograms (copy-on-write).
    """
    program: JTProgram
    provenance: str = PROVENANCE_FIXTURE
    source_path: str | None = None
    edit_source: str = "offline_editor"   # source-aware ops (future automation/MIDI)

    # ---- construction ----------------------------------------------------
    @classmethod
    def from_program(cls, program: JTProgram, *, provenance: str | None = None,
                     source_path: str | Path | None = None) -> "PatchState":
        if provenance is None:
            provenance = (detect_provenance(source_path)
                          if source_path is not None else PROVENANCE_FIXTURE)
        return cls(program, provenance,
                   str(Path(source_path)) if source_path is not None else None)

    # ---- identity --------------------------------------------------------
    @property
    def index(self) -> int:
        return self.program.index

    @property
    def name(self) -> str:
        return self.program.name

    @property
    def data(self) -> bytes:
        return self.program.data

    # ---- values ----------------------------------------------------------
    def get_raw(self, key: str) -> int:
        return self.program.get_parameter(key)

    def get_semantic(self, key: str) -> str:
        return value_for(self.program, key).semantic

    def get_display(self, key: str) -> str:
        return value_for(self.program, key).display

    def value(self, key: str) -> ParameterValue:
        return value_for(self.program, key)

    def all_values(self) -> dict[str, ParameterValue]:
        obs = _observed_offsets()
        return {k: value_for(self.program, k, observed=obs)
                for k, s in BY_KEY.items() if s.offset is not None}

    def unknown_bytes(self) -> dict[int, int]:
        """Every byte not covered by a registry offset or the name field.

        Read-only view onto program.data — there is NO parallel storage, so
        these bytes cannot be lost by editing known parameters.
        """
        mapped = {s.offset for s in BY_KEY.values() if s.offset is not None}
        return {i: self.program.data[i] for i in range(PROGRAM_LEN)
                if i not in mapped and i not in NAME_RANGE}

    def name_bytes(self) -> bytes:
        return self.program.data[55:64]

    # ---- mutation (validated, copy-on-write) ----------------------------
    def set_parameter(self, key: str, value: int) -> "PatchState":
        # model.set_parameter enforces range + confirmed-enum validation and
        # touches exactly one byte; everything else is preserved verbatim.
        return PatchState(self.program.set_parameter(key, value),
                          self.provenance, self.source_path, self.edit_source)

    def set_parameters(self, updates: Mapping[str, int]) -> "PatchState":
        """Batch edit with all-or-nothing semantics: validation happens
        against the current state first, so a failure leaves no partially
        modified patch."""
        for k, v in updates.items():
            spec = BY_KEY.get(k)
            if spec is None:
                raise KeyError(f"Unknown parameter: {k}")
            # Cheap pre-validation pass; full validation still happens in
            # set_parameter during application.
            self.program.get_parameter(k)
            if not isinstance(v, int):
                raise ValueError(f"{k} must be an integer.")
        cur = self
        for k in sorted(updates):
            cur = cur.set_parameter(k, updates[k])
        return cur

    def set_name(self, name: str) -> "PatchState":
        return PatchState(self.program.set_name(name),
                          self.provenance, self.source_path, self.edit_source)

    # ---- snapshots / diff -----------------------------------------------
    def snapshot(self) -> "PatchState":
        """Immutable read-only handle (JTProgram is already frozen)."""
        return self

    def diff_to(self, other: "PatchState") -> list[dict]:
        """Byte-level diff using the existing field_name() classification —
        parameter/name/unknown offsets are reported separately, never merged."""
        out = []
        for off in range(PROGRAM_LEN):
            a, b = self.program.data[off], other.program.data[off]
            if a != b:
                spec = BY_OFFSET.get(off)
                if off in NAME_RANGE:
                    category = "NAME"
                elif spec is not None:
                    # Registry owns this offset; syx.FIELDS may carry a
                    # different historical label — report both, never merge.
                    category = "PARAMETER"
                else:
                    category = "UNKNOWN"
                out.append({"offset": off, "old": a, "new": b,
                            "field": field_name(off), "category": category})
        return out

    # ---- serialization boundary -----------------------------------------
    def to_json_dict(self) -> dict:
        """Data-model representation for inspection/export. Raw SYX bytes stay
        authoritative storage; this JSON is NOT a replacement for .syx."""
        return {
            "schema": "jt4000m.editor_model/PatchState v1",
            "index": self.index,
            "name": self.name,
            "provenance": self.provenance,
            "source_path": self.source_path,
            "edit_source": self.edit_source,
            "raw_data_hex": self.program.data.hex(),
            "parameters": [v.to_dict() for v in self.all_values().values()],
            "unknown_bytes": {f"0x{i:02X}": b for i, b in self.unknown_bytes().items()},
            "name_bytes_hex": self.name_bytes().hex(),
        }


class EditorModel:
    """Session-level controller: which file/bank/patch is being edited.

    Holds references to the EXISTING Bank domain object; it never copies or
    replaces it. Dirty tracking here mirrors PatchLibrary.dirty but lives at
    the editor-session level (a loaded file plus an in-progress patch edit).
    """

    def __init__(self) -> None:
        self._bank: Bank | None = None
        self._path: Path | None = None
        self._provenance: str = "REFERENCE_FIXTURE"
        self._selected: int = 1
        self._working: PatchState | None = None   # uncommitted patch edits
        self._dirty: bool = False

    # ---- loading ---------------------------------------------------------
    def load_bank(self, path: str | Path, *, provenance: str | None = None) -> Bank:
        p = Path(path)
        bank = Bank.load(p)
        self._bank = bank
        self._path = p.resolve()
        self._provenance = provenance or detect_provenance(p)
        self._selected = 1
        self._working = None
        self._dirty = False
        return bank

    @property
    def bank(self) -> Bank:
        if self._bank is None:
            raise RuntimeError("No bank loaded.")
        return self._bank

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def provenance(self) -> str:
        return self._provenance

    @property
    def dirty(self) -> bool:
        return self._dirty

    @property
    def selected(self) -> int:
        return self._selected

    def select(self, index: int) -> PatchState:
        if not 1 <= index <= 32:
            raise IndexError("Program index must be 1..32.")
        self._selected = index
        self._working = None
        return self.current_patch()

    def current_patch(self) -> PatchState:
        """The patch as currently edited (working copy if present)."""
        if self._working is not None and self._working.index == self._selected:
            return self._working
        return PatchState.from_program(self.bank.get(self._selected),
                                       provenance=self._provenance,
                                       source_path=self._path)

    # ---- editing ---------------------------------------------------------
    def edit_parameter(self, key: str, value: int) -> PatchState:
        self._working = self.current_patch().set_parameter(key, value)
        self._dirty = True
        return self._working

    def edit_parameters(self, updates: Mapping[str, int]) -> PatchState:
        self._working = self.current_patch().set_parameters(updates)
        self._dirty = True
        return self._working

    def edit_name(self, name: str) -> PatchState:
        self._working = self.current_patch().set_name(name)
        self._dirty = True
        return self._working

    def commit(self) -> Bank:
        """Write the working patch back into the bank (still in memory)."""
        if self._working is None:
            return self.bank
        self._bank = self.bank.replace(self._selected, self._working.program)
        self._working = None
        return self._bank

    def revert(self) -> None:
        self._working = None
        self._dirty = self._bank_modified()

    def _bank_modified(self) -> bool:
        if self._path is None:
            return True
        try:
            return self.bank.to_sysex() != self._path.read_bytes()
        except OSError:
            return True

    # ---- saving ----------------------------------------------------------
    def save(self, path: str | Path | None = None) -> Path:
        """Persist via the existing byte-preserving Bank.save(); after a
        successful export the session is clean. Provenance of the saved file
        is whatever the session started with — saving NEVER promotes a
        REFERENCE_FIXTURE-derived file to CAPTURED_FROM_DEVICE (only a real
        capture does that)."""
        target = Path(path) if path is not None else self._path
        if target is None:
            raise RuntimeError("No target path for save.")
        self.commit()
        payload = self.bank.save(target)
        self._path = target.resolve()
        self._dirty = False
        return target

    # ---- helpers ---------------------------------------------------------
    def patch_states(self) -> list[PatchState]:
        return [PatchState.from_program(p, provenance=self._provenance,
                                        source_path=self._path)
                for p in self.bank.programs]


# ---------------------------------------------------------------------------
# Registry validation (P1.8 §25) — runs over the EXISTING registry, report-only
# ---------------------------------------------------------------------------
def validate_registry() -> list[str]:
    problems: list[str] = []
    seen_keys: set[str] = set()
    seen_offsets: dict[int, str] = {}
    seen_cc: dict[int, str] = {}
    for spec in BY_KEY.values():
        if spec.key in seen_keys:
            problems.append(f"duplicate key {spec.key}")
        seen_keys.add(spec.key)
        if spec.offset is not None:
            if not 0 <= spec.offset < PROGRAM_LEN:
                problems.append(f"{spec.key}: offset {spec.offset} outside 0..63")
            if spec.offset in seen_offsets:
                problems.append(
                    f"conflicting offsets: {spec.key} and {seen_offsets[spec.offset]}"
                    f" both claim 0x{spec.offset:02X}")
            seen_offsets[spec.offset] = spec.key
        if spec.cc is not None and not 0 <= spec.cc <= 127:
            problems.append(f"{spec.key}: CC {spec.cc} outside 0..127")
        if spec.cc in seen_cc and spec.cc is not None:
            problems.append(f"CC {spec.cc} claimed by {spec.key} and {seen_cc[spec.cc]}")
        if spec.cc is not None:
            seen_cc[spec.cc] = spec.key
        if spec.minimum > spec.maximum:
            problems.append(f"{spec.key}: min > max")
        for v in ENUM_OPTIONS.get(spec.key, {}):
            if not spec.minimum <= v <= spec.maximum or not 0 <= v <= 255:
                problems.append(f"{spec.key}: enum value {v} outside valid byte range")
    return problems


# ---------------------------------------------------------------------------
# Bidirectional mapping API (explicit ambiguity; never silently picks one)
# ---------------------------------------------------------------------------
def keys_for_offset(offset: int) -> list[str]:
    return sorted(k for k, s in BY_KEY.items() if s.offset == offset)


def keys_for_cc(cc: int) -> list[str]:
    return sorted(k for k, s in BY_KEY.items() if s.cc == cc)


def resolve_key(name: str) -> str:
    """Resolve a key / offset ('0x0C', 12) / CC ('cc:74') to parameter key(s).
    Returns a single key when unambiguous, otherwise raises with candidates."""
    s = str(name).strip().lower()
    if s.startswith("cc:"):
        cands = keys_for_cc(int(s[3:]))
        if len(cands) == 1:
            return cands[0]
        raise ValueError(f"CC {s[3:]} is ambiguous: {cands or 'no mapping'}")
    if s.startswith("0x") or s.isdigit():
        off = int(s, 16) if s.startswith("0x") else int(s)
        cands = keys_for_offset(off)
        if len(cands) == 1:
            return cands[0]
        raise ValueError(f"offset 0x{off:02X} is ambiguous: {cands or 'no mapping'}")
    if s in BY_KEY:
        return s
    raise KeyError(f"Unknown parameter: {name}")
