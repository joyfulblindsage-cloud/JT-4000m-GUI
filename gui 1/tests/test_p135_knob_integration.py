"""P1.35 — custom rotary Knob integration tests (OSC Balance).

Contract proven here (automated only — NO physical JT-4000M involved):

    Knob gesture -> shared IntVar -> _scale_changed drag session
        -> EditorModel.set_slot_parameter (single validated mutation path)
        -> MidiSyncBridge TX (CC comes from the registry, GUI never knows it)
        -> one undo snapshot per continuous gesture
        -> model projection (_sync_widgets_from_model) pushes the value back
           into the knob via set_value() without any callback echo.

Everything runs against the injected FakeMidiBackend from the root conftest
(P1.5 safety rule: automated tests NEVER touch real MIDI hardware).
"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

tk = pytest.importorskip("tkinter")

try:
    _probe = tk.Tk()
    _probe.destroy()
    _HAS_DISPLAY = True
except tk.TclError:
    _HAS_DISPLAY = False

gui_test = pytest.mark.skipif(not _HAS_DISPLAY, reason="no display available")

from jt4000m.model import BY_KEY                                   # noqa: E402

FIXTURES = os.path.join(_ROOT, "fixtures")
ALL_INIT_SAW = os.path.abspath(os.path.join(FIXTURES, "ALL INIT SAW.syx"))


@pytest.fixture()
def app():
    from jt4000m.gui import Editor
    a = Editor()
    yield a
    a.destroy()


@pytest.fixture()
def loaded(app):
    """Bank loaded + program selected, exactly like the normal user flow."""
    app.load_path(ALL_INIT_SAW)
    app.select_program(1)
    return app


# ----------------------------------------------------------- 1. wiring shape
@gui_test
def test_osc_balance_is_a_knob_on_the_existing_registry_path(loaded):
    """The knob replaced ONLY the visual control; vars/registry untouched."""
    from jt4000m.widgets import Knob

    assert "osc_balance" in loaded._knobs
    knob = loaded._knobs["osc_balance"]
    assert isinstance(knob, Knob)
    # Range/scale come straight from the registry — no invented limits.
    spec = BY_KEY["osc_balance"]
    assert (knob.minimum, knob.maximum, knob.default_raw) == \
        (spec.minimum, spec.maximum, spec.default)
    # Shared model-projection variables still exist for this key.
    assert "osc_balance" in loaded.vars and "osc_balance" in loaded.value_vars
    # osc_balance is NOT among the tk.Scale widgets anymore (only this row);
    # every other continuous parameter keeps its Scale.
    assert knob not in getattr(loaded, "_parameter_scales", [])
    # The knob widget was actually realized inside the MIX/RING box.
    assert knob.winfo_ismapped() or knob.winfo_exists()


# --------------------------------------------- 2. gesture -> model + one undo
@gui_test
def test_knob_drag_mutates_model_with_one_undo_snapshot(loaded):
    before = loaded.editor.get_patch(1).get_raw("osc_balance")
    undo_depth = len(loaded._history._undo)

    # Simulate one continuous mouse gesture: press, several drags, release.
    knob = loaded._knobs["osc_balance"]
    _drag_gesture(knob, steps=5)                    # five incremental moves

    after = loaded.editor.get_patch(1).get_raw("osc_balance")
    assert after != before                          # parameter really changed
    assert 0 <= after <= 127                        # range preserved
    # ONE gesture => at most ONE new undo snapshot (existing architecture).
    assert len(loaded._history._undo) == undo_depth + 1
    # GUI projection matches the model after the gesture closed.
    assert int(loaded.vars["osc_balance"].get()) == after
    assert knob.current_norm == pytest.approx(after / 127.0, abs=0.02)


# ------------------------------------------------------- 3. MIDI TX via bridge
@gui_test
def test_knob_gesture_transmits_cc_through_existing_bridge(loaded,
                                                           fake_transport,
                                                           fake_backend):
    """TX reuses MidiSyncBridge; CC number comes from the registry (29)."""
    loaded.connect_midi(fake_transport, channel=1)
    fake_backend.tx_log.clear()

    cc = BY_KEY["osc_balance"].cc
    assert cc == 29                                  # mapping NOT changed

    knob = loaded._knobs["osc_balance"]
    previous = loaded.editor.get_patch(1).get_raw("osc_balance")
    _drag_gesture(knob, steps=1)                    # one moved value

    raw = loaded.editor.get_patch(1).get_raw("osc_balance")
    # One fast pointer gesture is coalesced to its latest value, not every
    # skipped integer between pointer events. Release always flushes final CC.
    assert fake_backend.tx_log == [bytes([0xB0, cc, raw])]
    # No-op guard: dragging back to the current value sends nothing extra.
    n = len(fake_backend.tx_log)
    knob._press(_FakeEvent(x_root=50, y_root=50))
    knob._emit_norm(raw / 127.0)                    # same raw value
    knob._release(_FakeEvent())
    assert len(fake_backend.tx_log) == n


# -------------------------------------------------------- 3b. full rotation
@gui_test
def test_portamento_time_is_live_cc5_and_does_not_mutate_patch(
        loaded, fake_transport, fake_backend):
    loaded.connect_midi(fake_transport, channel=1)
    assert "portamento_time" in loaded._midi_only_scales
    before = loaded.editor.bank.to_sysex()

    loaded._midi_only_changed("portamento_time", 100)

    assert fake_backend.tx_log == [bytes([0xB0, 5, 100])]
    assert loaded.editor.bank.to_sysex() == before
    assert "live CC only" in loaded.status_var.get()


@gui_test
def test_modulation_is_live_cc1_and_does_not_mutate_patch(
        loaded, fake_transport, fake_backend):
    loaded.connect_midi(fake_transport, channel=1)
    before = loaded.editor.bank.to_sysex()

    loaded._midi_only_changed("modulation", 73)

    assert fake_backend.tx_log == [bytes([0xB0, 1, 73])]
    assert loaded.editor.bank.to_sysex() == before


@gui_test
def test_knob_range_uses_240_degree_arc_with_minimum_at_bottom(loaded):
    knob = loaded._knobs["osc_balance"]
    cx, cy, radius = knob._cx, knob._cy, knob._r - 1

    knob.set_value(knob.minimum)
    coords_min = knob.coords(knob._arc_item)
    assert len(coords_min) == 6  # two-point minimum arc (start and end coincide)

    # At the minimum, the arc starts at 6 o'clock.
    assert coords_min[1] == pytest.approx(cy + radius, abs=0.1)

    knob.set_value(knob.maximum)
    coords_max = knob.coords(knob._arc_item)
    assert 90 <= len(coords_max) <= 102  # ~240° at 5° per segment
    # Maximum ends at 30°: upper-right, not a full revolution back to start.
    assert coords_max[-2] > cx
    assert coords_max[-1] < cy


@gui_test
def test_vcf_graph_drag_commits_only_the_touched_adsr_field(loaded):
    before = loaded.editor.get_patch(1).get_raw("vcf_decay")
    target = 0 if before != 0 else 1
    undo_depth = len(loaded._history._undo)

    # Attack is intentionally untouched; changing decay must not be erased
    # when the graph commits its edit.
    loaded._env_drag("vcf", "decay", target / 127.0)
    loaded._env_release()

    assert loaded.editor.get_patch(1).get_raw("vcf_decay") == target
    assert len(loaded._history._undo) == undo_depth + 1


# --------------------------------------------------- 4. external sync (RX etc)
@gui_test
def test_external_model_update_moves_the_knob_without_echo(loaded,
                                                           fake_transport,
                                                           fake_backend):
    """A value arriving FROM outside (hardware RX) updates the knob visually
    and never echoes a CC back (§9 feedback guard)."""
    loaded.connect_midi(fake_transport, channel=1)
    fake_backend.tx_log.clear()

    cc = BY_KEY["osc_balance"].cc
    remote_raw = 100
    packet = bytes([0xB0, cc, remote_raw])
    loaded._midi_rx_packet(packet)                  # existing RX entry point

    assert loaded.editor.get_patch(1).get_raw("osc_balance") == remote_raw
    knob = loaded._knobs["osc_balance"]
    assert knob.current_norm == pytest.approx(remote_raw / 127.0, abs=0.01)
    assert int(loaded.vars["osc_balance"].get()) == remote_raw
    assert fake_backend.tx_log == []                # silent, no echo


# --------------------------------------------------------- 5. undo / redo cycle
@gui_test
def test_knob_gesture_undo_redo_restores_projection(loaded):
    original = loaded.editor.get_patch(1).get_raw("osc_balance")
    knob = loaded._knobs["osc_balance"]
    _drag_gesture(knob, steps=2)
    changed = loaded.editor.get_patch(1).get_raw("osc_balance")
    assert changed != original

    loaded.undo()                                   # existing GUI action
    assert loaded.editor.get_patch(1).get_raw("osc_balance") == original
    assert knob.current_norm == pytest.approx(original / 127.0, abs=0.01)

    loaded.redo()
    assert loaded.editor.get_patch(1).get_raw("osc_balance") == changed
    assert knob.current_norm == pytest.approx(changed / 127.0, abs=0.01)


# ---------------------------------------------------- 6. discrete edits: 1 step
@gui_test
def test_wheel_step_outside_gesture_is_one_undo_step(loaded):
    """Keyboard/wheel edits keep the ordinary one-step path (like Scale)."""
    before = loaded.editor.get_patch(1).get_raw("osc_balance")
    depth = len(loaded._history._undo)

    knob = loaded._knobs["osc_balance"]
    knob._wheel_step(+1, _FakeEvent(state=1))       # Shift+wheel = fine +1
    after = loaded.editor.get_patch(1).get_raw("osc_balance")

    assert after == min(127, before + 1)
    assert len(loaded._history._undo) == depth + 1


# -------------------------------------------------------------- 7. reset path
@gui_test
def test_double_click_reset_uses_existing_reset_one(loaded, monkeypatch):
    calls = []
    monkeypatch.setattr(loaded, "reset_one",
                        lambda key: calls.append(key))
    knob = loaded._knobs["osc_balance"]
    knob._double_click(_FakeEvent())
    assert calls == ["osc_balance"]                 # routes to the ONE reset API


# ------------------------------------------------------ 8. resize / layout safe
@gui_test
def test_window_resize_does_not_break_knob_or_sliders(loaded):
    """PR #51 responsive layout must survive the knob (fixed-size canvas)."""
    scales_before = list(loaded._parameter_scales)
    loaded._on_synth_resize(_FakeEvent(width=800))
    loaded.update_idletasks()
    loaded._on_synth_resize(_FakeEvent(width=1400))
    loaded.update_idletasks()

    knob = loaded._knobs["osc_balance"]
    assert knob.winfo_exists()
    # Scales were resized by the existing mechanism, list identity preserved.
    assert loaded._parameter_scales == scales_before
    for s in scales_before:
        assert s.winfo_exists()
    # Label/value pair stays registered so nothing gets truncated silently.
    assert "osc_balance" in loaded.section_labels
    assert "osc_balance" in loaded.reset_buttons


