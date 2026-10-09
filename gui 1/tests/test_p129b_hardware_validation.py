"""P1.29b — Hardware Validation: diagnostic-path invariants (fake backend only).

These tests prove that the EXISTING midi_events stream plus the new minimal
GUI surfaces carry enough information to localize a real hardware problem:
port names, open success/failure, TX/RX direction with type/channel/cc/value,
PC slot/program, and honest error reasons.  No real MIDI device is touched;
the deterministic pump mechanism from P1.28/P1.29a is reused unchanged.
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
    import importlib.util
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "conftest.py"
    spec = importlib.util.spec_from_file_location("_jt4000m_root_conftest_p129b", root)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_HAS_TK = True
try:
    import tkinter  # noqa: F401
except Exception:
    _HAS_TK = False

gui_test = pytest.mark.skipif(not _HAS_TK, reason="no Tk display available")
midi_pump_control = True   # reuse the deterministic pump neutralizer


class RefusingPort:
    """Wraps an already-opened fake output port but refuses send_message()
    (models a midiOutShortMsg/MMRESULT-level refusal for THIS connection,
    leaving enumeration and input delivery untouched)."""

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def send_message(self, data):
        raise OSError("midiOutShortMsg failed, MMRESULT=0x15")


def _make_app(rx=None, backend=None):
    from jt4000m.gui import Editor
    from jt4000m.transport import MidiTransport

    if backend is None:
        backend = _root_conftest().FakeMidiBackend(rx=list(rx or []))
    app = Editor()
    app.load_path(ALL_INIT_SAW)
    app.select_program(1)
    transport = MidiTransport(backend=backend, backend_name="rtmidi")
    app._midi_transport = transport
    app.refresh_midi_ports()
    return app, backend, transport


# --------------------------------------------------------------- diagnostics
@gui_test
def test_connected_status_names_the_actual_open_ports():
    app, backend, _ = _make_app()
    app.connect_selected_midi()
    text = app.status_lbl.cget("text")
    assert text == "Status: Connected"
    header = app.midi_status_var.get()
    assert "JT-4000M MICRO" in header          # real selected IN name
    assert "In:" in header and "Out:" in header
    app.disconnect_midi()
    app.destroy()


@gui_test
def test_connect_failure_keeps_reason_and_never_claims_connected():
    app, backend, transport = _make_app()
    broken = _root_conftest().FakeMidiBackend(rx=[])
    broken.ports = [p for p in backend.ports if p.direction == "input"]
    app._midi_transport = broken               # no output port exists at all
    app.refresh_midi_ports()
    assert app.connect_selected_midi() is False
    assert app._midi_connected is False
    assert app.status_lbl.cget("text") != "Status: Connected"
    assert app._midi_last_error                # honest reason retained
    app.destroy()


@gui_test
def test_tx_api_failure_is_logged_and_surfaced_not_swallowed():
    """§7: backend refusal must be visible (status bar + tx-error event),
    while the app stays fully usable."""
    app, backend, transport = _make_app()
    app.connect_selected_midi()
    assert transport._out_port is not None     # output really opened by Connect
    transport._out_port = RefusingPort(transport._out_port)   # seam
    app.editor.set_slot_parameter(app.editor.selected, "filter_cutoff", 90)
    app._midi_tx("filter_cutoff", 90)
    errs = [e for e in app.midi_events if e["direction"] == "tx-error"]
    assert errs and "MMRESULT" in errs[-1]["message"]
    assert "MIDI TX failed" in app.status_var.get()
    assert app._midi_connected is True         # TX failure != fake disconnect
    app.destroy()


@gui_test
def test_midi_log_view_projects_events_without_second_log():
    app, backend, _ = _make_app(rx=[bytes([0xB0, 74, 42]), bytes([0xC0, 16])])
    app.connect_selected_midi()
    app._poll_midi_once()                      # RX CC + PC through pump
    app._update_midi_log()                     # explicit refresh button path
    rows = app.midi_log_tree.get_children()
    values = [app.midi_log_tree.item(r, "values") for r in rows]
    kinds = {str(v[2]) for v in values}        # 'type' column
    assert "filter_cutoff" in kinds and "program_change" in kinds
    dirs = {str(v[1]) for v in values}
    assert {"rx"} <= dirs
    # view is projection-only: it never invents events
    assert len(rows) == len(app.midi_events)
    app.destroy()


@gui_test
def test_switching_to_research_refreshes_midi_log_view():
    app, backend, _ = _make_app()
    app.connect_selected_midi()
    app.editor.set_slot_parameter(app.editor.selected, "osc_balance", 80)
    app._midi_tx("osc_balance", 80)
    app.current_tab.set("RESEARCH")
    app._switch_tab()
    rows = app.midi_log_tree.get_children()
    assert rows                              # tab entry alone shows the TX row
    first = app.midi_log_tree.item(rows[-1], "values")
    assert str(first[1]) == "tx" and str(first[3]) == "1"   # dir, channel
    app.destroy()


@gui_test
def test_rx_error_from_lost_input_is_logged_with_message():
    """Unplug-style backend failure inside the pump must land in the log
    (direction rx-error + message) instead of killing the GUI thread."""
    app, backend, transport = _make_app()
    app.connect_selected_midi()

    class DeadReceive:
        def __init__(self, inner):
            self.inner = inner

        def __getattr__(self, name):
            return getattr(self.inner, name)

        def get_message(self):
            raise OSError("device disconnected")

    transport._in_port = DeadReceive(transport._in_port)
    app._poll_midi_once()                    # must not raise
    errs = [e for e in app.midi_events if e["direction"] == "rx-error"]
    assert errs and "disconnected" in errs[-1]["message"]
    assert "MIDI RX error" in app.status_var.get()
    app.destroy()


@gui_test
def test_offline_diagnostics_show_selection_and_no_connection_claim():
    app, backend, _ = _make_app()
    app._update_midi_log()
    assert "Offline" in app.midi_diag_lbl.cget("text")
    assert "JT-4000M MICRO" in app.midi_diag_lbl.cget("text")  # selected ports
    assert app.midi_log_tree.get_children() == ()              # nothing faked
    app.destroy()


@gui_test
def test_program_change_tx_row_carries_channel_and_slot():
    app, backend, _ = _make_app()
    app.connect_selected_midi()
    app.select_program(17)
    app._update_midi_log()
    pc_rows = [app.midi_log_tree.item(r, "values")
               for r in app.midi_log_tree.get_children()
               if str(app.midi_log_tree.item(r, "values")[2]) == "program_change"]
    tx = [v for v in pc_rows if str(v[1]) == "tx"]
    assert tx and str(tx[-1][3]) == "1" and str(tx[-1][6]) == "17"  # ch, slot
    app.destroy()
