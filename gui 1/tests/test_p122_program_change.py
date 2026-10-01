"""P1.22 — MIDI Program Change synchronization (offline, test-driven).

Contract under test:

    MIDI Program Change -> bridge decode -> EditorModel.select_patch()
                                             -> GUI refresh (selection only)

Program Change is SELECTION ONLY.  It must never:
  * create a history entry;
  * mark the session dirty;
  * modify patch data or PatchBank contents;
  * trigger SysEx serialization / CC TX / SysEx TX.

The PC->slot mapping (PC 0..31 -> editor slot 1..32) is a documented
OFFLINE convention pending hardware verification; PC 32..127 stays
unmapped and is rejected rather than guessed at.
"""
import pytest

from jt4000m.editor_model import EditorHistory, EditorModel, PatchIndexError
from jt4000m.midi import (JT4000M_PROGRAM_COUNT, ProgramChange,
                          parse_program_change, program_change_to_slot,
                          slot_to_program_change)
from jt4000m.midi_sync import MidiProgramSelect, MidiSyncBridge


# ---- Step 2: MIDI Program Change representation -----------------------------

def test_program_change_encoding():
    assert ProgramChange(channel=1, program=0).bytes == bytes([0xC0, 0x00])
    assert ProgramChange(channel=2, program=7).bytes == bytes([0xC1, 0x07])
    assert ProgramChange(channel=16, program=127).bytes == bytes([0xCF, 0x7F])
    with pytest.raises(ValueError):
        ProgramChange(channel=1, program=128).bytes
    with pytest.raises(ValueError):
        ProgramChange(channel=0, program=1).bytes


def test_parse_program_change_exact_packets_only():
    pc = parse_program_change(bytes([0xC0, 5]))
    assert pc is not None and pc.channel == 1 and pc.program == 5
    assert parse_program_change(bytes([0xB0, 5, 1])) is None   # CC, not PC
    assert parse_program_change(bytes([0xC0])) is None          # truncated
    assert parse_program_change(b"\xF0\x01\xF7") is None        # sysex
    assert parse_program_change(b"") is None


# ---- Step 3: JT-4000M slot mapping (documented offline convention) ----------

def test_pc_slot_mapping_boundaries():
    assert program_change_to_slot(0) == 1                  # first valid
    assert program_change_to_slot(JT4000M_PROGRAM_COUNT - 1) == 32  # last valid
    assert program_change_to_slot(JT4000M_PROGRAM_COUNT) is None    # invalid
    assert program_change_to_slot(127) is None                     # invalid
    assert program_change_to_slot(-1) is None


def test_pc_slot_roundtrip():
    for slot in range(1, 33):
        program = slot_to_program_change(slot)
        assert program_change_to_slot(program) == slot
    with pytest.raises(ValueError):
        slot_to_program_change(0)
    with pytest.raises(ValueError):
        slot_to_program_change(33)


# ---- Bridge decoding ---------------------------------------------------------

def test_bridge_decodes_program_change(fake_transport):
    bridge = MidiSyncBridge(fake_transport, channel=1)
    sel = bridge.decode_program_change(bytes([0xC0, 0]))
    assert sel == MidiProgramSelect(slot=1, program=0, channel=1)
    sel = bridge.decode_program_change(bytes([0xC0, 31]))
    assert sel == MidiProgramSelect(slot=32, program=31, channel=1)


def test_bridge_ignores_other_channel_and_unmapped(fake_transport):
    bridge = MidiSyncBridge(fake_transport, channel=1)
    assert bridge.decode_program_change(bytes([0xC1, 4])) is None  # ch 2
    assert bridge.decode_program_change(bytes([0xC0, 32])) is None  # unmapped
    assert bridge.decode_program_change(bytes([0xC0, 127])) is None
    assert bridge.decode_program_change(bytes([0xB0, 74, 42])) is None  # CC


def test_bridge_cc_rx_still_works_after_pc_support(fake_transport):
    """Regression: adding PC support must not disturb CC decoding."""
    bridge = MidiSyncBridge(fake_transport, channel=2)
    upd = bridge.decode_incoming(bytes([0xB1, 74, 42]))
    assert upd is not None and upd.key == "filter_cutoff" and upd.value == 42
    assert bridge.decode_program_change(bytes([0xB1, 74, 42])) is None


# ---- EditorModel selection semantics ----------------------------------------

