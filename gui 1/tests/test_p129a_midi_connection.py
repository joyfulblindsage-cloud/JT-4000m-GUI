"""P1.29a — MIDI Connection & Device Discovery: behavioral invariants only.

The GUI connection panel is a thin lifecycle layer over the EXISTING stack
(MidiTransport / MidiSyncBridge / connect_midi).  These tests prove exactly
the contract of that layer with the shared deterministic FakeMidiBackend —
no real MIDI device is ever touched (root conftest safety rule).
"""
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
    spec = importlib.util.spec_from_file_location("_jt4000m_root_conftest_p129a", root)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_HAS_TK = True
try:
    import tkinter  # noqa: F401
except Exception:
    _HAS_TK = False

gui_test = pytest.mark.skipif(not _HAS_TK, reason="no Tk display available")

# Opt into the root-conftest pump neutralizer (see conftest._deterministic_
# midi_pump): RX draining happens ONLY through explicit _poll_midi_once()
# calls, never via leftover after() timers from earlier apps.
midi_pump_control = True


class FailingOutTransport:
    """Minimal seam: input opens fine, output open raises (P1.29a §5 case)."""

    def __init__(self, inner):
        self.inner = inner
        self.closed = 0

    def list_inputs(self):
        return self.inner.list_inputs()

    def list_outputs(self):
        return self.inner.list_outputs()

    def open_input(self, port):
        return self.inner.open_input(port)

    def open_output(self, port):
        raise RuntimeError("output port busy")

    def close(self):
        self.closed += 1
        return self.inner.close()


def _make_app(rx=None, backend=None):
    """Editor with a loaded bank and an INJECTED fake transport behind the
    production panel methods (no real device enumeration ever happens)."""
    from jt4000m.gui import Editor
    from jt4000m.transport import MidiTransport

    if backend is None:
        backend = _root_conftest().FakeMidiBackend(rx=list(rx or []))
    app = Editor()
    app.load_path(ALL_INIT_SAW)
    app.select_program(1)
    transport = MidiTransport(backend=backend, backend_name="rtmidi")
    app._midi_transport = transport          # test seam: injected fake backend
    app.refresh_midi_ports()                 # discovery path itself is production
    return app, backend, transport


def _ports(backend, direction):
    return [p for p in backend.ports if p.direction == direction]


# ------------------------------------------------------------------ discovery
@gui_test
def test_discovery_lists_inputs_and_outputs_separately():
    app, backend, _ = _make_app()
    assert app._midi_in_names == [p.name for p in _ports(backend, "input")]
    assert app._midi_out_names == [p.name for p in _ports(backend, "output")]
    # the two lists are never merged
    assert set(app._midi_in_names) != set(app._midi_out_names)
    # scanning NEVER opens ports (§3): fake ports report no opened index
    assert backend.last_in.opened_index is None
    assert backend.last_out.opened_index is None
    app.destroy()


@gui_test
def test_jt_hint_proposes_default_but_user_can_choose_any_port():
    app, backend, _ = _make_app()
    # fake backend has "JT-4000M MICRO" on both sides -> proposed default
    assert app.midi_in_combo.get() == "JT-4000M MICRO"
    assert app.midi_out_combo.get() == "JT-4000M MICRO"
    # manual override is always possible
    app.midi_out_combo.set("Microsoft GS Wavetable Synth")
    assert app.midi_out_combo.get() == "Microsoft GS Wavetable Synth"
    app.destroy()


@gui_test
def test_refresh_preserves_selection_when_ports_unchanged():
    app, backend, _ = _make_app()
    app.midi_in_combo.set("JT-4000M MICRO")
    app.midi_out_combo.set("Microsoft GS Wavetable Synth")
    app.refresh_midi_ports()
    assert app.midi_in_combo.get() == "JT-4000M MICRO"
    assert app.midi_out_combo.get() == "Microsoft GS Wavetable Synth"
    app.destroy()


@gui_test
def test_refresh_reports_vanished_port_honestly():
    app, backend, _ = _make_app()
    app.midi_out_combo.set("Microsoft GS Wavetable Synth")
    # simulate hot-unplug: drop that output from the fake backend
    backend.ports = [p for p in backend.ports
                     if p.name != "Microsoft GS Wavetable Synth"]
    app.refresh_midi_ports()
    assert app.midi_out_combo.get() != "Microsoft GS Wavetable Synth"
    assert "disappeared" in app.status_var.get()
    assert app._midi_connected is False
    app.destroy()


# -------------------------------------------------------------------- connect
@gui_test
def test_connect_opens_selected_in_and_out():
    app, backend, _ = _make_app()
    assert app.connect_selected_midi() is True
    assert backend.last_in.opened_index is not None
    assert backend.last_out.opened_index is not None
    assert app._midi_connected is True
    assert app.status_lbl.cget("text") == "Status: Connected"
    assert "online" in app.midi_status_var.get()
    # connecting must NOT send any MIDI message (§4 end)
    assert backend.tx_log == []
    app.destroy()


@gui_test
def test_reconnect_is_idempotent_no_second_bridge_or_pump():
    app, backend, _ = _make_app()
    app.connect_selected_midi()
    first_bridge = app._midi_bridge
    first_timer = app._midi_poll_after_id
    assert app.connect_selected_midi() is True     # second click: no-op
    assert app._midi_bridge is first_bridge
    assert app._midi_poll_after_id == first_timer
    app.destroy()


