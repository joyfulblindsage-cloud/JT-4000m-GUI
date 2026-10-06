"""P1.28 — Global Preset Navigator + Program Change integration: behavioral tests.

Proves the two directions of the PC slice WITHOUT touching real hardware
(P1.5 safety rule — everything runs against the injected FakeMidiBackend):

    ◀/▶ / keyboard / list click -> select_program -> EditorModel.select_patch
        -> MidiSyncBridge.send_program_change -> (fake) PC byte on the wire

    (fake) PC RX -> _poll_midi_once -> MidiSyncBridge.decode_program_change
        -> EditorModel.select_patch -> GUI projection (navigator, SYNTH
        widgets, PRESETS listbox, RESEARCH views) — selection ONLY: never an
        edit, never dirty, never a history entry, never a TX echo.

The slot<->PC mapping itself is NOT re-tested here (already covered by
tests/test_p122_program_change.py); these tests only prove the GUI wiring
reuses the EXISTING bridge/mapping abstractions instead of duplicating them.
"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

FIXTURES = os.path.join(_ROOT, "fixtures")
ALL_INIT_SAW = os.path.abspath(os.path.join(FIXTURES, "ALL INIT SAW.syx"))


def _root_conftest():
    """Deterministically load the ROOT conftest (FakeMidiBackend), immune to
    tests/hardware/conftest.py shadowing it under full-suite collection."""
    import importlib.util
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "conftest.py"
    spec = importlib.util.spec_from_file_location("_jt4000m_root_conftest_p128", root)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_HAS_DISPLAY = True
try:
    import tkinter  # noqa: F401
except Exception:
    _HAS_DISPLAY = False

gui_test = pytest.mark.skipif(not _HAS_DISPLAY, reason="no display available")

# Opt into the root-conftest pump neutralizer (see conftest._deterministic_
# midi_pump) so rx_queue draining is always driven deterministically via
# _poll_midi_once(), never by a leftover after() callback from an earlier
# test's app.
midi_pump_control = True


def _make_app(rx=None, connect=True):
    """Editor with a loaded bank; optionally MIDI-connected over a fake backend.

    NOTE: ``connect_midi`` auto-discovers ports by NAME ("JT-4000M"); the fake
    backend's port objects are NOT comparable across two backend instances, so
    tests build their own FakeMidiBackend and pass its PortInfo objects
    explicitly — everything else (bridge, pump, status) is the production path.
    """
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
        # Disable the Tk timer pump: RX is driven deterministically below via
        # app._poll_midi_once(); otherwise event_generate/update would race it.
        app._midi_poll_after_id = None
    return app, backend


def _undo_depth(app) -> int:
    return len(app._history._undo)


# ------------------------------------------------------------------ 1. TX (§2)
@gui_test
@pytest.mark.parametrize("slot,program", [(1, 0), (17, 16), (32, 31)])
def test_user_navigation_emits_program_change_through_existing_bridge(slot, program):
    """◀/▶ path -> select_program -> EditorModel -> bridge -> PC byte.

    The GUI never builds MIDI bytes itself: encoding lives in midi.py and the
    exact wire byte proves the existing slot->PC mapping was reused (§12).
    """
    app, backend = _make_app()
    try:
        assert app.midi_status_var.get().startswith("MIDI: online")
        if slot != 1:                      # §3: selecting P01 while on P01 is a no-op
            app.select_program(slot)
        else:
            app.select_program(2)
            backend.tx_log.clear()
            app.select_program(1)
        assert backend.tx_log == [bytes([0xC0, program])]
        assert app.editor.selected == slot
        assert app.selected_index == slot
        ev = [e for e in app.midi_events if e.get("type") == "program_change"]
        assert ev[-1] == {"direction": "tx", "type": "program_change",
                          "channel": 1, "slot": slot, "api_ok": True}
    finally:
        app.destroy()


@gui_test
def test_reselecting_current_slot_is_a_silent_noop():
    """§3: P17 -> P17 creates no history entry, no dirty flip, no PC TX."""
    app, backend = _make_app()
    try:
        app.select_program(17)
        backend.tx_log.clear()
        depth_before = _undo_depth(app)
        dirty_before = app.editor.is_dirty()

        app.select_program(17)           # same slot again
        assert backend.tx_log == []      # no redundant Program Change
        assert _undo_depth(app) == depth_before
        assert app.editor.is_dirty() == dirty_before
        assert app.selected_index == 17
    finally:
        app.destroy()


# ------------------------------------------------------------------ 2. RX (§4)
@gui_test
@pytest.mark.parametrize("program,slot", [(0, 1), (16, 17), (31, 32)])
def test_incoming_program_change_selects_slot_without_edit_or_echo(program, slot):
    """PC RX -> decode_program_change -> EditorModel.select_patch -> projection.

    §5 invariants: patch bytes untouched, no Undo entry, session stays clean,
    nothing saved, nothing sent back (§6: zero TX echo).
    """
    app, backend = _make_app(rx=[bytes([0xC0, program])])
    try:
        undo_depth = _undo_depth(app)

        app._poll_midi_once()

        assert app.editor.selected == slot
        assert app.selected_index == slot
        # Projection across ALL tabs from the single model (§15):
        assert app.nav_slot_var.get() == f"P{slot:02d}"
        assert app.slot_var.get() == f"P{slot:02d}"
        # PRESETS list selection highlights the RX-selected slot (the widget's
        # own selection_set semantics are exercised by the existing P1.10 GUI
        # tests; here we only prove the target row IS part of the selection).
        assert (slot - 1) in app.listbox.curselection()
        assert app.name_var.get() == app.editor.get_patch(slot).name
        # Selection is NOT an edit (§5): bytes untouched, session stays clean,
        # no Undo entry was created.
        assert app.editor.is_dirty() is False
        assert _undo_depth(app) == undo_depth
        # No feedback loop (§6): RX produced ZERO outgoing traffic.
        assert backend.tx_log == []
        rx_ev = [e for e in app.midi_events if e.get("type") == "program_change"]
        assert rx_ev == [{"direction": "rx", "type": "program_change",
                          "channel": 1, "program": program, "slot": slot}]
    finally:
        app.destroy()


@gui_test
def test_out_of_range_and_wrong_channel_pc_are_ignored():
    """PC 32..127 and other channels keep flowing into the old ignore path:
    selection unchanged, still no TX, logged nowhere as a selection event."""
    app, backend = _make_app(rx=[bytes([0xC1, 4]),       # wrong channel
                                 bytes([0xC0, 32]),      # out of range
                                 bytes([0xF8])])         # clock: non-PC traffic
    try:
        app._poll_midi_once()
        assert app.editor.selected == 1
        assert app.selected_index == 1
        assert backend.tx_log == []
        assert not [e for e in app.midi_events
                    if e.get("type") == "program_change"]
    finally:
        app.destroy()


@gui_test
def test_rx_pc_on_already_selected_slot_is_noop():
    """§3/§6 RX half: PC naming the current slot changes nothing at all."""
    app, backend = _make_app(rx=[bytes([0xC0, 0])])   # P01 while P01 selected
    try:
        depth = _undo_depth(app)
        app._poll_midi_once()
        assert app.editor.selected == 1
        assert _undo_depth(app) == depth
        assert app.editor.is_dirty() is False
        assert backend.tx_log == []
    finally:
        app.destroy()


# ------------------------------------------------------- 3. Keyboard nav (§7/§8)
@gui_test
def test_global_arrow_keys_navigate_from_any_tab_via_same_path():
    """Left/Right on the toplevel drive _nav_step -> select_program -> PC TX."""
    app, backend = _make_app()
    try:
        app.update_idletasks()
        app.focus_force()
        app.update()
        app.event_generate("<Right>")
        app.update()
        assert app.selected_index == 2
        assert app.editor.selected == 2
        assert backend.tx_log == [bytes([0xC0, 1])]
        app.event_generate("<Left>")
        app.update()
        assert app.selected_index == 1
        assert len(backend.tx_log) == 2               # back to P01 -> PC0
    finally:
        app.destroy()


@gui_test
def test_arrows_keep_native_behavior_in_entry_and_listbox():
    """§8 safety: text/list controls must not lose their own arrow handling."""
    app, backend = _make_app()
    try:
        # Search entry: caret movement stays native; no navigation, no TX.
        def _find_class(w, classes):
            if w.winfo_class() in classes:
                return w
            for c in w.winfo_children():
                found = _find_class(c, classes)
                if found is not None:
                    return found
            return None

        entry = _find_class(app, ("Entry", "TEntry"))
        assert entry is not None
        entry.delete(0, "end")
        entry.insert(0, "abcx")
        entry.focus_set()
        entry.icursor("end")
        app.update()
        # (a) the global handler only listens to Left/Right: plain typing is
        # never intercepted.  Tk's event_generate cannot synthesize the char
        # payload for Entry insertion, so we assert the behavioral contract
        # directly: a non-arrow KeyPress falls through the handler untouched.
        class _Ev:  # minimal stand-in for a tkinter Event (no char needed)
            keysym = "y"
            widget = entry
        if app._on_global_arrow_nav(_Ev()) is not None:
            raise AssertionError("global nav handler must return None for non-arrow keys")
        assert entry.get() == "abcx"                      # text unchanged by handler
        assert app.selected_index == 1                    # navigator did NOT move
        assert backend.tx_log == []                       # no stray PC TX
        # (b) Left/Right are neutral for the navigator while an Entry has
        # focus: our toplevel handler skips editing/listing classes, so no
        # navigation and no PC TX happen.  NOTE: in headless Tk event_generate
        # does not deliver real keyboard focus (focus_get stays on the
        # toplevel), so instead of a synthetic arrow we invoke the exact
        # handler with a focused-Entry event stand-in — the §8 guard itself.
        class _ArrowAtEntry:
            keysym = "Left"
            widget = entry
        assert app._on_global_arrow_nav(_ArrowAtEntry()) is None  # skip, no nav
        assert app.selected_index == 1                    # navigator did NOT move
        assert backend.tx_log == []                       # no stray PC TX
        assert entry.get() == "abcx"                      # text untouched

        # Listbox: Left/Right are neutral there — the global handler skips the
        # Listbox class (§8), so no double-step and no echo.  (Up/Down native
        # cursor movement cannot be verified via event_generate in headless Tk,
        # which does not deliver real keyboard focus; the <ListboxSelect> path
        # is already covered by other tests.)
        backend.tx_log.clear()

        class _ArrowAtListbox:
            keysym = "Right"
            widget = app.listbox
        assert app._on_global_arrow_nav(_ArrowAtListbox()) is None  # §8 skip
        assert app.selected_index == 1                    # unchanged: neutral key
        assert backend.tx_log == []
    finally:
        app.destroy()


# ------------------------------------------------------------ 4. Offline (§9)
@gui_test
def test_navigator_works_fully_with_midi_disconnected():
    """No MIDI at all: ◀/▶ and keyboard still switch presets, TX silently absent,
    no error surfaces anywhere."""
    app, backend = _make_app(connect=False)
    try:
        assert app.midi_status_var.get() == "MIDI: offline"
        app.select_program(5)
        assert app.selected_index == 5 and app.editor.selected == 5
        assert app.nav_slot_var.get() == "P05"
        assert backend.tx_log == []
        assert app.midi_events == []                  # silent, no tx-error spam
        app._nav_step(-1)
        assert app.selected_index == 4
        app.destroy()
    except Exception:
        app.destroy()
        raise


# ----------------------------------------------------- 5. Dirty/history (§16)
@gui_test
def test_program_change_is_never_an_edit_full_invariant_walkthrough():
    """load -> clean; nav -> clean; keyboard-style nav -> clean; RX PC -> clean;
    parameter edit -> dirty; Undo -> clean.  PC never becomes an edit."""
    app, backend = _make_app(rx=[bytes([0xC0, 9])])   # PC9 -> P10 pending RX
    try:
        assert app.editor.is_dirty() is False                 # after load
        app.select_program(3)                                 # ◀/▶ style nav
        assert app.editor.is_dirty() is False
        app._nav_step(1)                                      # button step
        assert app.editor.is_dirty() is False
        app.vars["filter_cutoff"].set(77)                     # synthetic edit
        app.apply_parameter("filter_cutoff")
        assert app.editor.is_dirty() is True                  # edit -> dirty
        app.undo()                                            # clean again
        assert app.editor.is_dirty() is False
        app._poll_midi_once()                                 # RX PC -> P10
        assert app.editor.selected == 10
        assert app.editor.is_dirty() is False                 # selection ≠ edit
    finally:
        app.destroy()


# --------------------------------------------- 6. CC path regression (P1.27)
@gui_test
def test_cc_slice_still_flows_after_pc_branch_added():
    """The PC decoder branch in the pump must not swallow CC traffic:
    one RX CC still projects into the model/widgets, echo-free."""
    app, backend = _make_app(rx=[bytes([0xB0, 74, 42])])
    try:
        app._poll_midi_once()
        assert app.editor.get_patch(1).get_raw("filter_cutoff") == 42
        assert app.vars["filter_cutoff"].get() == 42
        assert backend.tx_log == []                           # no CC echo
    finally:
        app.destroy()