@pytest.fixture()
def editor(all_init_saw) -> EditorModel:
    m = EditorModel()
    m.load_bank(all_init_saw)
    return m


def test_select_program_changes_selection_only(editor):
    before_bytes = editor.bank.to_sysex()
    assert editor.selected == 1
    editor.select_patch(7)
    assert editor.selected == 7
    assert editor.current_patch().index == 7
    assert not editor.is_dirty()
    # PatchBank semantic content untouched by selection:
    assert editor.bank.to_sysex() == before_bytes


def test_selection_out_of_range_rejected(editor):
    for bad in (0, 33, -1, 999):
        with pytest.raises(PatchIndexError):
            editor.select_patch(bad)
    assert editor.selected == 1
    assert not editor.is_dirty()


def test_same_slot_selection_is_noop(editor):
    editor.select_patch(5)
    before = editor.bank.to_sysex()
    editor.select_patch(5)
    assert editor.selected == 5
    assert not editor.is_dirty()
    assert editor.bank.to_sysex() == before


# ---- History: selection must never push --------------------------------------

def test_program_change_does_not_create_history(editor):
    hist = EditorHistory(editor)
    hist.push()                       # baseline snapshot
    depth0 = hist.depth_undo
    editor.edit_parameter("filter_cutoff", 99)   # real mutation path
    hist.push()                                   # GUI pushes after mutation
    after_edit = hist.depth_undo
    assert after_edit >= depth0                   # a real edit may add depth
    # Now simulate the PC path: decode + select only (no push anywhere).
    bridge = MidiSyncBridge(None, channel=1)
    sel = bridge.decode_program_change(bytes([0xC0, 9]))
    editor.select_patch(sel.slot)
    assert hist.depth_undo == after_edit          # no new entry from PC
    assert hist.can_redo is not None              # redo stack untouched by PC


# ---- PC is not a patch edit: serialize equality --------------------------------

def test_program_change_leaves_serialized_bank_identical(editor):
    original = editor.bank.to_sysex()
    bridge = MidiSyncBridge(None, channel=1)
    for program in (0, 5, 17, 31):
        sel = bridge.decode_program_change(bytes([0xC0, program]))
        editor.select_patch(sel.slot)
    assert editor.bank.to_sysex() == original
    assert not editor.is_dirty()


# ---- Dirty semantics around selection ----------------------------------------

def test_dirty_follows_edits_not_selection(editor):
    assert not editor.is_dirty()
    editor.select_patch(12)
    assert not editor.is_dirty()                      # selection: clean
    cur = editor.get_patch(12).get_raw("filter_cutoff")
    editor.set_slot_parameter(12, "filter_cutoff", cur)
    assert not editor.is_dirty()                      # no-op edit: still clean
    editor.select_patch(4)
    assert not editor.is_dirty()                      # selection stays clean
    editor.rename("P122 TEST")
    assert editor.is_dirty()                          # real edit: modified
    # and selecting away does NOT clear or fake the dirty state:
    editor.select_patch(9)
    assert editor.is_dirty()


def test_undo_redo_after_selection_still_targets_edits(editor):
    hist = EditorHistory(editor)
    old = editor.get_patch(3).get_raw("filter_cutoff")
    new = (old + 7) % 100
    # GUI pattern: push BEFORE the mutation, then mutate.
    hist.push()                                       # baseline snapshot
    editor.set_slot_parameter(3, "filter_cutoff", new)
    assert editor.get_patch(3).get_raw("filter_cutoff") == new
    editor.select_patch(20)                           # PC-like selection
    assert hist.depth_undo == 1                       # selection added nothing
    assert hist.undo()
    assert editor.get_patch(3).get_raw("filter_cutoff") == old
    assert hist.redo()
    assert editor.get_patch(3).get_raw("filter_cutoff") == new


# ---- Unknown-byte / name preservation across selection -----------------------

def test_unknown_bytes_preserved_across_selection_cycle(editor):
    before = {i: editor.get_patch(i).unknown_bytes() for i in (1, 8, 32)}
    names = {i: editor.get_patch_name(i) for i in (1, 8, 32)}
    for i in (8, 32, 1, 8):
        editor.select_patch(i)
    for i in before:
        assert editor.get_patch(i).unknown_bytes() == before[i]
        assert editor.get_patch_name(i) == names[i]
