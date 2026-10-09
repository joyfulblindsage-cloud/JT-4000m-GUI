"""P1.29 — PRESETS Browser: behavioral tests (no pixel-perfect layout checks).

Proves the browser invariants WITHOUT real hardware:

  * list shows all 32 programs with slot number + name;
  * selection is ONE state: PRESETS click / global navigator / EditorModel /
    SYNTH widgets stay synchronized (no second selection variable);
  * selection is NOT an edit: clean -> select stays clean, no history entry;
  * same-slot selection is a no-op (P1.28 §3 preserved);
  * search filters the projection only — never model/dirty/history/MIDI TX;
  * Copy/Paste/Duplicate/Rename/Reset behave as edits: dirty + undoable;
  * P1.28 Program Change regression (TX on navigation, RX selection without
    echo) and P1.27 CC slice regression still pass through the browser path.

The module opts into the root-conftest deterministic MIDI pump neutralizer
(midi_pump_control = True) so no order-dependent flakiness is reintroduced.
"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

ALL_INIT_SAW = os.path.abspath(os.path.join(_ROOT, "fixtures", "ALL INIT SAW.syx"))


def _root_conftest():
    """Deterministically load the ROOT conftest (FakeMidiBackend), immune to
    tests/hardware/conftest.py shadowing it under full-suite collection."""
    import importlib.util
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "conftest.py"
    spec = importlib.util.spec_from_file_location("_jt4000m_root_conftest_p129", root)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_HAS_DISPLAY = True
try:
    import tkinter  # noqa: F401
except Exception:
    _HAS_DISPLAY = False

gui_test = pytest.mark.skipif(not _HAS_DISPLAY, reason="no display available")

# Deterministic pump policy from the P1.28 follow-up (see root conftest).
midi_pump_control = True


def _make_app(rx=None, connect=True):
    FakeMidiBackend = _root_conftest().FakeMidiBackend
    from jt4000m.gui import Editor
    from jt4000m.transport import MidiTransport

    backend = FakeMidiBackend(rx=list(rx or []))
    transport = MidiTransport(backend=backend, backend_name="rtmidi")
    app = Editor()
    app.load_path(ALL_INIT_SAW)
    app.select_program(1)
    if connect:
        out = next(p for p in backend.ports if p.direction == "output"
                   and "JT-4000M" in p.name)
        inp = next(p for p in backend.ports if p.direction == "input")
        assert app.connect_midi(transport, channel=1,
                                input_port=inp, output_port=out) is True
        app._midi_poll_after_id = None      # drive RX manually below
    return app, backend


def _undo_depth(app) -> int:
    return len(app._history._undo)


def _list_rows(app):
    return list(app.listbox.get(0, "end"))


# ------------------------------------------------------------------ 1. bank list
@gui_test
def test_list_shows_all_32_programs_with_slot_and_name():
    app, _ = _make_app(connect=False)
    try:
        rows = _list_rows(app)
        assert len(rows) == 32
        assert rows[0].startswith("01") and rows[31].startswith("32")
        # names come straight from the loaded bank (model projection, no copy)
        from jt4000m.patch import Bank
        bank = Bank.load(ALL_INIT_SAW)
        assert rows[4] == f"05  {bank.get(5).name}"
        assert app.count_label.cget("text") == "32/32"
    finally:
        app.destroy()


# ------------------------------------------------------- 2. selection one-state
@gui_test
def test_presets_click_selects_through_model_everywhere():
    app, _ = _make_app(connect=False)
    try:
        app.listbox.selection_clear(0, "end")
        app.listbox.selection_set(16)          # row index 16 == P17
        app._on_select()
        assert app.editor.selected == 17       # EditorModel = source of truth
        assert app.selected_index == 17        # GUI projection only
        assert app.nav_slot_var.get() == "P17" # global navigator synced
        assert app.slot_var.get().startswith("P17")
        # SYNTH widgets project the newly selected patch
        assert app.vars["filter_cutoff"].get() == \
            app.editor.get_patch(17).get_raw("filter_cutoff")
    finally:
        app.destroy()


@gui_test
def test_global_navigator_updates_presets_selection():
    app, _ = _make_app(connect=False)
    try:
        app.select_program(5)
        app._nav_step(1)                       # P05 -> P06 via ◀/▶ path
        assert app.editor.selected == 6
        sel = app.listbox.curselection()       # PRESETS highlights P06
        assert sel and _list_rows(app)[sel[0]].startswith("06")
    finally:
        app.destroy()


# ------------------------------------------------------------ 3. selection ≠ edit
@gui_test
def test_selection_keeps_clean_session_clean():
    app, _ = _make_app(connect=False)
    try:
        depth = _undo_depth(app)
        assert app.editor.is_dirty() is False
        for idx in (2, 3, 17, 32, 1):
            app.select_program(idx)
        assert app.editor.is_dirty() is False
        assert _undo_depth(app) == depth       # zero history entries
        assert app.modified_var.get() == ""
    finally:
        app.destroy()


@gui_test
def test_same_slot_selection_is_noop():
    app, backend = _make_app()
    try:
        app.select_program(9)
        tx_before = list(backend.tx_log)
        depth = _undo_depth(app)
        app.select_program(9)                  # already selected -> nothing
        assert backend.tx_log == tx_before     # no duplicate PC TX
        assert _undo_depth(app) == depth
        assert app.editor.is_dirty() is False
    finally:
        app.destroy()


# ------------------------------------------------------------------- 4. search
@gui_test
def test_search_filters_without_touching_model_or_dirty():
    app, backend = _make_app()                 # MIDI connected: proves no TX too
    try:
        app.select_program(7)
        depth = _undo_depth(app)
        tx_before = list(backend.tx_log)
        app.search_var.set("INIT")             # ALL INIT SAW bank: matches all
        app.refresh_list()
        assert len(_list_rows(app)) == 32
        app.search_var.set("zzz-no-match")
        app.refresh_list()
        assert _list_rows(app) == []
        assert app.editor.selected == 7        # selection untouched
        assert app.editor.is_dirty() is False
        assert _undo_depth(app) == depth
        assert backend.tx_log == tx_before     # no MIDI traffic from filtering
        app.search_var.set("")
        app.refresh_list()
        assert len(_list_rows(app)) == 32      # clearing restores full list
        assert app.count_label.cget("text") == "32/32"
    finally:
        app.destroy()


# ------------------------------------------------------------- 5. rename (edit)
@gui_test
def test_rename_updates_model_list_navigator_and_is_undoable():
    app, _ = _make_app(connect=False)
    try:
        app.select_program(3)
        depth = _undo_depth(app)
        app.name_var.set("FAT BASS")
        app.apply_name()
        assert app.editor.get_patch(3).name.strip() == "FAT BASS"
        assert any(r.startswith("03") and "FAT BASS" in r for r in _list_rows(app))
        assert app.nav_name_var.get() == "FAT BASS"   # global navigator synced
        assert app.editor.is_dirty() is True
        assert _undo_depth(app) == depth + 1          # participates in history
        app.undo()
        assert app.editor.get_patch(3).name != "FAT BASS"
        assert app.editor.is_dirty() is False
    finally:
        app.destroy()


# ----------------------------------------------------------- 6. copy / paste
@gui_test
def test_copy_paste_edits_target_and_stays_undoable():
    app, _ = _make_app(connect=False)
    try:
        # Make P05 visibly different from every other slot first (it is an
        # ALL-INIT bank: all programs are byte-identical), so Paste into P12
        # must actually change P12's bytes.
        app.select_program(5)
        cutoff = app.editor.get_patch(5).get_raw("filter_cutoff")
        app.vars["filter_cutoff"].set((cutoff + 20) % 128)
        app.apply_parameter("filter_cutoff")
        app.copy_program()
        assert str(app.paste_btn.cget("state")) == "normal"
        app.select_program(12)
        depth = _undo_depth(app)
        original_12 = app.editor.get_patch(12).program.data
        app.paste_program()
        assert app.editor.get_patch(12).program.data != original_12
        assert app.editor.get_patch(12).program.data == \
            app.editor.get_patch(5).program.data
        assert app.editor.is_dirty() is True
        assert _undo_depth(app) == depth + 1
        app.undo()
        assert app.editor.get_patch(12).program.data == original_12
    finally:
        app.destroy()


# --------------------------------------------------------------- 7. duplicate
@gui_test
def test_duplicate_copies_into_next_slot():
    app, _ = _make_app(connect=False)
    try:
        app.select_program(5)
        cutoff = app.editor.get_patch(5).get_raw("filter_cutoff")
        app.vars["filter_cutoff"].set((cutoff + 20) % 128)
        app.apply_parameter("filter_cutoff")     # P05 now differs from P06
        src = app.editor.get_patch(5).program.data
        target_before = app.editor.get_patch(6).program.data
        depth = _undo_depth(app)
        app.duplicate_program()                # P05 -> P06 (existing semantics)
        assert app.editor.get_patch(5).program.data == src      # source intact
        assert app.editor.get_patch(6).program.data == src      # target copied
        assert app.editor.get_patch(6).program.data != target_before
        assert app.editor.is_dirty() is True
        assert _undo_depth(app) == depth + 1
    finally:
        app.destroy()


# ------------------------------------------------------------------ 8. reset
@gui_test
def test_reset_restores_disk_version_of_selected_program(tmp_path):
    import shutil
    dst = tmp_path / "bank.syx"
    shutil.copy(ALL_INIT_SAW, dst)
    app, _ = _make_app(connect=False)
    try:
        # Dirty baseline: save the EDITED state to disk first, so the disk
        # version (cutoff=82) genuinely differs from the in-memory bank
        # snapshot (62).  Reset must restore the DISK version, not the old
        # session bytes.
        app.select_program(4)
        app.vars["filter_cutoff"].set((app.editor.get_patch(4).get_raw("filter_cutoff") + 20) % 128)
        app.apply_parameter("filter_cutoff")
        app._write(dst)                        # existing save path -> clean
        assert app.editor.is_dirty() is False
        # The GUI's in-memory bank mirror self.bank is refreshed by the
        # existing save path, so it now agrees with the disk (82).  Edit the
        # slot again in memory only (90), then Reset must restore exactly
        # what is on disk (82) — not the pre-edit session snapshot.
        from jt4000m.patch import Bank as _Bank
        disk_value = _Bank.load(str(dst)).get(4).get_parameter("filter_cutoff")   # 82
        app.vars["filter_cutoff"].set((disk_value + 8) % 128)                     # 90
        app.apply_parameter("filter_cutoff")
        edited = app.editor.get_patch(4).get_raw("filter_cutoff")
        saved_value = disk_value
        depth = _undo_depth(app)
        app.reset_program()                    # reads self.path == dst
        assert app.editor.get_patch(4).get_raw("filter_cutoff") == saved_value
        assert app.editor.get_patch(4).get_raw("filter_cutoff") != edited
        # Dirty semantics here are baseline-relative (P1.10): the save above
        # re-anchored the session baseline to the disk content (82), so
        # resetting back to the disk version returns the bank to the
        # baseline => CLEAN.  This is correct "save then reset == clean"
        # behavior; reset IS still a real mutation for history/Undo (§20).
        assert app.editor.is_dirty() is False
        assert _undo_depth(app) == depth + 1
        app.undo()                             # undo restores pre-reset state
        assert app.editor.get_patch(4).get_raw("filter_cutoff") == edited
        assert app.editor.is_dirty() is True   # 90 differs from baseline 82
    finally:
        app.destroy()


# ------------------------------------- 9. P1.28 regression through the browser
@gui_test
def test_presets_click_emits_program_change_tx():
    app, backend = _make_app()
    try:
        app.listbox.selection_clear(0, "end")
        app.listbox.selection_set(16)              # P17 row
        app._on_select()
        assert backend.tx_log == [bytes([0xC0, 16])]
        assert app.editor.selected == 17
    finally:
        app.destroy()


@gui_test
def test_program_change_rx_selects_in_presets_without_echo_or_edit():
    app, backend = _make_app(rx=[bytes([0xC0, 16])])
    try:
        app._poll_midi_once()
        assert app.editor.selected == 17
        assert app.selected_index == 17
        assert app.nav_slot_var.get() == "P17"
        sel = app.listbox.curselection()           # PRESETS highlight follows RX
        assert sel and _list_rows(app)[sel[0]].startswith("17")
        assert app.editor.is_dirty() is False      # RX selection is not an edit
        assert backend.tx_log == []                # no feedback echo
        ev = [e for e in app.midi_events if e.get("type") == "program_change"]
        assert ev[-1]["direction"] == "rx" and ev[-1]["slot"] == 17
    finally:
        app.destroy()


# -------------------------------------------- 10. P1.27 CC-slice regression
@gui_test
def test_cc_tx_and_rx_still_work_after_browser_changes():
    app, backend = _make_app(rx=[bytes([0xB0, 74, 42])])
    try:
        app.select_program(8)                      # browser selection first
        app.vars["filter_resonance"].set(64)
        app.apply_parameter("filter_resonance")
        assert bytes([0xB0, 71, 64]) in backend.tx_log
        app._poll_midi_once()                      # RX cutoff -> model + GUI
        assert app.editor.get_patch(8).get_raw("filter_cutoff") == 42
        assert app.vars["filter_cutoff"].get() == 42
    finally:
        app.destroy()


# ------------------------------------------------------ 11. offline navigation
@gui_test
def test_search_does_not_visually_select_a_different_program():
    app, _ = _make_app(connect=False)
    try:
        app.select_program(17)
        app.search_var.set("05")
        app.refresh_list()

        assert _list_rows(app) and _list_rows(app)[0].startswith("05")
        assert app.listbox.curselection() == ()
        assert app.editor.selected == 17
        assert app.nav_slot_var.get() == "P17"
        assert app.slot_var.get().startswith("P17")

        app.search_var.set("")
        app.refresh_list()
        selection = app.listbox.curselection()
        assert selection and _list_rows(app)[selection[0]].startswith("17")
    finally:
        app.destroy()


@gui_test
def test_identical_paste_and_duplicate_are_noops():
    app, _ = _make_app(connect=False)  # ALL INIT SAW: all slots are identical
    try:
        app.select_program(5)
        app.copy_program()
        app.select_program(6)

        depth = _undo_depth(app)
        assert app.editor.is_dirty() is False
        app.paste_program()
        assert _undo_depth(app) == depth
        assert app.editor.is_dirty() is False

        app.select_program(5)
        depth = _undo_depth(app)
        app.duplicate_program()  # target P06 already contains the same bytes
        assert _undo_depth(app) == depth
        assert app.editor.is_dirty() is False
    finally:
        app.destroy()


@gui_test
def test_reset_of_unchanged_program_is_noop():
    app, _ = _make_app(connect=False)
    try:
        app.select_program(12)
        depth = _undo_depth(app)
        assert app.editor.is_dirty() is False
        app.reset_program()
        assert _undo_depth(app) == depth
        assert app.editor.is_dirty() is False
    finally:
        app.destroy()


@gui_test
def test_duplicate_preserves_source_rename():
    app, _ = _make_app(connect=False)
    try:
        app.select_program(5)
        app.name_var.set("PENDING")
        app.apply_name()
        assert app.editor.get_patch_name(5).strip() == "PENDING"

        app.duplicate_program()
        assert app.editor.get_patch_name(6).strip() == "PENDING"
        assert app.editor.get_patch_name(5).strip() == "PENDING"
    finally:
        app.destroy()


@gui_test
def test_offline_presets_navigation_works_without_midi():
    app, _ = _make_app(connect=False)             # no MIDI at all
    try:
        assert app.midi_status_var.get() == "MIDI: offline"
        app.listbox.selection_clear(0, "end")
        app.listbox.selection_set(4)               # P05 row
        app._on_select()
        assert app.editor.selected == 5
        app._nav_step(-1)
        assert app.editor.selected == 4
        assert app.editor.is_dirty() is False      # no error, no dirty, usable
    finally:
        app.destroy()
