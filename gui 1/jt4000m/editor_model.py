"""P1.8/P1.9 — Offline editor data model + public Editor API contract
(no GUI, no MIDI, no hardware).

This module is a thin, presentation-independent *view layer* over the
existing domain model. It deliberately does NOT create a second patch/bank
model: ``PatchState`` wraps the existing immutable ``JTProgram``, and bank
operations keep returning real ``Bank`` objects.

P1.9 additions (docs/EDITOR_API.md is the normative contract):
  * stable exception types (UnknownParameterError / ParameterValueError /
    PatchIndexError / ParameterNotEditableError / BankFullError /
    SessionFormatError) — subclasses of the pre-existing builtin raises, so
    old `except KeyError/ValueError/IndexError` code keeps working;
  * read-only parameter access by offset (get_parameter_by_offset);
  * group listing/filtering from registry metadata only;
  * search / view-sorting / reorder / merge over the fixed 32-slot bank;
  * session JSON persistence (state + edits ONLY — SYX stays authoritative);
  * snapshot()/restore() convenience over the immutable copy-on-write model
    (NO undo framework here — PatchLibrary remains the history owner).

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
from .syx import NAME_START, PROGRAM_LEN, field_name

# Re-export the single project-wide evidence vocabulary (no second system).
LEVEL_STATIC = discovery.LEVEL_STATIC      # STATIC_KNOWN  (registry only)
LEVEL_OBSERVED = discovery.LEVEL_OBSERVED  # OBSERVED      (seen in fixtures)
LEVEL_INFERRED = discovery.LEVEL_INFERRED  # INFERRED      (statistical)
LEVEL_HARDWARE = discovery.LEVEL_HARDWARE  # vocabulary member ONLY; never emitted
_OFFLINE_LEVELS = frozenset({LEVEL_STATIC, LEVEL_OBSERVED, LEVEL_INFERRED})

# Name field = the LAST nine bytes of the 64-byte record: offsets 55..63
# (0x37..0x3F).  NAME_START == PROGRAM_LEN - 9 == 55.  Byte 54 (0x36) is a
# structural fixture-constant byte and must NEVER be treated as part of the
# name (rename evidence test: changed_offsets never include 54).
NAME_RANGE = range(NAME_START, PROGRAM_LEN)  # == range(55, 64) — 9 bytes

# Canonical group order — taken from the registry `section` metadata values.
_GROUP_ORDER = ("OSCILLATORS", "FILTER", "VCF ENVELOPE", "VCA ENVELOPE",
                "LFO", "MODULATION", "UNMAPPED")


# ---------------------------------------------------------------------------
# EMPTY SLOT SEMANTICS — ARCHITECTURAL RULE (P1.9, fixed by decision).
#
# In the current reverse-engineering model there is NO proven empty-slot
# state. Consequences that MUST hold across the whole codebase:
#
#   * A JT-4000M bank always contains exactly 32 VALID program slots.
#   * The name "EMPTY" does NOT mean the slot is empty: ALL EMPTY.syx
#     records carry non-zero registry-parameter bytes (init defaults), so
#     they are ordinary, valid JTPrograms.
#   * Zero bytes are NOT evidence of emptiness; unknown bytes are never
#     classified by guessing.
#   * Emptiness MUST NOT be inferred from names, padding or any heuristic.
#   * If a genuine empty-slot marker is ever proven by hardware evidence, it
#     must enter as a separate, explicitly documented policy (e.g. a public
#     ``is_empty(program)`` fed by captured evidence) — never derived from
#     the string "EMPTY". No such function exists today, on purpose.
#
# Therefore every slot is occupied, and merge conflict modes below operate
# on "occupied slot" semantics only.
# ---------------------------------------------------------------------------


def _slot_is_source_template(program: JTProgram) -> bool:
    """Internal helper: True iff a record is byte-identical to the source
    bank's own slot template (the literal padded name b"EMPTY    " plus
    all-zero data). This is a byte-equality fact, NOT an emptiness claim:
    e.g. Synthmania's all-zero unnamed records qualify as neutral fillers
    for skip-merge purposes, while ALL EMPTY.syx records (non-zero data)
    do NOT — they are treated as occupied, valid patches."""
    return program.data[NAME_START:] == b"EMPTY    " and not any(program.data)

# ---------------------------------------------------------------------------
# P1.9 — Public API exception contract (docs/EDITOR_API.md).
# Each type subclasses the builtin that the pre-P1.9 code already raised, so
# every existing `except KeyError / ValueError / IndexError` keeps working.
# ---------------------------------------------------------------------------
class EditorAPIError(Exception):
    """Base class for all public Editor API errors."""


class UnknownParameterError(EditorAPIError, KeyError):
    """Requested parameter key is not in the registry."""


class ParameterValueError(EditorAPIError, ValueError):
    """Value fails registry validation (range / enum / type). NEVER clamped
    silently — an out-of-range value always raises instead."""


class ParameterNotEditableError(ParameterValueError):
    """The parameter exists but has no established SysEx offset (or its enum
    table is unconfirmed), so it cannot be written through this API."""


class PatchIndexError(EditorAPIError, IndexError):
    """Patch slot outside the fixed 1..32 bank range."""


class BankFullError(EditorAPIError, ValueError):
    """A merge/reorder would exceed the fixed 32-slot JT-4000M bank format.
    Explicit error — silent truncation is forbidden."""


class SessionFormatError(EditorAPIError, ValueError):
    """An editor session JSON is missing/corrupt/incompatible."""


def _wrap_builtin_errors(fn):
    """Translate the legacy builtin raises of the domain layer into the
    public API contract WITHOUT changing any behaviour underneath."""
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except KeyError as e:
            raise UnknownParameterError(str(e).strip("'\"")) from e
        except PatchIndexError:
            raise
        except IndexError as e:
            raise PatchIndexError(str(e)) from e
        except ParameterValueError:
            raise
        except ValueError as e:
            msg = str(e)
            if "no established SysEx offset" in msg or "no confirmed enum" in msg:
                raise ParameterNotEditableError(msg) from e
            raise ParameterValueError(msg) from e
    wrapper.__name__ = getattr(fn, "__name__", "wrapped")
    wrapper.__doc__ = fn.__doc__
    return wrapper


JTProgram.get_parameter = _wrap_builtin_errors(JTProgram.get_parameter)
JTProgram.set_parameter = _wrap_builtin_errors(JTProgram.set_parameter)
Bank.get = _wrap_builtin_errors(Bank.get)
Bank.replace = _wrap_builtin_errors(Bank.replace)
Bank.copy_program = _wrap_builtin_errors(Bank.copy_program)
Bank.swap = _wrap_builtin_errors(Bank.swap)
Bank.move = _wrap_builtin_errors(Bank.move)
Bank.set_parameter = _wrap_builtin_errors(Bank.set_parameter)
Bank.reset_parameter = _wrap_builtin_errors(Bank.reset_parameter)


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


def _corpus_profiles():
    """Deterministic P1.7 offset profiles over the local fixture corpus."""
    try:
        paths = [f.path for f in discovery.inventory(discovery_fixtures())]
        files = [(Path(p).name, discovery.parse_file(p)) for p in paths]
        return discovery.offset_profiles(files)
    except Exception:
        return []


def _corpus_classification() -> dict[int, dict]:
    """offset -> {classification, evidence_level} from the P1.7 pipeline."""
    return {p.offset: {"classification": p.classification,
                       "evidence_level": p.evidence_level}
            for p in _corpus_profiles()}


def _observed_offsets(refresh: bool = False) -> frozenset[int]:
    key = "v1"
    if refresh or key not in _CORPUS_CACHE:
        _CORPUS_CACHE[key] = _corpus_observed_offsets()
    return _CORPUS_CACHE[key]


def definition_for(key: str, *, observed: frozenset[int] | None = None) -> ParameterDefinition:
    spec = BY_KEY.get(key)
    if spec is None:
        raise UnknownParameterError(f"Unknown parameter: {key}")
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
        raise UnknownParameterError(f"Unknown parameter: {key}")
    if spec.offset is None:
        raise ParameterNotEditableError(
            f"Parameter {key} has no established SysEx offset.")
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
        return self.program.data[NAME_START:]

    # ---- P1.9 public-contract accessors ---------------------------------
    def get_parameter(self, key: str) -> ParameterValue:
        """Public read API: one full ParameterValue (raw/semantic/display)."""
        return value_for(self.program, key)

    def get_parameter_by_offset(self, offset: int) -> list[ParameterValue]:
        """Read-only access by program-relative SysEx offset.

        Returns a LIST because the mapping may be ambiguous; an empty list
        means the offset is UNKNOWN (never guessed, never auto-named).
        """
        keys = keys_for_offset(offset)
        return [value_for(self.program, k) for k in keys]

    def unknown_parameters(self) -> list[dict]:
        """Unknown-byte dossier view for a future GUI developer mode.

        Classification comes from the deterministic P1.7 discovery pipeline
        when available; meaning stays UNKNOWN always — no naming, no
        promotion to hardware evidence.
        """
        cls_map = _corpus_classification()
        out = []
        for off, raw in sorted(self.unknown_bytes().items()):
            c = cls_map.get(off, {})
            out.append({
                "offset": off,
                "offset_hex": f"0x{off:02X}",
                "raw": raw,
                "raw_hex": f"0x{raw:02X}",
                "classification": c.get("classification", discovery.CLS_UNKNOWN),
                "evidence_level": c.get("evidence_level", LEVEL_INFERRED),
                "meaning": "UNKNOWN",
                "hardware_confirmation": False,
            })
        return out

    # ---- mutation (validated, copy-on-write) ----------------------------
    def set_parameter(self, key: str, value: int) -> "PatchState":
        # model.set_parameter enforces range + confirmed-enum validation and
        # touches exactly one byte; everything else is preserved verbatim.
        return PatchState(self.program.set_parameter(key, value),
                          self.provenance, self.source_path, self.edit_source)

    def set_parameters(self, updates: Mapping[str, int]) -> "PatchState":
        """Batch edit with all-or-nothing semantics: validation happens
        against the current state FIRST (range + confirmed-enum checks via
        the registry), so a failure leaves no partially modified patch.
        Out-of-range values raise ParameterValueError — never clamped."""
        for k, v in updates.items():
            spec = BY_KEY.get(k)
            if spec is None:
                raise UnknownParameterError(f"Unknown parameter: {k}")
            if not isinstance(v, int):
                raise ParameterValueError(f"{k} must be an integer.")
            if spec.offset is None:
                raise ParameterNotEditableError(
                    f"Parameter {k} has no established SysEx offset.")
            if not spec.minimum <= v <= spec.maximum:
                raise ParameterValueError(
                    f"{k} must be between {spec.minimum} and {spec.maximum}.")
            opts = ENUM_OPTIONS.get(k)
            if spec.kind == "enum" and opts:
                if v not in opts:
                    raise ParameterValueError(
                        f"{k}: {v} is not a confirmed enum value "
                        f"(allowed: {sorted(opts)}).")
        cur = self
        for k in sorted(updates):
            cur = cur.set_parameter(k, updates[k])
        return cur

    def reset_parameter(self, key: str) -> "PatchState":
        """Restore one parameter to its registry default (None default ->
        ParameterNotEditableError). Only the mapped byte changes."""
        d = definition_for(key)
        if d.default is None:
            raise ParameterNotEditableError(
                f"{key}: no documented default; refusing to invent one.")
        return self.set_parameter(key, d.default)

    def set_name(self, name: str) -> "PatchState":
        return PatchState(self.program.set_name(name),
                          self.provenance, self.source_path, self.edit_source)

    def rename(self, name: str) -> "PatchState":
        """Public-contract alias of set_name (only Name[0..8] bytes change)."""
        return self.set_name(name)

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
        # Baseline bytes of the last successful load/save.  This is the ONE
        # dirty-state source of truth for editor sessions (P1.10 §6): the GUI
        # never computes dirty itself — it asks is_dirty().
        self._baseline: bytes | None = None

    # ---- loading ---------------------------------------------------------
    def load_bank(self, path: str | Path, *, provenance: str | None = None) -> Bank:
        p = Path(path)
        bank = Bank.load(p)
        self._bank = bank
        self._path = p.resolve()
        self._provenance = provenance or detect_provenance(p)
        self._selected = 1
        self._working = None
        self._baseline = bank.to_sysex()
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

    @property
    def loaded(self) -> bool:
        """P1.15 boundary: public 'is a bank loaded?' predicate so the GUI
        never needs to inspect ``editor._bank`` (P1.11 rule)."""
        return self._bank is not None

    def get_patch_name(self, index: int) -> str:
        """P1.15 boundary: read one slot's name without materialising a
        full PatchState and without touching private state."""
        self._require_loaded()
        return self.bank.get(index).name

    def select(self, index: int) -> PatchState:
        if not 1 <= index <= 32:
            raise PatchIndexError("Program index must be 1..32.")
        self._selected = index
        self._working = None
        return self.current_patch()

    # ---- P1.9 public-contract aliases ------------------------------------
    def save_bank(self, path=None) -> bytes:
        """Public-contract save: persists and returns the exported bytes."""
        target = Path(path) if path is not None else self._path
        self.save(target)
        return Path(target).read_bytes()

    def patch_count(self) -> int:
        return len(self.bank.programs)             # always 32 (bank invariant)

    def patches(self) -> list[PatchState]:
        return self.patch_states()

    def get_patch(self, index: int) -> PatchState:
        """Patch at slot `index` WITHOUT changing the selection."""
        return PatchState.from_program(self.bank.get(index),
                                       provenance=self._provenance,
                                       source_path=self._path)

    def select_patch(self, index: int) -> PatchState:
        return self.select(index)

    def current(self) -> PatchState:
        return self.current_patch()

    def is_dirty(self) -> bool:
        return self._dirty

    def mark_dirty(self, value: bool) -> None:
        """P1.23 public dirty-projection hook (used by EditorHistory after a
        restore).  This replaces the old direct private-attribute write from
        inside EditorHistory.undo()/redo() — a P1.11 boundary violation.
        Deliberately NOT named ``set_dirty`` so it can never be confused with
        a user edit: no history push, no notification, byte state untouched."""
        self._dirty = bool(value)

    def get_parameter(self, key: str) -> ParameterValue:
        """Read a parameter of the CURRENT patch (public contract)."""
        return self.current_patch().get_parameter(key)

    def set_parameter(self, key: str, value: int) -> PatchState:
        return self.edit_parameter(key, value)

    def set_slot_parameter(self, index: int, key: str, value: int) -> PatchState:
        """P1.15: immediate byte-preserving slot mutation through the same
        validated model helpers as every other edit (single-byte change,
        unknown bytes preserved).  Unlike ``set_parameter`` this does NOT
        create an uncommitted working copy — it writes into the bank right
        away, which is what per-slot operations from the GUI need so that a
        history snapshot taken BEFORE the call can undo it exactly.

        No-op contract: if the slot already holds the value, nothing changes
        and no session mutation occurs (dirty flag untouched)."""
        self._require_loaded()
        spec = BY_KEY[key]                      # raises UnknownParameterError
        prog = self._bank.get(index)            # raises on bad index
        if prog.get_parameter(key) == value:
            return self.get_patch(index)
        new_prog = prog.set_parameter(key, value)
        # P1.15 corrective fix: fold any pending working copy of THIS slot
        # into the bank before mutating (same pattern as duplicate/swap/move/
        # replace/rename_patch).  A bare `self._working = None` here would
        # silently DISCARD uncommitted edits — e.g. a rename made through the
        # GUI and then overwritten by a per-slot parameter change.
        if self._working is not None and self._working.index == index:
            self.commit()
        else:
            self._working = None
        self._bank = self._bank.replace(index, new_prog)
        self._dirty = self._session_modified()
        return self.get_patch(index)

    def rename(self, name: str) -> PatchState:
        return self.edit_name(name)

    # ---- groups / search / filter / sort (P1.9) ---------------------------
    def list_groups(self) -> list[str]:
        """Registry sections in canonical order — metadata only, no
        key-prefix heuristics."""
        seen = {d.group for d in all_definitions()}
        order = [g for g in _GROUP_ORDER if g in seen]
        return order + sorted(seen - set(_GROUP_ORDER))

    def parameters(self, group: str | None = None) -> list[ParameterDefinition]:
        defs = all_definitions()
        if group is None:
            return defs
        out = [d for d in defs if d.group == group]
        if not out:
            raise UnknownParameterError(f"Unknown group: {group}")
        return out

    def search_patches(self, query: str) -> list[PatchState]:
        """Case-insensitive substring search over patch NAMES (stable order
        by slot index). Read-only: never mutates the bank."""
        q = query.lower()
        return [ps for ps in self.patch_states() if q in ps.name.lower()]

    def filter_by_group(self, group: str) -> list[ParameterDefinition]:
        return self.parameters(group)

    def filter_by_parameter(self, keys) -> list[ParameterDefinition]:
        wanted = set(keys)
        out = [d for d in all_definitions() if d.key in wanted]
        missing = wanted - {d.key for d in out}
        if missing:
            raise UnknownParameterError(f"Unknown parameters: {sorted(missing)}")
        return out

    def filter_by_value(self, key: str, predicate) -> list[PatchState]:
        """Slots whose ParameterValue satisfies predicate(ParameterValue)."""
        return [ps for ps in self.patch_states()
                if predicate(ps.get_parameter(key))]

    def view_sorted(self, by: str = "name") -> list[PatchState]:
        """ORDERED VIEW ONLY — the underlying bank is NOT modified.
        Use reorder() when an actual slot reordering is wanted; the two are
        deliberately different operations."""
        pats = self.patch_states()
        if by == "name":
            return sorted(pats, key=lambda p: (p.name.upper(), p.index))
        if by == "index":
            return sorted(pats, key=lambda p: p.index)
        if by.startswith("param:"):
            key = by[6:]
            BY_KEY[key]  # raises KeyError for bad keys
            return sorted(pats, key=lambda p: (p.get_raw(key), p.index))
        raise ValueError(f"Unknown sort spec: {by!r} "
                         "(use 'name', 'index' or 'param:<key>')")

    def reorder(self, ordered_states) -> Bank:
        """MUTATING view-order -> slot assignment. The raw record of every
        supplied patch is preserved byte-for-byte; it only moves slots."""
        states = list(ordered_states)
        if len(states) != 32:
            raise BankFullError(
                f"A JT-4000M bank has exactly 32 slots; got {len(states)}.")
        progs = [JTProgram(i + 1, bytes(p.data)) for i, p in enumerate(states)]
        self._bank = Bank(tuple(progs), source_header=self.bank.source_header)
        self._working = None
        self._dirty = True
        return self._bank

    # ---- merge (fixed 32-slot semantics; NO silent truncation) -----------
    MERGE_MODES = ("replace", "skip", "error")

    def duplicate_patch(self, source: int, destination: int) -> PatchState:
        """Copy program record `source` into slot `destination`.
        Byte-preserving; both slots stay occupied (there is no empty-slot
        concept — see EMPTY SLOT SEMANTICS rule at module top).

        No-op contract (P1.12 §9): copying a slot onto itself, or onto a
        slot that already holds byte-identical data, changes nothing."""
        self._require_loaded()
        if not (1 <= source <= 32 and 1 <= destination <= 32):
            raise PatchIndexError("Slot index must be 1..32.")
        if bytes(self._bank.get(source).data) == bytes(self._bank.get(destination).data):
            return self.get_patch(destination)          # no-op
        # P1.15 corrective fix: fold a pending working copy of the SOURCE
        # slot first — otherwise duplicating the currently edited patch
        # would copy the STALE committed record and silently discard the
        # user's uncommitted edit (state-change semantics apply to the
        # state the USER sees, not only to the committed bank).
        if self._working is not None and self._working.index == source:
            self.commit()
        elif bytes(self.current_patch().data) == bytes(self._bank.get(destination).data):
            # destination equals the on-screen (working) patch → duplicating
            # it onto itself is a genuine no-op for the visible state.
            return self.get_patch(destination)
        else:
            self._working = None
        self._bank = self._bank.copy_program(source, destination)
        self._dirty = self._session_modified()
        return self.get_patch(destination)

    def swap_patches(self, a: int, b: int) -> None:
        """Swap two slots. Raw records move byte-for-byte; only indices are
        renumbered. Program count stays exactly 32.

        No-op contract (P1.15 corrective): a swap that leaves the bank
        byte-identical — swap(x, x) OR swapping two slots that already hold
        identical records (common in ALL INIT SAW.syx) — changes nothing and
        must NOT discard an uncommitted working copy or flip dirty.  The
        decision is made on the RESULTING BANK STATE, not merely on index
        equality."""
        self._require_loaded()
        if a == b:
            return                                      # no-op
        candidate = self._bank.swap(a, b)
        if bytes(candidate.to_sysex()) == bytes(self._bank.to_sysex()):
            return                                      # state unchanged → no-op
        self._bank = candidate
        self._working = None
        self._dirty = self._session_modified()

    def move_patch(self, source: int, destination: int) -> None:
        """Shift the record at `source` to `destination` (Bank.move
        semantics); every other raw record is preserved byte-for-byte.

        No-op contract (P1.15 corrective): move(x, x) does nothing; a move
        whose resulting bank is byte-identical to the current bank (e.g. all
        slots hold the same record) is also a genuine no-op and must not
        discard the pending working copy."""
        self._require_loaded()
        if source == destination:
            return                                      # no-op
        candidate = self._bank.move(source, destination)
        if bytes(candidate.to_sysex()) == bytes(self._bank.to_sysex()):
            return                                      # state unchanged → no-op
        self._bank = candidate
        self._working = None
        self._dirty = self._session_modified()

    def replace_patch(self, destination: int, patch) -> PatchState:
        """Replace one slot with another patch's record (byte-for-byte).
        Accepts PatchState or JTProgram.

        No-op contract: replacing a slot with identical bytes changes
        nothing and does not flip dirty."""
        self._require_loaded()
        data = getattr(patch, "data", None)
        if data is None:
            raise TypeError("replace_patch expects PatchState or JTProgram")
        new_prog = JTProgram(destination, bytes(data))
        if bytes(new_prog.data) == bytes(self._bank.get(destination).data):
            return self.get_patch(destination)          # no-op
        self._bank = self._bank.replace(destination, new_prog)
        self._working = None
        self._dirty = self._session_modified()
        return self.get_patch(destination)

    def rename_patch(self, index: int, name: str) -> PatchState:
        """Rename a slot without selecting it. Changes ONLY name bytes
        0x37..0x3F / offsets 55..63 (domain-level guarantee; byte 54 is
        structural and never written). Uses the existing Bank.set_name
        (same helper as PatchLibrary), so the 9-byte field semantics
        (truncate >9, space padding) are identical everywhere.

        No-op contract (P1.15): if the effective 9-byte name is already the
        requested one, nothing changes and no session mutation occurs."""
        self._require_loaded()
        if self._bank.get(index).name == name[:9]:
            return self.get_patch(index)
        self._bank = self._bank.set_name(index, name)
        # P1.15 corrective fix: if the renamed slot is the one currently
        # held as an uncommitted working copy, fold the rename into that
        # copy — otherwise a pending parameter edit would silently shadow
        # (and eventually discard) the new name.  Dirty stays MODIFIED:
        # the session state really did change (rename succeeded).
        if self._working is not None and self._working.index == index:
            self._working = self.current_patch().set_name(name)
        self._dirty = self._session_modified()
        return self.get_patch(index)

    def reset_patch_parameter(self, index: int, key: str) -> bool:
        """Reset one slot's parameter to its documented registry default —
        without changing the selection and WITHOUT touching the uncommitted
        working copy of another slot.

        Same history/dirty semantics as rename_patch(): immediate domain
        mutation through the existing model helpers; the session becomes
        MODIFIED only if the bank really differs from the baseline. The GUI
        never writes raw bytes itself; this exists so a per-parameter
        'reset to default' button is a single public-API call.

        Returns True when the byte value actually changed, False when the
        parameter was already at its default (no-op contract)."""
        self._require_loaded()
        spec = BY_KEY[key]                      # raises UnknownParameterError
        # Editability/writability come from the EDITOR-layer definition
        # (registry metadata + writable_parameters()), NOT from a nonexistent
        # ParameterSpec attribute — see ParameterDefinition.editable/.writable.
        d = definition_for(key)
        if not d.editable or d.offset is None or not d.writable:
            raise ParameterNotEditableError(
                f"{key} is not editable through the editor API")
        prog = self._bank.get(index)            # raises on bad index
        if prog.get_parameter(key) == spec.default:
            return False                        # already default → no-op
        new_prog = prog.set_parameter(key, spec.default)
        self._bank = self._bank.replace(index, new_prog)
        self._dirty = self._session_modified()
        return True

    def registry_status(self) -> dict:
        """Report-only registry audit (P1.8 validate_registry). NEVER
        mutates the registry; contradictions stay observations."""
        return {"problems": validate_registry(),
                "parameters": len(BY_KEY),
                "hardware_confirmed": 0}

    def _require_loaded(self) -> None:
        if self._bank is None:
            raise SessionFormatError("No bank loaded.")

    # ---- merge (fixed 32-slot semantics; NO silent truncation) -----------
    MERGE_MODES = ("replace", "skip", "error")

    def merge(self, other, mode: str = "skip", slots=None) -> dict:
        """Merge patches from another bank into THIS bank.

        EMPTY-SLOT POLICY (architectural rule): this model has NO proven
        empty-slot state — every one of the 32 slots is an occupied, valid
        JTProgram, and the name "EMPTY" does NOT mean "empty". Conflict
        modes therefore work on OCCUPIED-SLOT semantics:

          mode='replace' — overwrite destination slots unconditionally;
          mode='skip'    — never overwrite an occupied destination slot.
              A source record that is byte-identical to the neutral slot
              template (literal padded name b"EMPTY    " AND all-zero data
              — a pure byte-equality fact, e.g. Synthmania filler records)
              carries no information and may fill a destination slot; it is
              NOT treated as a conflict. Since ALL banks always have their
              32 slots occupied, skip can legitimately report 0 merged —
              that is the expected outcome, not an error.
          mode='error'   — report a conflict instead of overwriting any
              occupied destination slot (same neutral-template exemption).

        Source patches are taken in slot order (source slot 1..32). The
        optional `slots` list maps them to destination slots
        (len(slots) == len(source programs)); by default destinations match
        source indices — the classic same-slot bank merge.
        Returns {'merged': [...], 'skipped': [...], 'errors': [...]}.
        Accepts EditorModel / PatchLibrary / Bank. Fixed 32-slot semantics:
        no silent truncation ever.
        """
        if mode not in self.MERGE_MODES:
            raise ValueError(f"Unknown merge mode: {mode!r}")
        self._require_loaded()
        src_bank = getattr(other, "bank", other)
        src_progs = list(src_bank.programs)
        if slots is None:
            pairs = list(zip(range(1, len(src_progs) + 1), src_progs))
        else:
            if len(slots) != len(src_progs):
                raise BankFullError(
                    f"merge slots mapping must cover all {len(src_progs)} "
                    f"source programs; got {len(slots)}.")
            pairs = list(zip(slots, src_progs))
        merged, skipped, errors = [], [], []
        bank = self._bank
        for dst, sp in pairs:
            if not 1 <= dst <= 32:
                raise PatchIndexError("Merge slot outside 1..32.")
            neutral_src = _slot_is_source_template(sp)
            if mode == "error" and not neutral_src:
                errors.append(dst)
                continue
            if mode == "skip" and not neutral_src:
                skipped.append(dst)
                continue
            bank = bank.replace(dst, JTProgram(dst, bytes(sp.data)))
            merged.append(dst)
        if len(merged) + len(skipped) + len(errors) != len(pairs):
            raise BankFullError("Merge would exceed the 32-slot bank.")
        if merged:
            self._bank = bank
            self._working = None
            self._dirty = True
        return {"merged": merged, "skipped": skipped, "errors": errors}

    # ---- snapshot / restore (minimal; NO undo framework here) ------------
    def snapshot(self) -> "BankSnapshot":
        return BankSnapshot(self._bank, self._selected, self._path,
                            self._provenance, working=self._working,
                            was_clean=not self._dirty)

    def restore(self, snap: "BankSnapshot", *, recompute_dirty: bool = True) -> None:
        """Restore a snapshot. Provenance comes back exactly as stored —
        restoring NEVER promotes REFERENCE_FIXTURE.

        P1.23 fix: ``recompute_dirty=False`` keeps the CURRENT dirty flag.
        EditorHistory.undo()/redo() need this because their own undo/redo
        stacks contain no baseline reference: once the user saves (or loads)
        mid-history, an older snapshot may differ from the NEW baseline, and
        blindly marking dirty would report MODIFIED for a state that equals
        the saved file.  Recomputing here instead would require exposing
        private baseline state to the history wrapper, which violates the
        P1.11 boundary.  The load/save entry points below keep the default
        (conservative) behaviour.
        """
        self._bank = snap.bank
        self._selected = snap.selected
        self._path = snap.path
        self._provenance = snap.provenance
        self._working = snap.working
        if recompute_dirty:
            self._dirty = True

    # ---- editing ---------------------------------------------------------
    def current_patch(self) -> PatchState:
        """The patch as currently edited (working copy if present)."""
        if self._working is not None and self._working.index == self._selected:
            return self._working
        return PatchState.from_program(self.bank.get(self._selected),
                                       provenance=self._provenance,
                                       source_path=self._path)

    def edit_parameter(self, key: str, value: int) -> PatchState:
        new = self.current_patch().set_parameter(key, value)
        # P1.15/P1.12 no-op contract: setting the SAME value must not create
        # a working copy and must not flip dirty (validation above still
        # raises for unknown/out-of-range values).
        if bytes(new.data) == bytes(self.current_patch().data):
            return new
        # main's unconditional assignment is kept, but dirty is RECOMPUTED
        # via _session_modified() (P1.10 baseline semantics) instead of a
        # hard `True`, so the two branches stay consistent with commit()/
        # revert()/undo()/redo().
        self._working = new
        self._dirty = self._session_modified()
        return new

    def edit_parameters(self, updates: Mapping[str, int]) -> PatchState:
        new = self.current_patch().set_parameters(updates)
        if bytes(new.data) == bytes(self.current_patch().data):
            return new
        self._working = new
        self._dirty = self._session_modified()
        return new

    def edit_name(self, name: str) -> PatchState:
        new = self.current_patch().set_name(name)
        # Same effective 9-byte name → no session mutation, no dirty flip.
        if bytes(new.data) == bytes(self.current_patch().data):
            return new
        self._working = new
        self._dirty = self._session_modified()
        return new
        self._working = self.current_patch().set_parameter(key, value)
        self._dirty = self._session_modified()
        return self._working

    def edit_parameters(self, updates: Mapping[str, int]) -> PatchState:
        self._working = self.current_patch().set_parameters(updates)
        self._dirty = self._session_modified()
        return self._working

    def edit_name(self, name: str) -> PatchState:
        self._working = self.current_patch().set_name(name)
        self._dirty = self._session_modified()
        return self._working

    def commit(self) -> Bank:
        """Write the working patch back into the bank (still in memory)."""
        if self._working is None:
            return self.bank
        self._bank = self.bank.replace(self._selected, self._working.program)
        self._working = None
        self._dirty = self._session_modified()
        return self._bank

    def revert(self) -> None:
        self._working = None
        self._dirty = self._session_modified()

    def _bank_modified(self) -> bool:
        """Dirty iff current serialized bank differs from the load/save
        baseline.  Uses the in-memory baseline captured at the last
        successful load or save — NOT a disk re-read — so undo-ing back to
        the exact loaded state returns CLEAN even if the file on disk was
        changed meanwhile."""
        if self._bank is None:
            return False
        if self._baseline is None:
            return True
        return self._bank.to_sysex() != self._baseline

    def _session_modified(self) -> bool:
        """Full dirty semantics (P1.10 §6): the session is MODIFIED when the
        committed bank OR the uncommitted working patch copy differs from the
        load/save baseline.  The working copy lives outside `Bank`, so a bare
        `_bank_modified()` check would wrongly report CLEAN while an edited
        patch is pending commit — exactly the state a GUI must show as
        MODIFIED and must not silently discard."""
        if self._working is not None:
            try:
                base = self.bank.get(self._selected)
            except Exception:
                return True
            if bytes(self._working.data) != bytes(base.data):
                return True
        return self._bank_modified()

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
        payload = self.bank.save(target)   # raises on failure; dirty stays True
        self._path = target.resolve()
        self._baseline = bytes(payload)    # serializer output == file bytes
        self._dirty = False
        return target

    # ---- helpers ---------------------------------------------------------
    def patch_states(self) -> list[PatchState]:
        return [PatchState.from_program(p, provenance=self._provenance,
                                        source_path=self._path)
                for p in self.bank.programs]

    # ---- session persistence (P1.9 §18/§19) ------------------------------
    SESSION_SCHEMA = "jt4000m.editor_session/v1"

    def to_session_dict(self) -> dict:
        """Editor-session state ONLY. Raw program bytes are NOT duplicated
        here — the .syx file stays the authoritative storage representation;
        the session merely says which file/slot is open and what uncommitted
        working-copy edits exist."""
        d = {
            "schema_version": 1,
            "schema": self.SESSION_SCHEMA,
            "source": str(self._path) if self._path else None,
            "provenance": self._provenance,
            "selected_patch": self._selected,
            "dirty": self._dirty,
            "edits": [],
        }
        if self._working is not None:
            base = self.bank.get(self._selected)
            diff = PatchState.from_program(base).diff_to(self._working)
            name_changed = (self._working.name_bytes()
                            != bytes(base.data[NAME_START:]))
            d["edits"].append({
                "patch": self._selected,
                "name": self._working.name if name_changed else None,
                "parameters": [{"offset": c["offset"], "old": c["old"],
                                "new": c["new"]} for c in diff],
            })
        return d

    def save_session(self, path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_session_dict(), ensure_ascii=False,
                                indent=2), encoding="utf-8")
        return p

    @classmethod
    def load_session(cls, path) -> "EditorModel":
        """Recover SYX -> edit -> session-save -> close -> reopen state.

        The source SYX remains authoritative; only selection + pending
        working-copy edits are replayed. Provenance is restored exactly as
        stored (never promoted)."""
        p = Path(path)
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except FileNotFoundError as e:
            raise SessionFormatError(f"Session file not found: {p}") from e
        except json.JSONDecodeError as e:
            raise SessionFormatError(f"Session JSON corrupt: {e}") from e
        if not isinstance(data, dict) or data.get("schema") != cls.SESSION_SCHEMA:
            raise SessionFormatError(
                f"Unsupported session schema: {data.get('schema')!r}")
        src = data.get("source")
        if not src:
            raise SessionFormatError("Session has no source SYX.")
        m = cls()
        try:
            m.load_bank(src)
        except Exception as e:
            raise SessionFormatError(f"Source SYX unreadable: {e}") from e
        # provenance is restored verbatim — NO re-detection, NO promotion.
        m._provenance = data.get("provenance", m._provenance)
        sel = data.get("selected_patch", 1)
        if not 1 <= sel <= 32:
            raise SessionFormatError("Session selected_patch out of range.")
        m.select(sel)
        for edit in data.get("edits", []):
            if edit.get("patch") != sel:
                continue      # pending edits belong to the selected slot only
            if edit.get("name"):
                m.edit_name(edit["name"])
            for ch in edit.get("parameters", []):
                keys = keys_for_offset(ch["offset"])
                if len(keys) == 1:
                    m.edit_parameter(keys[0], ch["new"])
        m._dirty = bool(data.get("dirty", True))
        return m


@dataclass(frozen=True)
class BankSnapshot:
    """Immutable restore point for an EditorModel session (bank + selection
    + path + provenance + uncommitted working patch). Deliberately minimal —
    PatchLibrary keeps owning undo/redo history; this exists for before/after
    workflows and as the substrate for a thin editor-level history wrapper.

    P1.23: ``was_clean`` records whether the session was CLEAN at capture
    time, so EditorHistory can recompute dirty semantics after a restore
    without touching EditorModel private state."""
    bank: Bank
    selected: int
    path: Path | None
    provenance: str
    working: "PatchState | None" = None
    was_clean: bool = False


# ---------------------------------------------------------------------------
# EditorHistory — thin wrapper over snapshot()/restore() (P1.10 §11)
# ---------------------------------------------------------------------------
class EditorHistory:
    """Undo/redo for an EditorModel WITHOUT a second state model.

    Every entry is a full immutable BankSnapshot (the domain model is
    copy-on-write, so snapshots share unchanged programs — cheap).  The GUI
    calls push() BEFORE any mutating operation and undo()/redo() on demand.
    No MIDI, no raw bytes, no knowledge of SYX format.
    """

    def __init__(self, model: "EditorModel", limit: int = 100) -> None:
        self._model = model
        self._limit = max(2, int(limit))
        self._undo: list[BankSnapshot] = []
        self._redo: list[BankSnapshot] = []

    def push(self) -> None:
        """Call immediately before a mutation; records current state.

        P1.15 no-op contract: pushing a snapshot identical to the one on top
        of the undo stack would create an undo step that changes nothing
        (and could flip dirty state spuriously).  Consecutive identical
        snapshots are therefore coalesced — the stack depth stays the same
        and the redo stack is left untouched.
        """
        snap = self._model.snapshot()
        if self._undo and self._snapshots_equal(self._undo[-1], snap):
            return
        self._undo.append(snap)
        if len(self._undo) > self._limit:
            self._undo.pop(0)
        self._redo.clear()

    @staticmethod
    def _snapshots_equal(a: "BankSnapshot", b: "BankSnapshot") -> bool:
        """Cheap structural equality WITHOUT any serialization side effects.

        The domain model is copy-on-write, so unchanged programs are shared
        objects; comparing the program tuples element-wise is enough (plus
        selection/working-copy identity checks)."""
        if a.selected != b.selected:
            return False
        aw, bw = a.working, b.working
        if (aw is None) != (bw is None):
            return False
        if aw is not None and bytes(aw.data) != bytes(bw.data):
            return False
        if len(a.bank.programs) != len(b.bank.programs):
            return False
        return all(pa.data == pb.data for pa, pb in
                   zip(a.bank.programs, b.bank.programs))

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> bool:
        if not self._undo:
            return False
        current = self._model.snapshot()
        was_dirty_before_undo = self._model.is_dirty()
        self._redo.append(current)
        # P1.23 fix: restore WITHOUT touching the dirty flag, then recompute
        # it via public API only (the old code wrote the private `_dirty`
        # attribute directly — a P1.11 boundary violation).
        target = self._undo.pop()
        self._model.restore(target, recompute_dirty=False)
        if self._snapshots_equal(target, current):
            # Coalesced no-op step: dirty semantics are unchanged.
            self._model.mark_dirty(was_dirty_before_undo)
        else:
            # Restoring into a state that was CLEAN when captured (i.e. the
            # snapshot itself equalled the load/save baseline at push time)
            # must report CLEAN; any other restore is a real session change.
            self._model.mark_dirty(not target.was_clean)
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        current = self._model.snapshot()
        was_dirty_before_redo = self._model.is_dirty()
        self._undo.append(current)
        target = self._redo.pop()
        self._model.restore(target, recompute_dirty=False)
        if self._snapshots_equal(target, current):
            self._model.mark_dirty(was_dirty_before_redo)
        else:
            self._model.mark_dirty(not target.was_clean)
        return True

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()

    # ---- P1.15 read-only inspection (projection support, no mutation) ----
    @property
    def depth_undo(self) -> int:
        """Current undo-stack depth (read-only; used by behavioral tests and
        the status projection — the GUI never manipulates stacks itself)."""
        return len(self._undo)

    @property
    def depth_redo(self) -> int:
        return len(self._redo)

    # ---- dirty semantics (P1.10 §6; single source of truth = model) ------
    def sync_dirty(self) -> bool:
        """Recompute the model's dirty flag from the load/save baseline.

        Call after mutations that were performed directly on the domain
        layer (e.g. EditorModel.bank.replace(...) via a GUI helper) so the
        GUI never needs its own dirty tracking.  Returns the new state."""
        self._model._dirty = self._model._session_modified()
        return self._model._dirty


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