# ------------------------------------------------------------ 9. other controls
@gui_test
def test_other_parameters_still_work_after_knob_intro(loaded):
    """Regression guard: ring_mod_amount (Scale) behaves as before."""
    app = loaded
    before = app.editor.get_patch(1).get_raw("ring_mod_amount")
    app.vars["ring_mod_amount"].set((before + 10) % 128)
    app.apply_parameter("ring_mod_amount")
    assert app.editor.get_patch(1).get_raw("ring_mod_amount") == (before + 10) % 128
    # ADSR vertical sliders untouched too.
    assert any(s.cget("orient") == "vertical" for s in app._parameter_scales)


class _FakeEvent:
    """Minimal stand-in for a Tk event object used by the knob handlers."""

    def __init__(self, x_root=0, y_root=0, state=0, x=0, y=0, delta=0,
                 width=0):
        self.x_root, self.y_root, self.state = x_root, y_root, state
        self.x, self.y, self.delta = x, y, delta
        self.width = width


def _drag_gesture(knob, steps: int, per_move: int = 10) -> None:
    """One synthetic continuous mouse gesture (press + N drags + release).

    ``Knob._drag`` moves the value by ~0.12 normalized units per 10px step
    (vertical upward or horizontal rightward), so a few incremental steps
    change the value noticeably; positive ``steps`` drag upwards/rightwards.
    Each drag event carries the NEW pointer position (incremental movement),
    exactly like real B1-Motion events do.
    """
    knob._press(_FakeEvent(x_root=100, y_root=100))
    y = 100
    for _ in range(abs(steps)):
        y -= per_move if steps > 0 else -per_move
        knob._drag(_FakeEvent(x_root=100, y_root=y, state=0))
    knob._release(_FakeEvent())
