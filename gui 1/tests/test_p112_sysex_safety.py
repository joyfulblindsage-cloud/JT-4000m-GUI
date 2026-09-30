"""P1.12 — SysEx Safety Contracts (restored into this branch).

These tests formalise the raw-byte invariants verified during the P1.9-P1.12
audits and protect them as automatic regression contracts:

  CONTRACT 1  rename touches only offsets 55..63 (the name window)
  CONTRACT 2  name truncation at 9 bytes; "1234567890" -> "123456789"
  CONTRACT 3  byte 54 is structurally OUTSIDE the name window and is
              preserved unchanged by rename. It is NOT claimed to be
              "unused" — no such evidence exists.
  CONTRACT 4  a single known-parameter edit changes exactly its mapped
              registry byte inside the program payload
  CONTRACT 5  unknown bytes survive edit + rename round-trip
  CONTRACT 6  unmodified fixture: parse -> serialize == original bytes
  CONTRACT 7  parse -> serialize -> reload -> serialize is stable
  CONTRACT 8  bulk banks keep 32 programs and their order
  CONTRACT 9  no-op mutations produce byte-identical serialization
  CONTRACT 10 checksum correctness is owned by the serializer layer
  CONTRACT 11 save -> reload -> serialize identity

All tests are offline and fixture-driven. No MIDI, no hardware, no new
parameter mappings, no evidence promotion. HARDWARE_CONFIRMED stays 0.
"""
from pathlib import Path

import pytest

from jt4000m import syx
from jt4000m.editor_model import EditorModel
from jt4000m.model import BY_KEY
from jt4000m.syx import NAME_END, NAME_START, parse_file, serialize_bulk, serialize_single

pytestmark = pytest.mark.syx_safety

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
BULK_FIXTURES = ["ALL EMPTY.syx", "ALL INIT SAW.syx",
                 "Synthmania-EDM-Soundset-JT-4000.syx"]
SINGLE_FIXTURES = ["EMPTY.syx"]


# --------------------------------------------------------------------------
# Boundary constants themselves must stay pinned.
# --------------------------------------------------------------------------
def test_name_boundary_constants():
    assert NAME_START == 55
    assert NAME_END == 64          # exclusive -> last name offset is 63
    assert (NAME_END - NAME_START) == 9


# --------------------------------------------------------------------------
# CONTRACTS 1/2/3 — rename isolation, truncation, byte-54 untouched.
# EditorModel slots are 1-based (hardware program numbers 1..32).
# --------------------------------------------------------------------------
@pytest.mark.parametrize("fixture", BULK_FIXTURES)
def test_rename_touches_only_name_window(fixture):
    model = EditorModel()
    model.load_bank(FIXTURES / fixture)
    before = bytes(model.get_patch(1).data)
    model.select_patch(1)
    model.edit_name("TEST")
    after = bytes(model.current_patch().data)
    changed = {i for i in range(len(before)) if before[i] != after[i]}
    assert changed <= set(range(55, 64)), f"rename escaped name window: {sorted(changed)}"
    assert before[54] == after[54]           # CONTRACT 3
    assert before[:54] == after[:54]         # everything below the window intact


def test_rename_truncation_contract():
    model = EditorModel()
    model.load_bank(FIXTURES / "ALL INIT SAW.syx")
    model.select_patch(1)
    st = model.edit_name("TEST")
    data = bytes(st.data)
    assert data[55:59] == b"TEST"
    assert data[54] == 0                     # padding never leaks into byte 54
    st9 = model.edit_name("123456789")
    assert bytes(st9.data)[55:64] == b"123456789"
    st10 = model.edit_name("1234567890")     # 10 chars truncate to 9
    d10 = bytes(st10.data)
    assert d10[55:64] == b"123456789"
    assert d10[54] == 0


def test_rename_noop_is_not_a_mutation():
    """Renaming to the same effective name must not flip dirty."""
    model = EditorModel()
    model.load_bank(FIXTURES / "ALL INIT SAW.syx")
    current = model.current_patch().name
    model.edit_name(current)
    assert model.is_dirty() is False


# --------------------------------------------------------------------------
# CONTRACT 4 — single parameter edit changes exactly its mapped byte.
# --------------------------------------------------------------------------
@pytest.mark.parametrize("key,offset", [
    ("osc1_wave", 0), ("osc_balance", 8), ("filter_cutoff", 12),
    ("vcf_release", 17), ("filter_env_amount", 22),
])
def test_parameter_edit_changes_exactly_one_byte(key, offset):
    spec = BY_KEY[key]
    assert spec.offset == offset             # registry pin
    model = EditorModel()
    model.load_bank(FIXTURES / "ALL INIT SAW.syx")
    patch = model.current_patch()
    old = patch.get_raw(key)
    new_value = 0 if old != 0 else 1
    updated = patch.set_parameter(key, new_value)
    before, after = bytes(patch.data), bytes(updated.data)
    changed = {i for i in range(len(before)) if before[i] != after[i]}
    assert changed == {offset}, f"{key}: unexpected changed offsets {sorted(changed)}"


