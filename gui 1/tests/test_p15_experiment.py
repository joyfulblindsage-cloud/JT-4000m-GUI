"""P1.5 — A/B SysEx experiment protocol tests (OFFLINE ONLY).

These tests never touch MIDI; they compare local .syx files with the real
project fixtures and assert the evidence discipline:
no invented parameters, no automatic attribution, explicit provenance.
"""
import json

import pytest

from jt4000m.experiment import (
    CLASS_KNOWN, CLASS_NAME, CLASS_UNKNOWN,
    CONF_EXPERIMENTAL, CONF_OBSERVED, CONF_REGISTRY, CONF_AMBIGUOUS,
    EVIDENCE_AB_SYSEX, PROVENANCE_FIXTURE, PROVENANCE_DEVICE,
    Capture, append_evidence, classify_offset, compare_experiment,
    key_for_offset, read_evidence, registry_status,
)
from jt4000m.model import BY_KEY
from jt4000m.patch import Bank, JTProgram
from jt4000m.syx import parse_file


# ---------------------------------------------------------------- classification

def test_classify_known_name_unknown():
    assert classify_offset(0) == CLASS_KNOWN          # osc1_wave
    assert classify_offset(12) == CLASS_KNOWN         # filter_cutoff
    assert classify_offset(55) == CLASS_NAME          # Name[0]
    assert classify_offset(9) == CLASS_UNKNOWN        # not in registry
    assert classify_offset(0x19) == CLASS_UNKNOWN     # 25: unknown byte
    assert key_for_offset(0) == "osc1_wave"
    assert key_for_offset(9) is None


# ------------------------------------------------------- ALL EMPTY vs INIT SAW

def test_compare_first_program_fixture_pair(all_empty, all_init_saw):
    res = compare_experiment(all_empty, all_init_saw, program=1)
    offs = {c.offset for c in res.changes}
    assert 0 in offs                                  # OSC1 wave OFF->SAW
    assert all(c.classification != CLASS_UNKNOWN or
               c.confidence == CONF_OBSERVED for c in res.changes)
    name_changes = [c for c in res.changes if c.classification == CLASS_NAME]
    assert name_changes, "INIT SAW renames the patch"
    for c in name_changes:
        assert 55 <= c.offset <= 63


def test_hypothesis_confirmed_single_byte(all_empty, all_init_saw):
    res = compare_experiment(all_empty, all_init_saw, program=1,
                             hypothesis="osc1_wave")
    assert res.verdict == "CONFIRMED"
    assert res.evidence if hasattr(res, "evidence") else True
    target = [c for c in res.changes if c.offset == 0][0]
    assert target.confidence == CONF_EXPERIMENTAL
    assert target.old == 0 and target.new == 4
    assert target.old_semantic == "OFF" and target.new_semantic == "SAW"
    d = res.to_dict()
    assert d["evidence"] == EVIDENCE_AB_SYSEX
    assert d["expected_cc"] == BY_KEY["osc1_wave"].cc


def test_wrong_hypothesis_never_confirms(all_empty, all_init_saw):
    # filter_cutoff did NOT change between these fixtures; OSC1 Wave and the
    # name did. The tool must report NOT_CONFIRMED (hypothesis unsupported)
    # and refuse to attribute anything automatically — never CONFIRMED.
    res = compare_experiment(all_empty, all_init_saw, program=1,
                             hypothesis="filter_cutoff")
    assert res.verdict == "NOT_CONFIRMED"
    assert all(c.confidence != CONF_EXPERIMENTAL for c in res.changes)


def test_hypothesis_on_identical_files_is_no_change(all_empty):
    res = compare_experiment(all_empty, all_empty, program=1,
                             hypothesis="osc1_wave")
    assert res.verdict == "NO_CHANGE"


def test_ambiguous_extra_bytes(all_empty, all_init_saw, tmp_path):
    # BEFORE = fixture; AFTER = fixture + an extra unknown-byte change at 0x19.
    bank = Bank.load(all_init_saw)
    p = bank.get(1)
    data = bytearray(p.data)
    data[0x19] ^= 0x01
    after = tmp_path / "after.syx"
    Bank(tuple(JTProgram(i, (data if i == 1 else q.data), 8 + (i - 1) * 64)
               for i, q in enumerate(bank.programs, 1))).save(after)
    res = compare_experiment(all_empty, after, program=1,
                             hypothesis="osc1_wave")
    assert res.verdict == "AMBIGUOUS"
    un = [c for c in res.changes if c.classification == CLASS_UNKNOWN]
    assert un and un[0].offset == 0x19
    assert un[0].confidence == CONF_AMBIGUOUS
    # we never rename the unknown byte into a guessed parameter
    assert un[0].field == "Byte 0x19"
    assert un[0].parameter_key is None


def test_identical_files_no_change(all_empty):
    res = compare_experiment(all_empty, all_empty, program=3)
    assert res.verdict == "NO_CHANGE"
    assert res.changes == []
    assert res.to_dict()["evidence"] == "NONE"


def test_provenance_labels_are_explicit(all_empty, all_init_saw):
    res = compare_experiment(all_empty, all_init_saw, program=1,
                             before_provenance=PROVENANCE_FIXTURE,
                             after_provenance=PROVENANCE_DEVICE)
    d = res.to_dict()
    assert d["before"]["provenance"] == "REFERENCE_FIXTURE"
    assert d["after"]["provenance"] == "CAPTURED_FROM_DEVICE"
    # default is REFERENCE_FIXTURE on both sides (fixtures are NOT device proof)
    d2 = compare_experiment(all_empty, all_init_saw).to_dict()
    assert d2["before"]["provenance"] == d2["after"]["provenance"] \
        == "REFERENCE_FIXTURE"


