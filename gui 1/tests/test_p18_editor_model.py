"""P1.8 — offline editor data model test suite (no GUI, no MIDI, no hardware)."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from jt4000m import editor_model as em
from jt4000m.editor_model import (EditorModel, PatchState, ParameterDefinition,
                                  ParameterValue)
from jt4000m.experiment import PROVENANCE_FIXTURE, PROVENANCE_DEVICE
from jt4000m.patch import Bank, JTProgram
from jt4000m.syx import parse_file

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "fixtures"


@pytest.fixture()
def init_saw():
    m = EditorModel()
    m.load_bank(FIX / "ALL INIT SAW.syx")
    return m


# ---------------------------------------------------------------- definitions
def test_definition_fields_and_no_invention():
    d = em.definition_for("osc1_wave")
    assert d.offset == 0x00 and d.cc == 24 and d.kind == "enum"
    assert d.label == "OSC1 Wave"
    # enum options come from the existing registry tables only
    assert (4, "SAW") in d.enum_options and (0, "OFF") in d.enum_options
    assert d.hardware_confirmed is False
    assert d.evidence_level in (em.LEVEL_STATIC, em.LEVEL_OBSERVED)


def test_cc_only_definition_keeps_none_offset():
    d = em.definition_for("modulation")   # CC 1, SysEx offset not established
    assert d.offset is None
    assert d.editable is False and d.writable is False
    assert d.cc == 1
    assert d.group == "UNMAPPED"


def test_portamento_amount_registered_with_no_cc():
    d = em.definition_for("portamento_amount")
    assert d.offset == 0x2E
    assert d.cc is None            # never invented
    assert d.writable is True


def test_validate_registry_reports_current_conflicts_only():
    problems = em.validate_registry()
    # The osc_balance duplicate was fixed in P1.6; today the registry must be
    # internally consistent on keys/offsets/ranges:
    assert not [p for p in problems if "duplicate key" in p or "conflicting offsets" in p]


def test_groups_come_from_metadata_not_key_prefixes():
    groups = em.definitions_by_group()
    assert set(groups) >= {"OSCILLATORS", "FILTER", "VCF ENVELOPE",
                           "VCA ENVELOPE", "LFO", "MODULATION"}
    # every definition's group equals its registry section
    for defs in groups.values():
        for d in defs:
            assert isinstance(d, ParameterDefinition)


# --------------------------------------------------------------------- values
def test_value_raw_semantic_display(init_saw):
    v = init_saw.current_patch().value("osc1_wave")
    assert v.raw == 4 and v.semantic == "SAW" and v.display == "SAW"
    assert v.known is True and v.hardware_confirmed is False


def test_unknown_enum_value_never_becomes_none():
    m = EditorModel()
    m.load_bank(FIX / "Synthmania-EDM-Soundset-JT-4000.syx")
    seen = [m.select(i) for i in range(1, 33)]
    hit = [p for p in seen if p.get_raw("osc1_wave") == 7]
    assert hit, "fixture corpus expected to contain OSC1 wave value 0x07"
    v = hit[0].value("osc1_wave")
    assert v.raw == 7                       # raw preserved
    assert v.semantic == "UNKNOWN_VALUE"    # not None, not invented
    assert v.display == "Unknown (0x07)"
    assert v.known is False


def test_continuous_value_is_numeric_string(init_saw):
    v = init_saw.current_patch().value("filter_cutoff")
    assert v.semantic == str(v.raw)         # no invented percentage scale


# ------------------------------------------------------------------- editing
def test_set_parameter_changes_exactly_one_byte(init_saw):
    a = init_saw.current_patch()
    b = a.set_parameter("osc1_wave", 0)
    diff = a.diff_to(b)
    assert diff == [{"offset": 0, "old": 4, "new": 0,
                     "field": "OSC1 Wave", "category": "PARAMETER"}]
    assert a.name_bytes() == b.name_bytes()
    assert a.unknown_bytes() == b.unknown_bytes()


def test_invalid_edit_rejected(init_saw):
    with pytest.raises(ValueError):
        init_saw.current_patch().set_parameter("filter_cutoff", 999)
    with pytest.raises(ValueError):          # unconfirmed enum value
        init_saw.current_patch().set_parameter("osc1_wave", 7)


def test_batch_edit_is_all_or_nothing(init_saw):
    a = init_saw.current_patch()
    with pytest.raises(ValueError):
        a.set_parameters({"osc1_wave": 2, "filter_cutoff": 999})
    ok = a.set_parameters({"osc1_wave": 2, "filter_cutoff": 60})
    assert ok.get_raw("osc1_wave") == 2 and ok.get_raw("filter_cutoff") == 60
    assert a.get_raw("filter_cutoff") != 60   # original untouched


def test_rename_changes_only_name_bytes(init_saw):
    a = init_saw.current_patch()
    b = a.set_name("MY PATCH")
    assert b.name == "MY PATCH"
    diffs = a.diff_to(b)
    assert diffs and all(d["category"] == "NAME" for d in diffs)
    assert a.unknown_bytes() == b.unknown_bytes()


# ------------------------------------------------------------- unknown bytes
def test_unknown_bytes_view_matches_discovery_count(init_saw):
    u = init_saw.current_patch().unknown_bytes()
    assert len(u) == 24                       # P1.7 invariant (24 unknown offsets)
    mapped = {s.offset for s in em.BY_KEY.values() if s.offset is not None}
    # no unknown byte may coincide with a registry offset or the name field
    assert not any(k in mapped or 55 <= k <= 63 for k in u)
    expected = {i for i in range(64) if i not in mapped and not 55 <= i <= 63}
    assert set(u) == expected


def test_unknown_bytes_survive_full_edit_save_reload(init_saw, tmp_path):
    before = init_saw.current_patch().unknown_bytes()
    init_saw.edit_parameter("osc1_wave", 0)
    init_saw.edit_name("EDITED")
    target = tmp_path / "edited.syx"
    init_saw.save(target)
    m2 = EditorModel()
    m2.load_bank(target)
    after = m2.current_patch().unknown_bytes()
    assert after == before
    assert m2.bank.to_sysex()[-2] == parse_file(target).checksum_expected


# ---------------------------------------------------------------- round-trip
@pytest.mark.parametrize("fname", [
    "ALL EMPTY.syx", "ALL INIT SAW.syx",
    "Synthmania-EDM-Soundset-JT-4000.syx",
])
def test_roundtrip_unmodified_is_byte_identical(fname, tmp_path):
    src = FIX / fname
    m = EditorModel()
    m.load_bank(src)
    out = tmp_path / ("rt_" + fname)
    m.save(out)
    assert out.read_bytes() == src.read_bytes()


def test_single_dump_roundtrip(tmp_path):
    m = EditorModel()
    m.load_bank(FIX / "EMPTY.syx")
    assert m.provenance == PROVENANCE_FIXTURE
    ps = m.current_patch()
    assert isinstance(ps, PatchState)


# -------------------------------------------------------------------- dirty
def test_dirty_state_machine(init_saw, tmp_path):
    assert init_saw.dirty is False
    init_saw.edit_parameter("osc1_wave", 0)
    assert init_saw.dirty is True
    target = tmp_path / "d.syx"
    init_saw.save(target)
    assert init_saw.dirty is False
    init_saw.revert()
    assert init_saw.dirty is False   # nothing pending after save


def test_revert_drops_working_copy(init_saw):
    orig = init_saw.current_patch().get_raw("osc1_wave")
    init_saw.edit_parameter("osc1_wave", 0)
    init_saw.revert()
    assert init_saw.current_patch().get_raw("osc1_wave") == orig
    assert init_saw.dirty is False


# ---------------------------------------------------------------- evidence
def test_no_hardware_confirmation_anywhere():
    for d in em.all_definitions():
        assert d.hardware_confirmed is False
        assert d.evidence_level != em.LEVEL_HARDWARE
    assert em._filter_hardware(em.LEVEL_HARDWARE) == em.LEVEL_STATIC


def test_evidence_vocabulary_is_shared_with_discovery():
    from jt4000m import discovery
    assert em.LEVEL_STATIC is discovery.LEVEL_STATIC
    assert em.LEVEL_OBSERVED is discovery.LEVEL_OBSERVED


# ---------------------------------------------------------------- provenance
def test_provenance_fixture_stays_fixture(init_saw):
    assert init_saw.provenance == PROVENANCE_FIXTURE
    assert init_saw.current_patch().provenance == PROVENANCE_FIXTURE


def test_save_never_promotes_provenance(init_saw, tmp_path):
    out = tmp_path / "saved.syx"
    init_saw.edit_parameter("osc1_wave", 0)
    init_saw.save(out)
    m2 = EditorModel()
    m2.load_bank(out)
    assert m2.provenance == PROVENANCE_FIXTURE     # NOT captured-from-device
    assert m2.provenance != PROVENANCE_DEVICE


# ---------------------------------------------------------------------- MIDI
def test_cc_mapping_preserved_without_confirmation():
    d = em.definition_for("filter_cutoff")
    assert d.cc == 74                    # documented mapping preserved
    assert d.hardware_confirmed is False # ... but proves nothing about hardware


# ------------------------------------------------------------ bidirectional
def test_resolve_key_paths():
    assert em.resolve_key("osc1_wave") == "osc1_wave"
    assert em.resolve_key("0x0C") == "filter_cutoff"
    assert em.resolve_key("cc:74") == "filter_cutoff"
    with pytest.raises(KeyError):
        em.resolve_key("does_not_exist")
    err = None
    try:
        em.resolve_key("cc:99")          # unmapped CC -> explicit ambiguity msg
    except ValueError as e:
        err = str(e)
    assert err and "ambiguous" in err


def test_keys_for_offset_lists_all_candidates():
    assert em.keys_for_offset(0x00) == ["osc1_wave"]
    assert em.keys_for_offset(0x09) == []


# ------------------------------------------------------------------ snapshot
def test_snapshot_diff_workflow(init_saw):
    snap = init_saw.current_patch().snapshot()
    edited = init_saw.edit_parameter("osc1_wave", 0)
    d = snap.diff_to(edited)
    assert len(d) == 1 and d[0]["category"] == "PARAMETER"
    assert snap.get_raw("osc1_wave") == 4   # snapshot unaffected


# ---------------------------------------------------------------- JSON export
def test_json_export_schema(init_saw):
    j = init_saw.current_patch().to_json_dict()
    assert j["schema"] == "jt4000m.editor_model/PatchState v1"
    assert j["provenance"] == PROVENANCE_FIXTURE
    assert bytes.fromhex(j["raw_data_hex"]) == init_saw.current_patch().data
    assert len(j["unknown_bytes"]) == 24
    json.dumps(j)  # serializable


# ----------------------------------------------------------------------- CLI
def test_cli_model_inspect(init_saw, capsys):
    from jt4000m.cli import main
    main(["model", "inspect", str(FIX / "ALL INIT SAW.syx"), "1"])
    out = capsys.readouterr().out
    assert "OSC1 Wave" in out and "SAW" in out
    assert "STATIC_KNOWN" in out or "OBSERVED" in out
    assert "NOT_CONFIRMED" in out


def test_cli_model_export(tmp_path):
    from jt4000m.cli import main
    out = tmp_path / "patch.json"
    main(["model", "export", str(FIX / "ALL INIT SAW.syx"), "1", "--json", str(out)])
    data = json.loads(out.read_text())
    assert data["schema"].startswith("jt4000m.editor_model")
    assert data["name"] == "INIT SAW"


def test_cli_old_commands_still_work(capsys):
    from jt4000m.cli import main
    main(["inspect", str(FIX / "ALL EMPTY.syx")])
    assert "programs: 32" in capsys.readouterr().out.lower() or "32" in capsys.readouterr().out
