"""P1.25 — Program Change TX vertical slice (offline, no hardware).

Closes the GUI -> MIDI half of the Program Change round trip using ONLY the
existing architecture:

    GUI selection API (EditorModel.select_patch / slot number)
      -> MidiSyncBridge.send_program_change(slot)     (existing bridge layer)
      -> MidiTransport.send_program_change(...)       (same dispatch as send_cc)
      -> FakeMidiBackend.tx_log                       (exact bytes recorded)

Contract proven here at the INTEGRATION level (unit contracts for PC
encoding/mapping already live in test_p122_program_change.py — not duplicated):
  * one user selection produces EXACTLY ONE Program Change with exact bytes;
  * documented offline convention: GUI slot 1 -> PC 0, slot 7 -> PC 6,
    slot 32 -> PC 31 (still UNVERIFIED against physical hardware);
  * PC TX is selection-only: it never dirties the session, never pushes
    history and never touches bank bytes;
  * re-selecting the same slot is a GUI no-op (see gui.py _sync_selection_
    from_cursor / select_program guards) => zero duplicate TX;
  * invalid slots raise BEFORE any transmission (nothing reaches the backend);
  * TransportReport stays honest: api_ok True != device verified.
"""
from __future__ import annotations

import pytest

from jt4000m.editor_model import EditorHistory, EditorModel
from jt4000m.midi_sync import MidiSyncBridge


@pytest.fixture()
def editor(all_init_saw) -> EditorModel:
    m = EditorModel()
    m.load_bank(all_init_saw)
    return m


@pytest.fixture()
def tx_bridge(editor, fake_transport, fake_backend):
    """Bridge wired to the JT-4000M OUTPUT port on the injected fake backend."""
    out = fake_transport.find("JT-4000M", "output")[0]
    return MidiSyncBridge(fake_transport, channel=1, output=out)


def _select_like_gui(editor: EditorModel, bridge: MidiSyncBridge, slot: int):
    """Replicate the existing GUI selection semantics (gui.py):
    _sync_selection_from_cursor ignores clicks on the already-selected slot,
    select_program() folds pending edits via commit(), then calls
    EditorModel.select_patch().  The MIDI TX hook lives in the bridge layer,
    NOT inside EditorModel."""
    if slot == editor.selected:          # GUI guard: same-slot click = no-op
        return None
    editor.commit()
    editor.select_patch(slot)
    return bridge.send_program_change(slot)


# ---- the vertical slice itself ----------------------------------------------

@pytest.mark.parametrize("slot,program", [(1, 0), (7, 6), (32, 31)])
def test_pc_tx_exact_bytes_for_documented_convention(editor, fake_backend,
                                                     tx_bridge, slot, program):
    if editor.selected == slot:                # already selected -> move first
        _select_like_gui(editor, tx_bridge, 5)
        fake_backend.tx_log.clear()            # keep the assertion one-message
    rep = _select_like_gui(editor, tx_bridge, slot)

    assert rep is not None
    expected = bytes([0xC0, program])          # channel 1 -> status 0xC0
    assert rep.tx_bytes == expected
    assert rep.api_ok is True
    assert rep.device_response == "NOT VERIFIED"
    assert rep.op == "program_change"
    # EXACTLY one message reached the backend, with exactly these bytes:
    assert fake_backend.tx_log == [expected]
    # selection moved through the same API the GUI uses:
    assert editor.selected == slot
    assert editor.current_patch().index == slot


def test_pc_tx_is_selection_only_no_dirty_no_history(editor, fake_backend,
                                                     tx_bridge):
    hist = EditorHistory(editor)
    hist.push()
    depth0 = hist.depth_undo
    bank0 = editor.bank.to_sysex()

    _select_like_gui(editor, tx_bridge, 7)

    assert fake_backend.tx_log == [bytes([0xC0, 6])]
    assert not editor.is_dirty()               # remote/local PC never dirties
    assert hist.depth_undo == depth0           # selection adds no history entry
    assert editor.bank.to_sysex() == bank0     # bank bytes untouched


def test_pc_tx_reselect_same_slot_is_noop_zero_duplicate_tx(editor,
                                                            fake_backend,
                                                            tx_bridge):
    _select_like_gui(editor, tx_bridge, 7)
    before = list(fake_backend.tx_log)

    again = _select_like_gui(editor, tx_bridge, 7)   # same-slot click

    assert again is None                            # GUI-level no-op branch
    assert fake_backend.tx_log == before            # no duplicate TX
    assert len(fake_backend.tx_log) == 1


def test_pc_tx_invalid_slot_refused_before_transmission(editor, fake_backend,
                                                        tx_bridge):
    with pytest.raises(ValueError):
        tx_bridge.send_program_change(0)
    with pytest.raises(ValueError):
        tx_bridge.send_program_change(33)

    assert fake_backend.tx_log == []              # nothing hit the backend


def test_pc_tx_without_output_port_raises_and_sends_nothing(editor,
                                                            fake_transport,
                                                            fake_backend):
    bridge = MidiSyncBridge(fake_transport, channel=1)  # output=None
    with pytest.raises(RuntimeError, match="No MIDI output"):
        bridge.send_program_change(5)
    assert fake_backend.tx_log == []


def test_pc_tx_honest_report_on_backend_failure(editor, fake_transport,
                                                fake_backend):
    """A backend exception becomes an honest FAILED report, not a crash and
    not a false success."""
    def boom(data):
        raise OSError("winmm write failed")
    fake_backend.last_out_send = None
    out_port = fake_transport.find("JT-4000M", "output")[0]
    fake_transport.open_output(out_port)          # ensure last_out exists
    fake_backend.last_out.send_message = boom

    bridge = MidiSyncBridge(fake_transport, channel=1, output=out_port)
    rep = bridge.send_program_change(3)

    assert rep.api_ok is False
    assert "winmm write failed" in rep.error
    assert rep.tx_bytes == bytes([0xC0, 2])       # what was attempted
    assert rep.device_response == "NOT VERIFIED"


def test_offline_editor_model_tests_need_no_transport(all_init_saw):
    """Boundary guard: plain EditorModel selection works with NO transport,
    NO bridge, NO backend object anywhere."""
    m = EditorModel()
    m.load_bank(all_init_saw)
    patch = m.select_patch(9)                     # identical GUI API call
    assert m.selected == 9
    assert patch.index == 9
    assert not m.is_dirty()
