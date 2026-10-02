"""P1.24 — Program Change RX vertical slice (offline, no hardware).

Closes the one proven gap from the Step-3 audit: MidiTransport.receive()
yields ``(timestamp, raw bytes)`` packets, while MidiSyncBridge expects raw
bytes.  This test wires the EXISTING pieces together without adding any new
architectural layer:

    FakeMidiBackend.rx_queue
      -> MidiTransport.receive()            (existing, yields ts+raw bytes)
      -> MidiSyncBridge.decode_program_change(raw)   (existing decoder)
      -> MidiProgramSelect                  (existing, selection-only result)
      -> EditorModel.select_patch(slot)     (existing)
      -> GUI-visible selection state        (editor.selected / current patch)

Contract re-asserted here at the INTEGRATION level (unit-level contracts
already live in test_p122_program_change.py — not duplicated):
  * a remote PC changes selection ONLY;
  * it never marks the session dirty and never touches bank bytes/history;
  * malformed / other-channel / unmapped traffic is ignored, never raises.
"""
from __future__ import annotations

import pytest

from jt4000m.editor_model import EditorHistory, EditorModel
from jt4000m.midi_sync import MidiProgramSelect, MidiSyncBridge


@pytest.fixture()
def editor(all_init_saw) -> EditorModel:
    m = EditorModel()
    m.load_bank(all_init_saw)
    return m


def _rx_transport(fake_backend, fake_transport):
    """Open the JT-4000M input on the injected fake backend."""
    port = fake_transport.find("JT-4000M", "input")[0]
    fake_transport.open_input(port)
    return fake_transport


def _receive_all(transport):
    """Drain transport.receive() into a list of raw byte packets."""
    return [data for _ts, data in transport.receive(timeout=0.2)]


# ---- the vertical slice itself ----------------------------------------------

def test_pc_rx_vertical_slice_selects_patch(editor, fake_backend,
                                            fake_transport):
    transport = _rx_transport(fake_backend, fake_transport)
    bridge = MidiSyncBridge(transport, channel=1)

    # Hardware-side program 6 (0-based) == editor slot 7 (1-based).
    fake_backend.rx_queue = [bytes([0xC0, 6])]

    applied = []
    for raw in _receive_all(transport):
        sel = bridge.decode_program_change(raw)
        if sel is not None:
            editor.select_patch(sel.slot)
            applied.append(sel)

    assert applied == [MidiProgramSelect(slot=7, program=6, channel=1)]
    assert editor.selected == 7
    assert editor.current_patch().index == 7          # GUI-visible selection
    assert not editor.is_dirty()                       # selection never dirties
    assert editor.bank.to_sysex() == editor._baseline  # bytes untouched


def test_pc_rx_boundary_first_and_last(editor, fake_backend, fake_transport):
    transport = _rx_transport(fake_backend, fake_transport)
    bridge = MidiSyncBridge(transport, channel=1)

    fake_backend.rx_queue = [bytes([0xC0, 0]), bytes([0xC0, 31])]
    slots = []
    for raw in _receive_all(transport):
        sel = bridge.decode_program_change(raw)
        if sel is not None:
            editor.select_patch(sel.slot)
            slots.append(sel.slot)

    assert slots == [1, 32]        # first and last valid programs
    assert editor.selected == 32
    assert not editor.is_dirty()


def test_pc_rx_out_of_range_ignored_selection_stays(editor, fake_backend,
                                                    fake_transport):
    transport = _rx_transport(fake_backend, fake_transport)
    bridge = MidiSyncBridge(transport, channel=1)
    editor.select_patch(3)

    fake_backend.rx_queue = [bytes([0xC0, 32]), bytes([0xC0, 127])]
    changed = False
    for raw in _receive_all(transport):
        sel = bridge.decode_program_change(raw)
        if sel is not None:
            editor.select_patch(sel.slot)
            changed = True

    assert not changed                          # never silently clamped/wrapped
    assert editor.selected == 3                 # original selection preserved
    assert not editor.is_dirty()


def test_pc_rx_foreign_traffic_never_breaks_the_chain(editor, fake_backend,
                                                      fake_transport):
    """CC / other-channel PC / truncated / SysEx must be ignored, not raise."""
    transport = _rx_transport(fake_backend, fake_transport)
    bridge = MidiSyncBridge(transport, channel=1)

    fake_backend.rx_queue = [
        bytes([0xB0, 74, 99]),      # CC (filter_cutoff) — not our concern here
        bytes([0xC1, 5]),           # PC on channel 2 — wrong channel
        bytes([0xC0]),              # truncated PC
        b"\xF0\x43\x00\xF7",        # SysEx buffer
    ]
    selections = []
    for raw in _receive_all(transport):
        sel = bridge.decode_program_change(raw)
        if sel is not None:
            selections.append(sel)

    assert selections == []
    assert editor.selected == 1
    assert not editor.is_dirty()


def test_pc_rx_does_not_push_history(editor, fake_backend, fake_transport):
    transport = _rx_transport(fake_backend, fake_transport)
    bridge = MidiSyncBridge(transport, channel=1)
    hist = EditorHistory(editor)
    hist.push()                                   # baseline snapshot
    depth0 = hist.depth_undo

    fake_backend.rx_queue = [bytes([0xC0, 11])]
    for raw in _receive_all(transport):
        sel = bridge.decode_program_change(raw)
        if sel is not None:
            editor.select_patch(sel.slot)

    assert editor.selected == 12
    assert hist.depth_undo == depth0              # remote PC added no entry
    assert not editor.is_dirty()
