"""P1.27 — Bidirectional MIDI Core: minimal behavioral slice tests.

Scope (per the P1.27 contract): ONLY the six CC-mapped parameters
(filter_cutoff, filter_resonance, osc_balance, osc1_wave, osc2_wave,
filter_env_amount aka "VCF Amount") in both directions:

    GUI -> EditorModel -> MidiSyncBridge -> CC -> (fake) hardware
    (fake) hardware -> CC -> MidiSyncBridge -> EditorModel -> GUI projection

No real MIDI is ever touched: everything runs against the injected
FakeMidiBackend from the root conftest (P1.5 safety rule).  Program Change,
SysEx transfer and history-architecture changes are explicitly OUT of
scope here — this file only proves the first vertical CC slice.
"""
from __future__ import annotations

import os
import sys

import pytest

# The root conftest.py (repo root) hosts FakeMidiBackend; make it importable
# from tests/ regardless of which conftest pytest binds to first.
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from jt4000m.editor_model import EditorModel
from jt4000m.midi import cc_to_parameter, parameter_to_cc
from jt4000m.midi_sync import MidiSyncBridge
from jt4000m.model import BY_KEY

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures")
ALL_INIT_SAW = os.path.abspath(os.path.join(FIXTURES, "ALL INIT SAW.syx"))

# The six P1.27 parameters and the current project-consensus CC mapping.
SLICE = {
    "filter_cutoff": 74,
    "filter_resonance": 71,
    "osc_balance": 29,
    "osc1_wave": 24,
    "osc2_wave": 25,      # working consensus; CC22 conflict is a SEPARATE task
    "filter_env_amount": 47,
}


def _model() -> EditorModel:
    m = EditorModel()
    m.load_bank(ALL_INIT_SAW)
    return m


# --------------------------------------------------------------- 1. Mapping
@pytest.mark.parametrize("key,cc", sorted(SLICE.items()))
def test_registry_maps_the_six_parameters_to_consensus_ccs(key, cc):
    """Canonical IDs come from the Registry; no new IDs, no GUI-side table."""
    assert BY_KEY[key].cc == cc
    msg = parameter_to_cc(key, 64, channel=1)
    assert (msg.controller, msg.bytes()[0], msg.value) == (cc, 0xB0, 64)
    decoded = cc_to_parameter(cc, 64)
    assert decoded is not None and decoded[0] == key   # round-trip by semantic key


# -------------------------------------------------------------------- 2. TX
def test_tx_editor_model_change_emits_expected_cc(fake_transport, fake_backend):
    model = _model()
    output = fake_transport.find("JT-4000M", "output")[0]
    bridge = MidiSyncBridge(fake_transport, channel=1, output=output)

    model.set_slot_parameter(model.selected, "filter_cutoff", 99)
    report = bridge.send_parameter("filter_cutoff", 99)

    assert fake_backend.tx_log == [bytes([0xB0, 74, 99])]
    assert report is not None
    # Transport success NEVER claims the device acknowledged anything.
    assert report.device_response == "NOT VERIFIED"


def test_tx_uses_configured_channel_only(fake_transport, fake_backend):
    """§12: the existing bridge channel configuration is the single source."""
    model = _model()
    output = fake_transport.find("JT-4000M", "output")[0]
    bridge = MidiSyncBridge(fake_transport, channel=3, output=output)
    model.set_slot_parameter(model.selected, "osc_balance", 20)
    bridge.send_parameter("osc_balance", 20)
    assert fake_backend.tx_log == [bytes([0xB2, 29, 20])]


# -------------------------------------------------------------------- 3. RX
def test_rx_cc_mutates_editor_model_semantic_parameter(fake_transport):
    model = _model()
    bridge = MidiSyncBridge(fake_transport, channel=1)

    update = bridge.decode_incoming(bytes([0xB0, 74, 42]))
    assert update is not None and update.key == "filter_cutoff"

    before = model.get_patch(model.selected).get_raw("filter_cutoff")
    mutated = bridge.apply_update(model, update)

    assert before != 42
    assert mutated is True
    assert model.get_patch(model.selected).get_raw("filter_cutoff") == 42
    assert model.is_dirty()          # §7: hardware edit marks dirty...
    assert model.selected == 1       # ...but never changes the selection
    # No auto-save: the on-disk fixture file was never written to.


def test_rx_ignores_foreign_channels_and_unknown_ccs(fake_transport):
    model = _model()
    bridge = MidiSyncBridge(fake_transport, channel=1)
    base = model.bank.to_sysex()
    for packet in (bytes([0xB1, 74, 10]),        # wrong channel
                   bytes([0xB0, 3, 10]),         # unknown CC
                   bytes([0xC0, 5]),             # PC: out of P1.27 scope
                   b"\xF0\x00\x20\x32\xF7"):     # SysEx
        assert bridge.decode_incoming(packet) is None
    assert model.bank.to_sysex() == base
    assert not model.is_dirty()


# ------------------------------------------------------------- 4. No-op (§8)
def test_rx_same_value_is_a_full_noop(fake_transport):
    model = _model()
    bridge = MidiSyncBridge(fake_transport, channel=1)
    current = model.get_patch(model.selected).get_raw("filter_resonance")
    base = model.bank.to_sysex()
    dirty_before = model.is_dirty()

    update = bridge.decode_incoming(bytes([0xB0, 71, current]))
    mutated = bridge.apply_update(model, update)

    assert mutated is False                      # no mutation
    assert model.bank.to_sysex() == base         # byte state untouched
    assert model.is_dirty() == dirty_before      # no spurious dirty flip