# --------------------------------------------------------------------------
# CONTRACT 5 — unknown bytes preserved through edit+rename.
# --------------------------------------------------------------------------
def test_unknown_bytes_survive_edit_and_rename():
    model = EditorModel()
    model.load_bank(FIXTURES / "Synthmania-EDM-Soundset-JT-4000.syx")
    name_offsets = set(range(55, 64))
    before = bytes(model.current_patch().data)
    model.edit_parameter("filter_resonance",
                         (model.current_patch().get_raw("filter_resonance") + 7) & 0x7F)
    model.edit_name("SAFETY T")
    after = bytes(model.current_patch().data)
    touched = {13} | name_offsets            # resonance byte + name window
    for i in range(64):
        if i in touched:
            continue
        assert before[i] == after[i], f"unknown byte {i} was modified"


# --------------------------------------------------------------------------
# CONTRACTS 6/7/8 — round-trip, re-serialization stability, 32-slot order.
# --------------------------------------------------------------------------
@pytest.mark.parametrize("fixture", BULK_FIXTURES)
def test_bulk_roundtrip_byte_identity(fixture):
    raw = (FIXTURES / fixture).read_bytes()
    parsed = parse_file(FIXTURES / fixture)
    out = serialize_bulk(parsed.programs)
    assert out == raw                                 # CONTRACT 6
    reparsed = syx.parse(out)
    assert serialize_bulk(reparsed.programs) == raw   # CONTRACT 7
    assert len(parsed.programs) == 32                 # CONTRACT 8
    assert [p.name for p in parsed.programs] == [p.name for p in reparsed.programs]


@pytest.mark.parametrize("fixture", SINGLE_FIXTURES)
def test_single_roundtrip_byte_identity(fixture):
    raw = (FIXTURES / fixture).read_bytes()
    parsed = parse_file(FIXTURES / fixture)
    out = serialize_single(parsed.programs[0])
    assert out == raw
    assert syx.parse(out).programs[0].data == parsed.programs[0].data


# --------------------------------------------------------------------------
# CONTRACT 9 — no-op mutation => byte-identical bank serialization.
# --------------------------------------------------------------------------
def test_noop_edits_keep_serialization_identical():
    fixture = FIXTURES / "Synthmania-EDM-Soundset-JT-4000.syx"
    model = EditorModel()
    model.load_bank(fixture)
    base = model.bank.to_sysex()
    cur = model.current_patch()
    model.edit_parameter("filter_cutoff", cur.get_raw("filter_cutoff"))  # same value
    model.edit_name(cur.name)                       # same effective name
    assert model.is_dirty() is False
    assert model.bank.to_sysex() == base


# --------------------------------------------------------------------------
# CONTRACT 10 — checksum ownership: serializer output always validates.
# --------------------------------------------------------------------------
@pytest.mark.parametrize("fixture", BULK_FIXTURES + SINGLE_FIXTURES)
def test_checksum_valid_after_every_serialization(fixture):
    parsed = parse_file(FIXTURES / fixture)
    out = (serialize_bulk(parsed.programs) if len(parsed.programs) > 1
           else serialize_single(parsed.programs[0]))
    assert syx.parse(out).checksum_ok
    # after an edit, the editor's own export path still produces valid checksum
    model = EditorModel()
    model.load_bank(FIXTURES / fixture)
    model.edit_parameter("filter_cutoff",
                         (model.current_patch().get_raw("filter_cutoff") + 5) & 0x7F)
    out2 = model.bank.to_sysex()
    assert syx.parse(out2).checksum_ok


# --------------------------------------------------------------------------
# CONTRACT 11 — save -> reload -> serialize identity.
# --------------------------------------------------------------------------
def test_save_reload_serialize_identity(tmp_path):
    src = tmp_path / "edited.syx"
    model = EditorModel()
    model.load_bank(FIXTURES / "ALL INIT SAW.syx")
    model.edit_parameter("filter_resonance",
                         (model.current_patch().get_raw("filter_resonance") + 9) & 0x7F)
    model.edit_name("SAFE TEST")
    saved = model.save(src)
    assert model.is_dirty() is False
    raw = Path(saved).read_bytes()
    assert syx.parse(raw).checksum_ok
    again = EditorModel()
    again.load_bank(saved)
    assert again.current_patch().name == "SAFE TEST"
    assert again.bank.to_sysex() == raw
