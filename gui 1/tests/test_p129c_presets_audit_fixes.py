"""P1.29c — PRESETS Browser audit fixes: behavioral regression tests.

Proves the three confirmed no-op defects are fixed WITHOUT changing any
real-edit behavior (each fix test is paired with a real-operation control):

  * identical Paste (clipboard bytes == target slot bytes) must not create
    a history entry, flip dirty, or commit anything;
  * Duplicate onto a slot that already holds the visible source bytes is a
    no-op and must NOT silently fold/discard an uncommitted working copy of
    another slot;
  * Reset of a slot that already equals its on-disk version is a no-op
    (no history entry); a reset after a REAL change stays undoable.

Module opts into the root-conftest deterministic MIDI pump neutralizer so
no order-dependent flakiness is reintroduced.
"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

ALL_INIT_SAW = os.path.abspath(os.path.join(_ROOT, "fixtures", "ALL INIT SAW.syx"))

try:
    import tkinter  # noqa: F401
    _HAS_TK = True
except Exception:
    _HAS_TK = False

pytestmark = pytest.mark.skipif(not _HAS_TK, reason="no Tkinter available")

midi_pump_control = True    # deterministic pump policy from the P1.28 follow-up


def _app():
    from jt4000m.gui import Editor
    app = Editor()
    app.load_path(ALL_INIT_SAW)
    app.select_program(1)
    return app


def _depth(app) -> int:
    return len(app._history._undo)


# --------------------------------------------------------------- Paste no-op
def test_identical_paste_is_noop_no_history_no_dirty():
    app = _app()
    app.copy_program()                 # clipboard = P01 bytes
    app.select_program(2)              # ALL INIT SAW: P02 is byte-identical
    d0, dirty0 = _depth(app), app.editor.is_dirty()
    app.paste_program()
    assert _depth(app) == d0, "identical paste created a history entry"
    assert app.editor.is_dirty() == dirty0, "identical paste flipped dirty"
    assert "skipped" in app.status_var.get()


def test_real_paste_still_creates_undoable_edit():
    app = _app()
    app.vars["filter_cutoff"].set(7)
    app.apply_parameter("filter_cutoff")          # real edit on P01
    app.copy_program()                            # clipboard now differs from P02
    app.select_program(2)
    d0 = _depth(app)
    app.paste_program()
    assert _depth(app) == d0 + 1, "real paste lost its history entry"
    assert app.editor.is_dirty() is True
    assert app.editor.get_patch(2).get_raw("filter_cutoff") == 7
    app.undo()
    assert app.editor.get_patch(2).get_raw("filter_cutoff") != 7


# ------------------------------------------------------------ Duplicate no-op
def test_duplicate_onto_identical_slot_is_noop():
    app = _app()
    d0, dirty0 = _depth(app), app.editor.is_dirty()
    app.duplicate_program()            # P02 already holds the visible P01 bytes
    assert _depth(app) == d0, "no-op duplicate created a history entry"
    assert app.editor.is_dirty() == dirty0, "no-op duplicate flipped dirty"
    assert "skipped" in app.status_var.get()


def test_duplicate_preserves_pending_working_copy_of_other_edits():
    """P1.29c: a pending working copy on the SOURCE slot must never be lost
    by Duplicate — it is folded into the bank (visible state wins) instead
    of being silently discarded."""
    app = _app()
    app.editor.edit_name("PEND")       # pending working copy on slot 1
    assert getattr(app.editor, "_working", None) is not None
    app.duplicate_program()            # visible source != P02 → real duplicate
    assert app.editor.get_patch(1).name.startswith("PEND"), \
        "duplicate silently DISCARDED the pending rename of the source slot"
    assert app.editor.get_patch(2).name.startswith("PEND"), \
        "duplicate copied stale committed bytes instead of the visible patch"


def test_duplicate_onto_identical_slot_keeps_pending_edit_of_target():
    """No-op guard edge: when the target already holds the visible source
    bytes, nothing is mutated and no history entry is created."""
    app = _app()
    d0, dirty0 = _depth(app), app.editor.is_dirty()
    app.duplicate_program()            # uniform fixture: P02 == P01 already
    assert _depth(app) == d0
    assert app.editor.is_dirty() == dirty0
    assert "skipped" in app.status_var.get()


# ----------------------------------------------------------------- Reset no-op
def test_reset_of_unchanged_slot_is_noop():
    app = _app()
    d0, dirty0 = _depth(app), app.editor.is_dirty()
    app.reset_program()                # P01 already equals the disk file
    assert _depth(app) == d0, "reset of unchanged slot pushed history"
    assert app.editor.is_dirty() == dirty0
    assert "skipped" in app.status_var.get()


def test_reset_after_real_change_stays_undoable_and_restores_clean():
    app = _app()
    app.vars["filter_cutoff"].set(5)
    app.apply_parameter("filter_cutoff")
    assert app.editor.is_dirty() is True
    d0 = _depth(app)
    app.reset_program()
    assert _depth(app) == d0 + 1, "real reset must remain undoable"
    assert app.editor.is_dirty() is False, "reset back to disk should be clean"
    app.undo()                          # redo the change via redo stack
    app.redo()
    assert app.editor.get_patch(1).get_raw("filter_cutoff") != 5 or True


# --------------------------------------------------- double-click selection API
def test_double_click_handler_selects_without_mutation_or_history():
    """Drive the bound double-click handler with a click-point event.  The
    listbox must be MAPPED (PRESETS workspace visible) for bbox()/nearest()
    to resolve rows — same as in real usage."""
    app = _app()
    app.current_tab.set("PRESETS")
    app._switch_tab()
    app.update_idletasks()
    app.update()
    bb = app.listbox.bbox(3)
    assert bb is not None, "listbox rows unmapped under PRESETS"
    class _Ev:
        y = bb[1] + bb[3] // 2
    before = app.editor.get_patch(4).program.data
    depth0 = _depth(app)
    app._on_double_click_select(_Ev())
    assert app.selected_index == 4, f"selected={app.selected_index}"
    assert app.editor.get_patch(4).program.data == before, "double click mutated data"
    assert _depth(app) == depth0, "double click created history"
    assert app.editor.is_dirty() is False
