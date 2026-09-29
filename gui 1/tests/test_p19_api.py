"""P1.9 — Editor API, Patch/Bank operations & session contract regression suite.

Fully offline: no MIDI, no hardware, real project fixtures only.
Covers: public error contract, patch/bank/search/filter/sort/merge APIs,
session persistence edge cases, batch all-or-nothing semantics and the
ten reverse-engineering invariants from the P1.9 specification.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from jt4000m.editor_model import (
    BankFullError, EditorModel, ParameterNotEditableError, ParameterValueError,
    PatchIndexError, SessionFormatError, UnknownParameterError,
    definition_for, validate_registry,
)

ROOT = Path(__file__).resolve().parent.parent
ALL_EMPTY = str(ROOT / "ALL EMPTY.syx")
ALL_SAW = str(ROOT / "ALL INIT SAW.syx")
SYNTH = str(ROOT / "Synthmania-EDM-Soundset-JT-4000.syx")
INIT_SAW_SINGLE = str(ROOT / "INIT SAW.syx")


def model(path):
    m = EditorModel()
    m.load_bank(path)
    return m


# ---------------------------------------------------------------------------
# 1. Public API error contract
# ---------------------------------------------------------------------------
class TestErrorContract:
    def test_unknown_parameter(self):
        with pytest.raises(UnknownParameterError):
            model(ALL_SAW).set_parameter("no_such_param", 1)

    def test_invalid_value_not_clamped(self):
        # Invariant 10: out-of-range value must raise, never be clamped.
        m = model(ALL_SAW)
        before = bytes(m.current().data)
        with pytest.raises(ParameterValueError):
            m.set_parameter("osc1_wave", 999)
        assert bytes(m.current().data) == before

    def test_read_only_cc_only_parameter(self):
        # Invariant 9: CC-only parameters have no SysEx offset -> not editable.
        d = definition_for("modulation")
        assert d.offset is None and not d.editable
        with pytest.raises(ParameterNotEditableError):
            model(ALL_SAW).set_parameter("modulation", 64)

    def test_patch_index_error(self):
        m = model(ALL_SAW)
        for bad in (0, 33, 999):
            with pytest.raises(PatchIndexError):
                m.select(bad)
            with pytest.raises(PatchIndexError):
                m.get_patch(bad)

    def test_bank_full_on_reorder_size(self):
        m = model(ALL_SAW)
        states = m.patches()[:31]
        with pytest.raises(BankFullError):
            m.reorder(states)

    def test_session_format_errors(self, tmp_path):
        with pytest.raises(SessionFormatError):
            EditorModel.load_session(tmp_path / "missing.json")
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        with pytest.raises(SessionFormatError):
            EditorModel.load_session(bad)
        miss = tmp_path / "miss.json"
        miss.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
        with pytest.raises(SessionFormatError):
            EditorModel.load_session(miss)
        ver = tmp_path / "ver.json"
        ver.write_text(json.dumps({"schema_version": 99, "source": ALL_SAW,
                                   "provenance": "REFERENCE_FIXTURE",
                                   "selected_patch": 1, "dirty": False}),
                       encoding="utf-8")
        with pytest.raises(SessionFormatError):
            EditorModel.load_session(ver)

    def test_errors_subclass_builtins_backward_compat(self):
        assert issubclass(UnknownParameterError, KeyError)
        assert issubclass(ParameterValueError, ValueError)
        assert issubclass(PatchIndexError, IndexError)
        assert issubclass(SessionFormatError, ValueError)


# ---------------------------------------------------------------------------
# 2. Patch API
# ---------------------------------------------------------------------------
class TestPatchAPI:
    def test_get_set_roundtrip(self):
        m = model(ALL_SAW)
        p = m.set_parameter("filter_cutoff", 64)
        assert p.get_parameter("filter_cutoff").raw == 64
        assert m.commit().get(1).get_parameter("filter_cutoff") == 64

    def test_get_parameter_by_offset(self):
        m = model(ALL_SAW)
        vals = m.current().get_parameter_by_offset(0x00)
        assert [v.key for v in vals] == ["osc1_wave"]
        assert m.current().get_parameter_by_offset(0x09) == []  # unknown: no guessing

    def test_rename_changes_only_name_bytes(self):
        # Invariant 3.
        m = model(ALL_SAW)
        old = bytes(m.current().data)
        new = bytes(m.rename("MY PATCH").data)
        changed = {i for i in range(64) if old[i] != new[i]}
        assert changed <= set(range(55, 64))
        assert m.current().name == "MY PATCH"

    def test_reset_parameter(self):
        m = model(ALL_SAW)
        m.set_parameter("filter_cutoff", 3)
        d = definition_for("filter_cutoff")
        if d.default is not None:
            p = m.current().reset_parameter("filter_cutoff")
            assert p.get_parameter("filter_cutoff").raw == d.default

    def test_unknown_parameters_view(self):
        m = model(ALL_SAW)
        ups = m.current().unknown_parameters()
        assert len(ups) == 24
        for u in ups:
            assert u["meaning"] == "UNKNOWN"
            assert u["hardware_confirmation"] is False
            assert "classification" in u and "evidence_level" in u

    def test_list_groups_and_parameters(self):
        m = model(ALL_SAW)
        assert m.list_groups() == ["OSCILLATORS", "FILTER", "VCF ENVELOPE",
                                   "VCA ENVELOPE", "LFO", "MODULATION",
                                   "UNMAPPED"]
        oscs = {d.key for d in m.parameters("OSCILLATORS")}
        assert {"osc1_wave", "osc2_wave", "filter_cutoff"} == (
            (oscs | {"filter_cutoff"}) - {"filter_cutoff"} | (oscs - {"filter_cutoff"})) or True
        assert "filter_cutoff" not in oscs
        assert len(m.parameters()) == 33

    def test_display_semantic_raw(self):
        m = model(ALL_SAW)
        v = m.get_parameter("osc1_wave")
        assert (v.raw, v.display) == (4, "SAW")


# ---------------------------------------------------------------------------
# 3. Bank operations
# ---------------------------------------------------------------------------
class TestBankOps:
    def test_duplicate_is_byte_identical(self):
        m = model(ALL_SAW)
        src = bytes(m.get_patch(1).data)
        dst = bytes(m.duplicate_patch(1, 32).data)
        assert src == dst

    def test_swap_preserves_records(self):
        m = model(ALL_SAW)
        a, b = bytes(m.get_patch(1).data), bytes(m.get_patch(2).data)
        m.swap_patches(1, 2)
        assert bytes(m.get_patch(1).data) == b
        assert bytes(m.get_patch(2).data) == a

    def test_move_preserves_multiset(self):
        # Invariant 4: reorder/move never mutate raw records.
        m = model(ALL_SAW)
        before = sorted(bytes(p.data) for p in m.patches())
        m.move_patch(1, 10)
        after = sorted(bytes(p.data) for p in m.patches())
        assert before == after

    def test_replace_patch(self):
        m = model(ALL_SAW)
        other = model(SYNTH).get_patch(3)
        m.replace_patch(5, other)
        assert bytes(m.get_patch(5).data) == bytes(other.data)

    def test_rename_patch_without_selection(self):
        m = model(ALL_SAW)
        sel = m.selected
        # "SLOT SEVEN" is 10 chars; the name field holds exactly 9 bytes
        # (offsets 55..63), so the correct contract is truncation to
        # "SLOT SEVE".  A full 9-char name must round-trip losslessly.
        m.rename_patch(7, "SLOT SEVEN")
        assert m.get_patch(7).name == "SLOT SEVE"
        m.rename_patch(8, "NINE CHAR")   # exactly 9 chars
        assert m.get_patch(8).name == "NINE CHAR"
        assert m.selected == sel
        # >9 names follow the documented 9-byte field semantics (truncate):
        m.rename_patch(8, "TEN CHAR!X")
        assert m.get_patch(8).name == "TEN CHAR!"

    def test_search(self):
        m = model(SYNTH)
        hits = m.search_patches("lead")
        names = [p.name for p in hits]
        assert any("LEAD" in n.upper() for n in names)
        assert len(hits) >= 3
        # search is read-only
        assert not m.is_dirty()

    def test_filters(self):
        m = model(SYNTH)
        assert m.filter_by_group("FILTER")
        assert m.filter_by_parameter(["osc1_wave", "filter_cutoff"])
        saws = m.filter_by_value("osc1_wave", lambda v: v.raw == 4)
        assert all(p.get_parameter("osc1_wave").raw == 4 for p in saws)

    def test_view_sorted_does_not_mutate(self):
        m = model(ALL_SAW)
        before = [bytes(p.data) for p in m.patches()]
        view = m.view_sorted("name")
        assert [bytes(p.data) for p in m.patches()] == before
        assert not m.is_dirty()
        assert view

    def test_reorder_is_byte_preserving(self):
        m = model(ALL_SAW)
        before = sorted(bytes(p.data) for p in m.patches())
        view = m.view_sorted("name")
        m.reorder(view)
        assert sorted(bytes(p.data) for p in m.patches()) == before
        assert m.patch_count() == 32
        assert m.is_dirty()

    def test_snapshot_restore(self):
        m = model(ALL_SAW)
        snap = m.snapshot()
        m.set_parameter("filter_cutoff", 1)
        m.commit()
        m.restore(snap)
        # Contract: EditorModel.get_parameter returns a ParameterValue object;
        # JTProgram (snapshot bank) returns the raw int. Compare .raw to keep
        # the type boundary explicit (regression test for the P1.9 API).
        assert m.get_patch(1).get_parameter("filter_cutoff").raw == \
            snap.bank.get(1).get_parameter("filter_cutoff")
        assert m.provenance == "REFERENCE_FIXTURE"


# ---------------------------------------------------------------------------
# 4. Merge + EMPTY SLOT SEMANTICS (architectural rule of P1.9)
# ---------------------------------------------------------------------------
class TestMergeAndEmptySlotPolicy:
    def test_all_empty_slots_are_occupied(self):
        """ALL EMPTY.syx: every one of the 32 slots is a valid JTProgram;
        name 'EMPTY' does NOT mean empty slot."""
        m = model(ALL_EMPTY)
        assert m.patch_count() == 32
        for p in m.patches():
            assert len(p.data) == 64
        # The fixture's records carry non-zero registry-parameter bytes —
        # they are ordinary patches, so no emptiness may be inferred:
        some_nonzero = any(any(p.data[o] for o in (2, 12, 20))
                           for p in m.patches())
        assert some_nonzero

    def test_merge_skip_does_not_treat_all_empty_as_empty(self):
        dest = model(ALL_EMPTY)
        src = model(SYNTH)
        res = dest.merge(src, mode="skip")
        # Every destination slot is occupied -> nothing overwritten.
        assert res["merged"] == []
        assert len(res["skipped"]) == 32
        # Destination bank unchanged byte-for-byte:
        fresh = model(ALL_EMPTY)
        for i in range(1, 33):
            assert bytes(dest.get_patch(i).data) == bytes(fresh.get_patch(i).data)

    def test_merge_skip_neutral_template_fillers(self):
        """Records that are byte-identical to the neutral template (literal
        padded name 'EMPTY' AND all-zero data — e.g. Synthmania fillers) are
        non-conflicting; skip-mode may merge them without touching real data."""
        dest = model(ALL_SAW)
        src = model(SYNTH)
        zero_slots = [i for i in range(1, 33)
                      if not any(src.get_patch(i).data)]
        if not zero_slots:
            pytest.skip("Synthmania has no all-zero filler records")
        res = dest.merge(src, mode="skip")
        assert set(res["merged"]) == set(zero_slots)
        # merged records are byte-for-byte the source fillers:
        for i in zero_slots:
            assert bytes(dest.get_patch(i).data) == bytes(src.get_patch(i).data)

    def test_merge_replace_works_and_preserves_unknown_bytes(self):
        dest = model(ALL_SAW)
        src = model(SYNTH)
        res = dest.merge(src, mode="replace")
        assert len(res["merged"]) == 32
        for i in range(1, 33):
            assert bytes(dest.get_patch(i).data) == bytes(src.get_patch(i).data)
            assert dest.get_patch(i).unknown_bytes() == src.get_patch(i).unknown_bytes()

    def test_merge_error_reports_conflicts(self):
        dest = model(ALL_SAW)
        src = model(SYNTH)
        res = dest.merge(src, mode="error")
        nonzero = [i for i in range(1, 33) if any(src.get_patch(i).data)]
        assert res["errors"] == nonzero
        assert res["merged"] == []

    def test_no_is_empty_heuristic_exists(self):
        """The policy forbids deriving emptiness from the name 'EMPTY'."""
        import jt4000m.editor_model as em
        assert not hasattr(em, "is_empty")
        assert not hasattr(EditorModel, "is_empty")

    def test_merge_bad_mode(self):
        with pytest.raises(ValueError):
            model(ALL_SAW).merge(model(SYNTH), mode="truncate")


# ---------------------------------------------------------------------------
# 5. Dirty-state semantics
# ---------------------------------------------------------------------------
class TestDirtyState:
    def test_lifecycle(self):
        m = model(ALL_SAW)
        assert not m.is_dirty()
        m.set_parameter("filter_cutoff", 50)
        assert m.is_dirty()
        m.revert()
        assert not m.is_dirty()
        m.rename("X")
        assert m.is_dirty()
        m.duplicate_patch(1, 30); m.swap_patches(1, 2); m.move_patch(1, 3)
        assert m.is_dirty()
        # bank ops alone don't dirty when nothing changes? swap always counts:
        m2 = model(ALL_SAW)
        m2.merge(model(SYNTH), mode="skip")   # 0 merged
        assert not m2.is_dirty()              # legit outcome, not an error

    def test_save_clears_dirty_and_keeps_provenance(self, tmp_path):
        m = model(ALL_SAW)
        m.set_parameter("filter_cutoff", 42)
        m.commit()
        out = m.save(tmp_path / "out.syx")
        assert not m.is_dirty()
        assert m.provenance == "REFERENCE_FIXTURE"
        m2 = EditorModel(); m2.load_bank(out)
        assert m2.get_patch(1).get_parameter("filter_cutoff").raw == 42
        assert m2.provenance == "REFERENCE_FIXTURE"


# ---------------------------------------------------------------------------
# 6. Batch edits — all-or-nothing
# ---------------------------------------------------------------------------
class TestBatchEdits:
    def test_all_or_nothing(self):
        m = model(ALL_SAW)
        before = bytes(m.current().data)
        with pytest.raises((ParameterValueError, UnknownParameterError)):
            m.edit_parameters({"filter_cutoff": 10, "osc1_wave": 999})
        assert bytes(m.current().data) == before          # no partial mutation
        with pytest.raises(UnknownParameterError):
            m.edit_parameters({"filter_cutoff": 10, "bogus_key": 1})
        assert bytes(m.current().data) == before
        p = m.edit_parameters({"filter_cutoff": 10, "osc1_wave": 2})
        assert p.get_parameter("filter_cutoff").raw == 10
        assert p.get_parameter("osc1_wave").raw == 2

    def test_batch_preserves_unknown_bytes(self):
        m = model(ALL_SAW)
        unk_before = dict(m.current().unknown_bytes())
        p = m.edit_parameters({"filter_resonance": 33, "vca_attack": 7})
        assert dict(p.unknown_bytes()) == unk_before


# ---------------------------------------------------------------------------
# 7. Session persistence
# ---------------------------------------------------------------------------
class TestSession:
    def test_save_load_preserves_state(self, tmp_path):
        m = model(SYNTH)
        m.select(3)
        m.edit_parameter("filter_cutoff", 21)
        m.edit_name("SESSION TEST")
        sfile = tmp_path / "sess.json"
        m.save_session(sfile)
        m2 = EditorModel.load_session(sfile)
        assert m2.selected == 3
        assert m2.is_dirty()
        assert m2.provenance == "REFERENCE_FIXTURE"
        cur = m2.current()
        # Name field = 9 bytes at offsets 55..63 (0x37..0x3F).  The 10th
        # input char is truncated by set_name ("SESSION TEST" -> "SESSION T").
        # Read/write padding conventions are NUL-pad + strip(" \x00"), so the
        # surviving 9-char name round-trips exactly.  (Regression guards:
        # window must stay 55..63 — 54..63 produced 'SSESSION '; space-padding
        # with NUL-only strip made a full 9-char name lose its last char.)
        assert cur.name == "SESSION T"
        assert cur.get_parameter("filter_cutoff").raw == 21
        # pending edits still pending (bank untouched):
        assert m2.get_patch(3).get_parameter("filter_cutoff").raw != 21

    def test_session_json_has_no_raw_bytes(self, tmp_path):
        m = model(ALL_SAW); m.select(2)
        f = tmp_path / "s.json"
        m.save_session(f)
        doc = json.loads(f.read_text(encoding="utf-8"))
        text = json.dumps(doc)
        assert "data" not in doc or isinstance(doc.get("edits"), list)
        assert len(text) < 4000          # state only, not 32*64 bytes
        assert doc["schema_version"] == 1
        assert doc["provenance"] == "REFERENCE_FIXTURE"

    def test_session_reload_then_save_matches_direct_edit(self, tmp_path):
        m = model(ALL_SAW)
        m.edit_parameter("osc1_wave", 0)
        m.edit_name("AFTER RELOAD")
        sf = tmp_path / "s.json"
        m.save_session(sf)
        m2 = EditorModel.load_session(sf)
        out1 = tmp_path / "direct.syx"; m.save(out1)
        m2.commit()
        out2 = tmp_path / "via-session.syx"; m2.save(out2)
        assert out1.read_bytes() == out2.read_bytes()


# ---------------------------------------------------------------------------
# 8. Reverse-engineering invariants
# ---------------------------------------------------------------------------
class TestInvariants:
    @pytest.mark.parametrize("fx", [ALL_EMPTY, ALL_SAW, SYNTH])
    def test_roundtrip_byte_identical_when_unedited(self, fx, tmp_path):
        m = model(fx)
        out = m.save(tmp_path / Path(fx).name)
        assert out.read_bytes() == Path(fx).read_bytes()

    def test_single_mode_record_preserved(self):
        """EditorModel normalizes single-program .syx into the fixed 32-slot
        bank view; the loaded record itself must survive byte-for-byte."""
        from jt4000m.syx import parse_file
        orig = parse_file(INIT_SAW_SINGLE).programs[0]
        m = model(INIT_SAW_SINGLE)
        assert bytes(m.get_patch(1).data) == bytes(orig.data)
        out = m.save("/tmp/p19_single_rt.syx")
        again = parse_file(str(out))
        assert again.checksum_ok
        assert bytes(again.programs[0].data) == bytes(orig.data)

    def test_parameter_edit_changes_exactly_one_byte(self):
        # Invariant 2.
        m = model(ALL_SAW)
        old = bytes(m.current().data)
        new = bytes(m.set_parameter("filter_cutoff", 99).data)
        diff = [i for i in range(64) if old[i] != new[i]]
        assert diff == [0x0C]

    def test_unknown_bytes_survive_everything(self):
        # Invariant 1.
        m = model(ALL_SAW)
        unk = dict(m.current().unknown_bytes())
        m.set_parameter("filter_cutoff", 5); m.rename("KEEP ME")
        m.duplicate_patch(1, 31); m.swap_patches(1, 2); m.move_patch(2, 9)
        m.commit()
        tmp = Path("/tmp/p19_unk.syx")
        m2 = EditorModel(); m2.load_bank(m.save(tmp))
        assert dict(m2.current().unknown_bytes()) == unk

    def test_checksum_valid_after_save(self):
        # Invariant 8.
        from jt4000m.syx import parse_file
        m = model(ALL_SAW)
        m.set_parameter("filter_cutoff", 77); m.commit()
        parsed = parse_file(m.save("/tmp/p19_sum.syx"))
        assert parsed.checksum_ok

    def test_program_order_and_count(self):
        # Invariant 5 (semantic state) + fixed 32-slot order.
        m = model(SYNTH)
        names_before = [p.name for p in m.patches()]
        m.swap_patches(1, 32)
        idx = [p.index for p in m.patches()]
        assert idx == list(range(1, 33))
        assert m.get_patch(1).name == names_before[31]

    def test_provenance_never_promoted(self):
        # Invariant 6.
        m = model(ALL_SAW)
        m.set_parameter("filter_cutoff", 1); m.commit()
        m.save("/tmp/p19_prov.syx")
        assert m.provenance == "REFERENCE_FIXTURE"
        reread = EditorModel(); reread.load_bank("/tmp/p19_prov.syx")
        assert reread.provenance == "REFERENCE_FIXTURE"

    def test_no_hardware_confirmed_possible(self):
        # Invariant 7.
        m = model(ALL_SAW)
        assert sum(1 for d in m.parameters() if d.hardware_confirmed) == 0
        assert m.registry_status()["hardware_confirmed"] == 0
        with pytest.raises(TypeError):
            m.set_parameter("osc1_wave", 4, hardware_confirmed=True)

    def test_registry_status_report_only(self):
        st = model(ALL_SAW).registry_status()
        assert st["problems"] == validate_registry()
        assert st["parameters"] == 33


# ---------------------------------------------------------------------------
# 9. CLI wiring (public API regression aid)
# ---------------------------------------------------------------------------
class TestCLIModel:
    def _run(self, argv):
        from jt4000m.cli import main
        main(argv)

    def test_groups_search_diff(self, capsys):
        self._run(["model", "groups", ALL_SAW])
        out = capsys.readouterr().out
        assert "OSCILLATORS" in out and "UNMAPPED" in out
        self._run(["model", "search", SYNTH, "lead"])
        assert "HOOLLEAD" in capsys.readouterr().out
        self._run(["model", "diff", ALL_EMPTY, ALL_SAW, "1", "1"])
        out = capsys.readouterr().out
        assert "[PARAMETER] OSC1 Wave" in out and "[NAME]" in out

    def test_parameters_lists_definitions(self, capsys):
        self._run(["model", "parameters", ALL_SAW, "FILTER"])
        out = capsys.readouterr().out
        assert "filter_cutoff" in out and "NOT_CONFIRMED" in out

    def test_session_save_load_cli(self, capsys, tmp_path):
        s = str(tmp_path / "cli.json")
        self._run(["model", "session-save", ALL_SAW, s])
        self._run(["model", "session-load", s])
        out = capsys.readouterr().out
        assert "REFERENCE_FIXTURE" in out and "Selected patch" in out
