"""P1 — Patch Library abstraction over the existing immutable Bank model.

This module adds NO new patch/bank data model: it wraps jt4000m.patch.Bank /
JTProgram (copy-on-write) and jt4000m.syx (parser/exporter). It performs no
MIDI I/O of any kind; everything here works on local .syx files only.

Guarantees (regression-tested in tests/test_p1_library.py):
  * unknown bytes inside the 64-byte program records are never dropped;
  * editing one known parameter touches exactly one byte;
  * renaming a patch touches only Name[0..8] (offsets 55..63);
  * the checksum is recomputed only at export time (serialize_bulk/save);
  * the 32-program order is preserved by every operation;
  * bulk and single SysEx dumps keep being distinguished by the parser.
"""
from __future__ import annotations

from pathlib import Path

from .diff import bank_diff, format_change, program_diff
from .patch import Bank, JTProgram


class Snapshot:
    """An opaque, immutable restore point for a PatchLibrary."""

    __slots__ = ("_bank", "_path", "_selected")

    def __init__(self, bank: Bank, path: str | None, selected: int):
        self._bank = bank
        self._path = path
        self._selected = selected

    @property
    def bank(self) -> Bank:
        return self._bank


class PatchLibrary:
    """Mutable controller around an immutable 32-slot Bank.

    Responsibilities:
      * load_bank()/save_bank() — local .syx files only (no MIDI);
      * get/set/replace/duplicate/rename/swap/move — safe slot operations;
      * compare_programs()/compare_banks() — reuse of the existing diff code;
      * undo/redo history (rename, parameter edits, duplicate, swap, move,
        replace, paste);
      * dirty state: clean after load, modified after any change, clean again
        after a successful export;
      * snapshot()/restore() — full-state restore points (intended for later
        hardware experiments, but purely offline today).
    """

    HISTORY_LIMIT = 100

    def __init__(self, bank: Bank | None = None, *, path: str | None = None):
        self._bank: Bank = bank if bank is not None else Bank.empty()
        self._path: str | None = str(path) if path is not None else None
        self._selected: int = 1
        self._dirty: bool = False
        self._undo: list[tuple[Bank, int]] = []
        self._redo: list[tuple[Bank, int]] = []

    # ------------------------------------------------------------- access
    @property
    def bank(self) -> Bank:
        return self._bank

    @property
    def path(self) -> str | None:
        return self._path

    @property
    def selected(self) -> int:
        return self._selected

    @selected.setter
    def selected(self, index: int) -> None:
        if not 1 <= index <= 32:
            raise IndexError("Program index must be 1..32.")
        self._selected = index

    @property
    def dirty(self) -> bool:
        return self._dirty

    def programs(self) -> tuple[JTProgram, ...]:
        return self._bank.programs

    def get(self, index: int) -> JTProgram:
        """Return the patch at slot `index` (1..32)."""
        return self._bank.get(index)

    def names(self) -> list[str]:
        return [p.name for p in self._bank.programs]

    # --------------------------------------------------------- file I/O
    def load_bank(self, path: str) -> Bank:
        """Load a local .syx file as the current bank (bulk or single dump).

        Resets history and dirty state: the loaded content is 'clean'.
        """
        bank = Bank.load(path)  # single entry point; distinguishes bulk/single
        self._bank = bank
        self._path = str(path)
        self._selected = 1
        self._dirty = False
        self._undo.clear()
        self._redo.clear()
        return bank

    def save_bank(self, path: str | None = None) -> bytes:
        """Export the current bank to a .syx file; marks the library clean.

        Format/checksum handling lives entirely in Bank.save()/serialize_bulk:
        the original header frame is reused and the checksum is recomputed
        over the payload at export time only. On failure the dirty flag stays
        set (a failed export never pretends to be saved).
        """
        target = path if path is not None else self._path
        if target is None:
            raise ValueError("No path given and the library has no source file.")
        payload = self._bank.save(target)  # atomic write + re-parse guard
        self._path = str(target)
        self._dirty = False
        self._redo.clear()
        return payload

    # ------------------------------------------------- mutating commands
    def _push(self) -> None:
        self._undo.append((self._bank, self._selected))
        if len(self._undo) > self.HISTORY_LIMIT:
            del self._undo[0]
        self._redo.clear()
        self._dirty = True

    def _apply(self, bank: Bank) -> Bank:
        self._push()
        self._bank = bank
        return bank

    def select(self, index: int) -> None:
        """Select a slot without touching the bank (not an undoable edit)."""
        self.selected = index

    def set_parameter(self, index: int, key: str, value: int) -> Bank:
        """Edit one confirmed parameter of one patch (single-byte change)."""
        return self._apply(self._bank.set_parameter(index, key, value))

    def rename(self, index: int, name: str) -> Bank:
        """Rename a patch; only Name[0..8] bytes change."""
        return self._apply(self._bank.set_name(index, name))

    def replace(self, index: int, program: JTProgram) -> Bank:
        """Replace one slot with another patch record (raw bytes preserved)."""
        return self._apply(self._bank.replace(index, program))

    def duplicate(self, source: int, target: int) -> Bank:
        """Copy the raw record of `source` into slot `target` (overwrites)."""
        return self._apply(self._bank.copy_program(source, target))

    def swap(self, a: int, b: int) -> Bank:
        """Exchange two slots; both raw records survive byte-for-byte."""
        if a == b:
            return self._bank
        return self._apply(self._bank.swap(a, b))

    def move(self, source: int, target: int) -> Bank:
        """Move a slot, shifting intermediate slots; all raw records kept."""
        if source == target:
            return self._bank
        return self._apply(self._bank.move(source, target))

    # ------------------------------------------------------------ compare
    def compare_programs(self, a: int, b: int) -> list[str]:
        """Human-readable differences between two slots of the current bank.

        Delegates to diff.program_diff (the same ByteDiff/format_change logic
        the CLI uses) — no second comparison system exists.
        """
        ds = program_diff(self._bank.get(a), self._bank.get(b))
        return [f"{d.field}: {format_change(d)}" for d in ds]

    def compare_banks(self, other: "PatchLibrary | Bank") -> list[str]:
        """Differences between this bank and another bank/library."""
        ob = other.bank if isinstance(other, PatchLibrary) else other
        ds = bank_diff(self._bank, ob)
        return [f"P{d.program:02d} {d.field}: {format_change(d)}" for d in ds]

    # ------------------------------------------------------- undo / redo
    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append((self._bank, self._selected))
        self._bank, self._selected = self._undo.pop()
        self._dirty = True
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append((self._bank, self._selected))
        self._bank, self._selected = self._redo.pop()
        self._dirty = True
        return True

    # ------------------------------------------------- snapshot / restore
    def snapshot(self) -> Snapshot:
        """Full-state restore point (bank + path + selection)."""
        return Snapshot(self._bank, self._path, self._selected)

    def restore(self, snap: Snapshot) -> None:
        """Restore a snapshot. History is NOT rewound by design: restoring is
        itself an undoable edit so nothing gets silently lost."""
        self._push()
        self._bank = snap._bank
        self._path = snap._path
        self._selected = snap._selected
        self._dirty = True

    # --------------------------------------------------- convenience
    @classmethod
    def from_file(cls, path: str) -> "PatchLibrary":
        lib = cls()
        lib.load_bank(path)
        return lib
