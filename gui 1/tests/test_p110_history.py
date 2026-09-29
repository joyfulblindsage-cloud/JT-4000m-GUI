"""P1.10 — EditorHistory / BankSnapshot regression suite (offline, no MIDI).

Covers the history contract the GUI relies on:
  * undo/redo round-trips for parameter edits, renames and bank ops;
  * snapshot restores the uncommitted working copy (BankSnapshot.working);
  * selection survives undo;
  * a new mutation after undo invalidates redo (documented semantics);
  * dirty flag is derived from the load/save baseline (undo-to-loaded = CLEAN);
  * failed save keeps MODIFIED; successful save -> CLEAN;
  * provenance is never promoted by restore/history.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from jt4000m.editor_model import EditorHistory, EditorModel

ROOT = Path(__file__).resolve().parent.parent
ALL_EMPTY = str(ROOT / "ALL EMPTY.syx")
ALL_SAW = str(ROOT / "ALL INIT SAW.syx")


def model(path):
    m = EditorModel()
    m.load_bank(path)
    return m


class TestEditUndoRedo:
    def test_parameter_edit_undo_redo(self):
        m = model(ALL_SAW)
        h = EditorHistory(m)
        m.select(1)
        before = m.get_parameter("osc1_wave").raw
        assert before == 4                      # INIT SAW
        h.push()
        m.set_parameter("osc1_wave", 0)
        m.commit()
        assert m.get_parameter("osc1_wave").raw == 0
        assert m.is_dirty()
        assert h.undo()
        assert m.get_parameter("osc1_wave").raw == before
        assert not m.is_dirty()                 # exact loaded state -> CLEAN
        assert h.redo()
        assert m.get_parameter("osc1_wave").raw == 0
        assert m.is_dirty()

    def test_selection_survives_undo(self):
        m = model(ALL_SAW)
        h = EditorHistory(m)
        m.select(7)
        h.push()
        m.rename("UNDO TEST")
        m.commit()
        # NOTE (documented semantics): select()/get_patch() intentionally
        # DISCARD an uncommitted working copy, so "undo" must be tested on
        # committed state only.  Move selection away and back:
        m.select(3)
        assert m.current_patch().name == "INIT SAW"      # edit was per-slot
        h.undo()
        assert m.selected == 7                  # snapshot carried selection
        assert m.current_patch().name != "UNDO TEST"

    def test_uncommitted_working_copy_survives_history_roundtrip(self):
        """BankSnapshot.working is what carries *uncommitted* edits."""
        m = model(ALL_SAW)
        h = EditorHistory(m)
        m.select(5)
        h.push()                                # snapshot: no working copy
        m.set_parameter("osc1_wave", 0)         # UNCOMMITTED working edit
        assert m.current_patch().get_raw("osc1_wave") == 0
        h.undo()                                # back to push-time snapshot
        assert m.selected == 5
        assert m.current_patch().get_raw("osc1_wave") == 4   # edit undone
        assert not m.is_dirty()                 # exact baseline -> CLEAN
        h.redo()
        assert m.current_patch().get_raw("osc1_wave") == 0   # edit restored
        assert m.is_dirty()

    def test_new_mutation_after_undo_invalidates_redo(self):
        m = model(ALL_SAW)
        h = EditorHistory(m)
        h.push(); m.set_parameter("osc1_pwm_fm", 100); m.commit()
        h.push(); m.set_parameter("osc1_pwm_fm", 110); m.commit()
        h.undo()                                 # back to 100
        assert m.get_parameter("osc1_pwm_fm").raw == 100
        assert h.can_redo
        h.push(); m.rename("FRESH EDIT"); m.commit()
        assert not h.can_redo                    # documented: push clears redo

    def test_empty_history_returns_false(self):
        m = model(ALL_SAW)
        h = EditorHistory(m)
        assert not h.can_undo and not h.can_redo
        assert h.undo() is False and h.redo() is False


class TestRenameAndOps:
    def test_rename_undo_redo(self):
        m = model(ALL_SAW)
        h = EditorHistory(m)
        m.select(2)
        original = m.current_patch().name      # "INIT SAW" (all slots equal)
        h.push()
        m.rename("SLOT SEVEN")                 # 10 chars -> truncates to 9
        m.commit()
        assert m.current_patch().name == "SLOT SEVE"   # documented capacity
        h.undo()
        assert m.current_patch().name == original
        h.redo()
        assert m.current_patch().name == "SLOT SEVE"

    def test_duplicate_undo_restores_bank(self):
        m = model(ALL_SAW)
        h = EditorHistory(m)
        src = m.get_patch(1)
        dst_before = m.get_patch(5)
        h.push()
        m.duplicate_patch(1, 5)
        assert m.get_patch(5).data == src.data
        h.undo()
        assert m.get_patch(5).data == dst_before       # slot 5 restored

    def test_swap_and_move_undo(self):
        m = model(ALL_SAW)
        h = EditorHistory(m)
        d1, d2 = m.get_patch(1).data, m.get_patch(2).data
        h.push(); m.swap_patches(1, 2)
        assert m.get_patch(1).data == d2
        h.undo(); assert m.get_patch(1).data == d1
        h.push(); m.move_patch(1, 3)
        h.undo(); assert m.get_patch(1).data == d1


class TestWorkingCopySnapshot:
    def test_snapshot_carries_uncommitted_working_copy(self):
        m = model(ALL_SAW)
        m.select(4)
        m.set_parameter("osc1_wave", 1)          # NOT committed
        snap = m.snapshot()
        assert snap.working is not None
        assert snap.working.get_raw("osc1_wave") == 1
        # restore() puts the working copy back verbatim:
        m.rename("DIRTY NAME")                   # further working edit
        assert m.current_patch().name == "DIRTY NAM"   # 9-byte capacity
        m.restore(snap)
        assert m._working is not None
        assert m.current_patch().get_raw("osc1_wave") == 1
        # ...and the rename is gone (working copy from snapshot restored):
        assert m.current_patch().name != "DIRTY NAM"

    def test_restore_keeps_provenance_verbatim(self):
        m = model(ALL_EMPTY)
        assert m.provenance == "REFERENCE_FIXTURE"
        snap = m.snapshot()
        m.rename("X")
        m.restore(snap)
        assert m.provenance == "REFERENCE_FIXTURE"


class TestDirtySemantics:
    def test_load_clean_edit_modified_save_clean(self, tmp_path):
        out = tmp_path / "copy.syx"
        out.write_bytes(Path(ALL_SAW).read_bytes())
        m = model(out)
        assert not m.is_dirty()
        m.set_parameter("osc1_wave", 0)
        assert m.is_dirty()
        m.save()
        assert not m.is_dirty()
        m.rename("AFTER SAVE")
        assert m.is_dirty()

    def test_undo_back_to_loaded_state_is_clean(self):
        m = model(ALL_SAW)
        h = EditorHistory(m)
        h.push()
        m.set_parameter("filter_res", 9)
        m.commit()
        assert m.is_dirty()
        h.undo()
        assert not m.is_dirty()                  # exact baseline match

    def test_failed_save_keeps_dirty(self, tmp_path):
        m = model(ALL_SAW)
        m.set_parameter("osc1_wave", 0)
        bad_dir = tmp_path / "nope"               # nonexistent dir -> OSError
        with pytest.raises(Exception):
            m.save(bad_dir / "x.syx")
        assert m.is_dirty()                       # error did NOT clear dirty

    def test_sync_dirty_after_domain_mutation(self):
        m = model(ALL_SAW)
        h = EditorHistory(m)
        # simulate a GUI helper mutating the domain bank directly
        prog = m.bank.get(1)
        m._bank = m.bank.replace(1, prog)         # same bytes -> still clean
        assert h.sync_dirty() is False
        edited = m.bank.set_parameter(1, "osc1_wave", 0)
        m._bank = edited
        assert h.sync_dirty() is True


class TestHistoryLimit:
    def test_limit_evicts_oldest(self):
        m = model(ALL_SAW)
        h = EditorHistory(m, limit=3)
        for i in range(6):
            h.push()
            m.rename(f"P{i}")
            m.commit()
        steps = 0
        while h.undo():
            steps += 1
        assert steps <= 3                         # bounded history