@gui_test
def test_connect_without_both_ports_errors_without_crash():
    app, backend, _ = _make_app()
    app.midi_out_combo.set("")
    assert app.connect_selected_midi() is False
    assert app.status_lbl.cget("text") == "Status: Error"
    assert app._midi_connected is False
    assert backend.last_out.opened_index is None   # nothing was opened
    app.destroy()


@gui_test
def test_output_open_failure_closes_already_open_input():
    """§5: input opens, output fails -> no partially open connection left."""
    app, backend, transport = _make_app()
    failing = FailingOutTransport(transport)
    app._midi_transport = failing
    assert app.connect_selected_midi() is False
    assert failing.closed >= 1                     # rollback happened
    assert app._midi_connected is False
    assert app.status_lbl.cget("text") == "Status: Error"
    assert "busy" in app._midi_last_error
    app.destroy()


# ----------------------------------------------------------------- disconnect
@gui_test
def test_disconnect_closes_both_ports_and_is_double_click_safe():
    app, backend, _ = _make_app()
    app.connect_selected_midi()
    app.disconnect_midi()
    assert backend.last_in.opened_index is None
    assert backend.last_out.opened_index is None
    assert app._midi_connected is False
    assert app.status_lbl.cget("text") == "Status: Offline"
    assert app.midi_status_var.get() == "MIDI: offline"
    assert app._midi_bridge is None                # stale bridge dropped
    app.disconnect_midi()                          # double click: safe no-op
    assert app._midi_connected is False
    app.destroy()


@gui_test
def test_reconnect_after_disconnect_works():
    app, backend, _ = _make_app()
    app.connect_selected_midi()
    app.disconnect_midi()
    assert app.connect_selected_midi() is True
    assert app._midi_connected is True
    app.destroy()


# --------------------------------------------------- integration with P1.27/28
@gui_test
def test_cc_tx_rx_use_the_panel_selected_ports():
    app, backend, _ = _make_app(rx=[bytes([0xB0, 74, 42])])
    app.connect_selected_midi()
    app.editor.set_slot_parameter(app.editor.selected, "filter_cutoff", 99)
    app._midi_tx("filter_cutoff", 99)
    assert bytes([0xB0, 74, 99]) in backend.tx_log            # TX -> chosen OUT
    app._poll_midi_once()                                     # RX <- chosen IN
    assert app.editor.get_patch(app.editor.selected).get_raw("filter_cutoff") == 42
    app.destroy()


@gui_test
def test_program_change_tx_rx_over_the_panel_connection():
    app, backend, _ = _make_app(rx=[bytes([0xC0, 16])])
    app.connect_selected_midi()
    app.select_program(17)                                   # user navigation
    assert bytes([0xC0, 16]) in backend.tx_log               # PC TX via OUT port
    before = len(backend.tx_log)
    app._poll_midi_once()                                    # PC RX via IN port
    assert app.selected_index == 17
    assert app.editor.selected == 17
    assert app.editor.is_dirty() is False                           # selection != edit
    assert len(backend.tx_log) == before                     # no echo (§6)
    app.destroy()


@gui_test
def test_connect_disconnect_never_touch_dirty_or_history():
    app, backend, _ = _make_app()
    depth0 = len(app._history._undo)
    dirty0 = app.editor.is_dirty()
    app.connect_selected_midi()
    app.disconnect_midi()
    assert app.editor.is_dirty() == dirty0
    assert len(app._history._undo) == depth0
    assert app.selected_index == 1                           # patch untouched
    app.destroy()


# --------------------------------------------------------------------- offline
@gui_test
def test_offline_navigation_and_editing_still_work():
    """No backend at all: the editor stays fully usable, TX is silent."""
    from jt4000m.gui import Editor
    app = Editor()                            # panel built against real
    app.load_path(ALL_INIT_SAW)               # transport; we simply never
    app.select_program(1)                     # press Connect
    app.select_program(2)                     # offline navigation works
    assert app.selected_index == 2
    app._nav_step(-1)
    assert app.selected_index == 1
    app.editor.set_slot_parameter(app.editor.selected, "filter_cutoff", 77)
    app._midi_tx("filter_cutoff", 77)         # must not raise when offline
    assert app.editor.is_dirty() is True
    assert app._midi_connected is False
    app.destroy()


@gui_test
def test_destroy_closes_open_ports():
    """§5: closing the app with an active connection releases the ports."""
    app, backend, _ = _make_app()
    app.connect_selected_midi()
    app.destroy()
    assert backend.last_in.opened_index is None
    assert backend.last_out.opened_index is None


# ------------------------------------------------------------------- contracts
@gui_test
def test_gui_module_stays_midi_free_on_import():
    """P1.27/P1.29a contract: lazy imports only — importing jt4000m.gui must
    not pull the MIDI stack into sys.modules."""
    import subprocess
    code = (
        "import sys;"
        "sys.path.insert(0, %r);"
        "import jt4000m.gui;"
        "bad=[m for m in sys.modules if m.startswith('jt4000m.midi')];"
        "print('LEAK:' + ','.join(bad) if bad else 'OK')"
        % _ROOT
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert "OK" in out.stdout, out.stdout + out.stderr