def test_capture_object_and_single_dump(fixtures_dir, tmp_path):
    from jt4000m.syx import serialize_single
    single = tmp_path / "one.syx"
    single.write_bytes(serialize_single(bytes(64)))
    cap = Capture(path=str(single))
    prog = cap.load(program=1)
    assert prog.data == bytes(64)
    with pytest.raises(ValueError):
        cap.load(program=2)   # single dump has only program 1


def test_bulk_slot_selection(all_empty):
    res = compare_experiment(all_empty, all_empty, program=32)
    assert res.program == 32
    with pytest.raises(ValueError):
        compare_experiment(all_empty, all_empty, program=33)


# ------------------------------------------------------------------- reporting

def test_json_markdown_reports(all_empty, all_init_saw, tmp_path):
    res = compare_experiment(all_empty, all_init_saw, program=1,
                             hypothesis="osc1_wave")
    files = res.save(tmp_path / "experiment")
    names = sorted(f.name for f in files)
    assert names == ["experiment.json", "experiment.md"]
    d = json.loads((tmp_path / "experiment.json").read_text("utf-8"))
    assert d["schema"] == "jt4000m-experiment/1"
    assert d["verdict"] == "CONFIRMED"
    assert d["changes"][0]["offset"] == 0
    md = (tmp_path / "experiment.md").read_text("utf-8")
    assert "# JT-4000M Experiment Report" in md
    assert "TRANSPORT VERIFIED" in md and "DEVICE BEHAVIOR VERIFIED" in md
    assert res.timestamp  # ISO timestamp recorded


# -------------------------------------------------- evidence log / registry

def test_registry_status_defaults_all_known_without_log(all_empty, tmp_path):
    rows = registry_status(tmp_path / "empty-log.jsonl")
    assert rows
    # Without any logged experiment NOTHING may be marked confirmed.
    assert all(r["level"] == "known" for r in rows)


def test_promotion_only_via_experiment(all_empty, all_init_saw, tmp_path):
    log = tmp_path / "log.jsonl"
    res = compare_experiment(all_empty, all_init_saw, program=1,
                             hypothesis="osc1_wave")
    append_evidence(res, log)
    rows = registry_status(log)
    by_off = {r["offset"]: r for r in rows}
    assert by_off[0]["level"] == "experimentally_confirmed"
    assert by_off[0]["evidence"]["old"] == 0
    assert by_off[0]["evidence"]["new"] == 4
    assert by_off[0]["evidence"]["before"]["path"] == str(all_empty)
    # other registry params stay merely "known": static mapping proves nothing
    assert by_off[12]["level"] == "known"
    # ambiguous runs do NOT promote anything
    log2 = tmp_path / "log2.jsonl"
    amb = compare_experiment(all_empty, all_init_saw, program=1,
                             hypothesis="filter_cutoff")
    append_evidence(amb, log2)
    assert all(r["level"] != "experimentally_confirmed"
               for r in registry_status(log2))


def test_observed_candidate_offsets_surface(all_empty, all_init_saw, tmp_path):
    # A no-hypothesis comparison that includes an unknown offset logs it as
    # an "observed" candidate in registry_status (never given a name).
    log = tmp_path / "log.jsonl"
    bank = Bank.load(all_empty)
    p = bank.get(1)
    data = bytearray(p.data); data[0x19] = 0x32
    after = tmp_path / "a.syx"
    Bank(tuple(JTProgram(i, (data if i == 1 else q.data), 8 + (i - 1) * 64)
               for i, q in enumerate(bank.programs, 1))).save(after)
    res = compare_experiment(all_empty, after, program=1)
    append_evidence(res, log)
    rows = {r["offset"]: r for r in registry_status(log)}
    assert rows[0x19]["level"] == "observed"
    assert rows[0x19]["key"] is None
    assert rows[0x19]["label"] == "Byte 0x19"


def test_read_evidence_roundtrip(all_empty, all_init_saw, tmp_path):
    log = tmp_path / "log.jsonl"
    res = compare_experiment(all_empty, all_init_saw, program=1)
    append_evidence(res, log)
    recs = read_evidence(log)
    assert len(recs) == len(res.changes)
    assert all(r["evidence"] == EVIDENCE_AB_SYSEX for r in recs)


# ------------------------------------------------------------------------- CLI

def test_cli_experiment_compare_offline(all_empty, all_init_saw, tmp_path,
                                        capsys):
    from jt4000m.cli import main
    js = tmp_path / "rep.json"
    main(["experiment", "compare", str(all_empty), str(all_init_saw),
          "--program", "1", "--hypothesis", "osc1_wave",
          "--json", str(js)])
    out = capsys.readouterr().out
    assert "Verdict: CONFIRMED" in out
    assert "OSC1 Wave" in out and "[PATCH_NAME]" in out
    d = json.loads(js.read_text("utf-8"))
    assert d["verdict"] == "CONFIRMED"


def test_cli_experiment_report_shows_expected_cc(capsys):
    from jt4000m.cli import main
    main(["experiment", "report", "osc1_wave", "--program", "1"])
    out = capsys.readouterr().out
    assert "Expected CC: CC 24" in out
    assert "midi capture --output BEFORE.syx" in out


def test_cli_experiment_report_unknown_param_errors():
    from jt4000m.cli import main
    with pytest.raises(SystemExit):
        main(["experiment", "report", "made_up_parameter"])


def test_cli_registry_status_runs(capsys):
    from jt4000m.cli import main
    main(["experiment", "registry-status"])
    out = capsys.readouterr().out
    assert "osc1_wave" in out
    assert "known" in out