def test_rx_unconfirmed_enum_value_is_rejected_not_guessed(fake_transport):
    """§11: an enum CC value outside the Registry table must NOT be applied."""
    model = _model()
    bridge = MidiSyncBridge(fake_transport, channel=1)
    before = model.get_patch(model.selected).get_raw("osc1_wave")
    bad = 100                                    # not in WAVE_NAMES (0..6)
    assert bad not in dict(BY_KEY["osc1_wave"] and __import__(
        "jt4000m.model", fromlist=["ENUM_OPTIONS"]).ENUM_OPTIONS["osc1_wave"])
    update = bridge.decode_incoming(bytes([0xB0, 24, bad]))
    assert update is not None                    # decoding itself succeeds...
    assert bridge.apply_update(model, update) is False   # ...application refuses
    assert model.get_patch(model.selected).get_raw("osc1_wave") == before


# --------------------------------------------------- 5. GUI projection (§6/§7)
_HAS_DISPLAY = True
try:
    import tkinter  # noqa: F401
except Exception:
    _HAS_DISPLAY = False

gui_test = pytest.mark.skipif(not _HAS_DISPLAY, reason="no display available")


def _root_conftest():
    """Import the ROOT conftest (FakeMidiBackend) unambiguously.

    ``import conftest`` resolves to tests/hardware/conftest.py when the full
    suite is collected (pytest puts each test dir's conftest on sys.path), so
    load the shared fake by path instead — deterministic under any run order.
    """
    import importlib.util
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "conftest.py"
    spec = importlib.util.spec_from_file_location("_jt4000m_root_conftest", root)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@gui_test
def test_gui_projects_rx_continuous_and_enum_updates_without_echo():
    """Representative continuous (cutoff) + enum (osc1 wave) round trip:
    CC -> EditorModel -> widgets, with zero echo TX (§9 feedback guard)."""
    FakeMidiBackend = _root_conftest().FakeMidiBackend
    from jt4000m.gui import Editor
    from jt4000m.transport import MidiTransport

    backend = FakeMidiBackend(rx=[bytes([0xB0, 74, 42]),     # cutoff
                                  bytes([0xB0, 24, 2])])     # osc1 SQUARE
    transport = MidiTransport(backend=backend, backend_name="rtmidi")
    app = Editor()
    try:
        app.load_path(ALL_INIT_SAW)
        app.select_program(1)
        assert app.midi_status_var.get() == "MIDI: offline"   # honest default

        assert app.connect_midi(transport, channel=1) is True
        assert "online" in app.midi_status_var.get()          # §14 status reflects reality

        app._poll_midi_once()                                 # deterministic pump

        # EditorModel received the values...
        assert app.editor.get_patch(1).get_raw("filter_cutoff") == 42
        assert app.editor.get_patch(1).get_raw("osc1_wave") == 2
        # ...and the GUI projects them (single source of truth, no widget state).
        assert app.vars["filter_cutoff"].get() == 42
        # osc1/osc2 wave are edited through the animated WaveTile rows on the
        # SYNTH tab; their projection is the tile display (registry DISPLAY).
        assert app._osc_tiles["osc1_wave"].display.upper().startswith("SQUARE")
        assert app.editor.is_dirty()

        # Feedback-loop protection: RX mutations produced NO outgoing traffic.
        assert backend.tx_log == []
        assert [e["direction"] for e in app.midi_events] == ["rx", "rx"]
    finally:
        app.destroy()


@gui_test
def test_gui_user_edit_sends_cc_through_bridge_no_cc_in_gui():
    """GUI TX uses semantic keys only; the CC number comes from the Registry."""
    FakeMidiBackend = _root_conftest().FakeMidiBackend
    from jt4000m.gui import Editor
    from jt4000m.transport import MidiTransport

    backend = FakeMidiBackend()
    transport = MidiTransport(backend=backend, backend_name="rtmidi")
    app = Editor()
    try:
        app.load_path(ALL_INIT_SAW)
        app.select_program(1)
        app.connect_midi(transport, channel=1)

        app.vars["filter_cutoff"].set(100)
        app.apply_parameter("filter_cutoff")
        assert backend.tx_log == [bytes([0xB0, 74, 100])]
        assert app.editor.get_patch(1).get_raw("filter_cutoff") == 100

        # Setting the SAME value again: apply_parameter's no-op guard means
        # no mutation AND no redundant CC (§8 GUI half).
        app.apply_parameter("filter_cutoff")
        assert backend.tx_log == [bytes([0xB0, 74, 100])]
    finally:
        app.destroy()


# ---------------------------------------------------------- 6. Offline (§13)
@gui_test
def test_gui_fully_usable_without_any_midi_hardware():
    from jt4000m.gui import Editor

    app = Editor()
    try:
        assert app._midi_bridge is None
        assert app.midi_status_var.get() == "MIDI: offline"
        app.load_path(ALL_INIT_SAW)
        app.select_program(1)
        app.vars["filter_resonance"].set(55)
        app.apply_parameter("filter_resonance")          # editable, no crash
        assert app.editor.get_patch(1).get_raw("filter_resonance") == 55
        app._midi_tx("filter_resonance", 55)             # TX hook is a silent no-op
        assert app.midi_events == []
    finally:
        app.destroy()


def test_bridge_send_without_output_raises_runtime_not_crash(fake_transport):
    """Even when wired without an output port, failure mode is a catchable
    RuntimeError (the GUI logs it and keeps working — §13)."""
    bridge = MidiSyncBridge(fake_transport, channel=1)     # output=None
    with pytest.raises(RuntimeError):
        bridge.send_parameter("filter_cutoff", 10)
