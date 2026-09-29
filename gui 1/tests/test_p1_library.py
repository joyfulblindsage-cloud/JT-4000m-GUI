"""P1 — Patch Library + Bank Editing regression tests.

Covers (per the P1 spec):
  * load a real 32-program bank;
  * round-trip load -> export -> load on ALL EMPTY / ALL INIT SAW / Synthmania;
  * unknown bytes preserved through every operation;
  * rename changes only Name[0..8];
  * duplicate produces an identical raw program;
  * swap preserves raw data of both slots;
  * move preserves all raw records (shift semantics);
  * parameter edit changes exactly one byte;
  * checksum valid after export (and recomputed only at export time);
  * dirty state clean/modified/clean-after-export;
  * undo/redo for rename, parameter edit, duplicate, swap, move, replace;
  * snapshot()/restore();
  * compare two programs and two banks via the existing diff code;
  * bulk vs single SysEx detection stays correct;
  * new `library` CLI subcommands are additive and old commands still work.

No MIDI is imported or exercised by these tests.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from jt4000m.diff import bank_diff, program_diff
from jt4000m.library import PatchLibrary
from jt4000m.model import BY_KEY, writable_parameters
from jt4000m.patch import Bank, JTProgram
from jt4000m.syx import FIELDS, parse, parse_file

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "fixtures"

BANKS = [
    FIX / "ALL EMPTY.syx",
    FIX / "ALL INIT SAW.syx",
    FIX / "Synthmania-EDM-Soundset-JT-4000.syx",
]


def _unknown_offsets() -> list[int]:
    """Offsets not covered by any mapped field; name bytes excluded."""
    return [o for o in range(64) if o not in FIELDS and not (55 <= o <= 63)]


# ---------------------------------------------------------------- loading
class TestLoading:
    @pytest.mark.parametrize("path", BANKS)
    def test_load_32_program_bank(self, path):
        lib = PatchLibrary.from_file(str(path))
        assert len(lib.bank.programs) == 32
        assert [p.index for p in lib.bank.programs] == list(range(1, 33))
        assert all(len(p.data) == 64 for p in lib.bank.programs)
        assert lib.path == str(path)
        assert not lib.dirty

    def test_single_dump_loads_as_full_bank(self):
        lib = PatchLibrary.from_file(str(FIX / "EMPTY.syx"))
        syx = parse_file(FIX / "EMPTY.syx")
        assert syx.mode == "single"
        assert len(lib.bank.programs) == 32  # padded bank, no invented data
        assert lib.bank.get(1).data == syx.programs[0].data

    def test_bulk_and_single_are_distinguished(self):
        assert parse_file(FIX / "ALL EMPTY.syx").mode == "bulk"
        assert parse_file(FIX / "EMPTY.syx").mode == "single"
        with pytest.raises(ValueError):
            Bank.from_sysex(parse_file(FIX / "EMPTY.syx"))


# ------------------------------------------------------------- round-trip
class TestRoundTrip:
    @pytest.mark.parametrize("path", BANKS)
    def test_export_unedited_is_byte_identical(self, path, tmp_path):
        original = path.read_bytes()
        lib = PatchLibrary.from_file(str(path))
        out = tmp_path / "out.syx"
        payload = lib.save_bank(str(out))
        assert payload == original
        assert out.read_bytes() == original
        assert not lib.dirty  # export marks clean

    @pytest.mark.parametrize("path", BANKS)
    def test_load_export_load_stable(self, path, tmp_path):
        lib1 = PatchLibrary.from_file(str(path))
        out = tmp_path / "rt.syx"
        lib1.save_bank(str(out))
        lib2 = PatchLibrary.from_file(str(out))
        assert [p.data for p in lib2.bank.programs] == [p.data for p in lib1.bank.programs]
        out2 = tmp_path / "rt2.syx"
        lib2.save_bank(str(out2))
        assert out2.read_bytes() == out.read_bytes()

    def test_checksum_recomputed_only_at_export(self, tmp_path):
        src = FIX / "ALL EMPTY.syx"
        lib = PatchLibrary.from_file(str(src))
        # In-memory: nothing was re-serialized yet, bank equals parsed source.
        assert lib.bank.to_sysex() == src.read_bytes()
        lib.rename(1, "CHECKSUM")
        out = tmp_path / "chk.syx"
        payload = lib.save_bank(str(out))
        syx = parse(payload)
        assert syx.checksum_ok
        assert payload[-2] != src.read_bytes()[-2] or payload[-2] == parse(payload).checksum_expected


# ------------------------------------------------------------ safety rules
class TestSafetyInvariants:
    def test_rename_changes_only_name_bytes(self):
        lib = PatchLibrary.from_file(str(FIX / "ALL INIT SAW.syx"))
        before = lib.get(3).data
        lib.rename(3, "MY PATCH")
        after = lib.get(3).data
        changed = [i for i in range(64) if before[i] != after[i]]
        assert changed and all(55 <= i <= 63 for i in changed)
        assert lib.get(3).name == "MY PATCH"
        # other slots untouched
        assert all(lib.get(i).data == Bank.load(FIX / "ALL INIT SAW.syx").get(i).data
                   for i in range(1, 33) if i != 3)

    def test_rename_pads_to_nine_bytes(self):
        lib = PatchLibrary.from_file(str(FIX / "ALL INIT SAW.syx"))
        lib.rename(1, "AB")
        raw = lib.get(1).data[55:64]
        assert raw == b"AB       "

    def test_parameter_edit_changes_exactly_one_byte(self):
        lib = PatchLibrary.from_file(str(FIX / "ALL EMPTY.syx"))
        original = lib.get(2).data
        lib.set_parameter(2, "osc1_wave", 4)  # SAW (established enum value)
        edited = lib.get(2).data
        diff = [i for i in range(64) if original[i] != edited[i]]
        assert diff == [BY_KEY["osc1_wave"].offset]
        assert edited[diff[0]] == 4

    def test_unknown_bytes_survive_edits_and_export(self, tmp_path):
        synth = FIX / "Synthmania-EDM-Soundset-JT-4000.syx"
        lib = PatchLibrary.from_file(str(synth))
        orig = Bank.load(synth)
        unknown = _unknown_offsets()
        assert unknown, "expected some unmapped offsets in the 64-byte record"
        lib.set_parameter(5, "filter_cutoff", 99)
        lib.rename(5, "UNKNOWNOK")
        out = tmp_path / "unk.syx"
        lib.save_bank(str(out))
        reloaded = Bank.load(out)
        for slot in range(1, 33):
            for off in unknown:
                assert reloaded.get(slot).data[off] == orig.get(slot).data[off], \
                    f"unknown byte lost at program {slot} offset 0x{off:02X}"

    def test_slot_order_preserved_by_all_operations(self):
        lib = PatchLibrary.from_file(str(FIX / "Synthmania-EDM-Soundset-JT-4000.syx"))
        lib.duplicate(1, 32)
        lib.swap(2, 7)
        lib.move(3, 10)
        assert [p.index for p in lib.bank.programs] == list(range(1, 33))
        assert all(len(p.data) == 64 for p in lib.bank.programs)

    def test_out_of_range_slots_rejected(self):
        lib = PatchLibrary.from_file(str(FIX / "ALL EMPTY.syx"))
        for bad in (0, 33, -1):
            with pytest.raises(IndexError):
                lib.get(bad)
            with pytest.raises(IndexError):
                lib.rename(bad, "X")


# ----------------------------------------------- duplicate / swap / move
class TestSlotOperations:
    def test_duplicate_produces_identical_raw_program(self):
        lib = PatchLibrary.from_file(str(FIX / "Synthmania-EDM-Soundset-JT-4000.syx"))
        src = lib.get(4).data
        lib.duplicate(4, 9)
        assert lib.get(9).data == src
        assert lib.get(9).index == 9  # re-slotted, raw bytes identical

    def test_swap_preserves_both_raw_records(self):
        lib = PatchLibrary.from_file(str(FIX / "Synthmania-EDM-Soundset-JT-4000.syx"))
        a, b = lib.get(1).data, lib.get(32).data
        lib.swap(1, 32)
        assert lib.get(1).data == b
        assert lib.get(32).data == a
        untouched = [lib.get(i).data for i in range(2, 32)]
        orig = Bank.load(FIX / "Synthmania-EDM-Soundset-JT-4000.syx")
        assert untouched == [orig.get(i).data for i in range(2, 32)]

    def test_move_shifts_without_losing_data(self):
        lib = PatchLibrary.from_file(str(FIX / "Synthmania-EDM-Soundset-JT-4000.syx"))
        orig = Bank.load(FIX / "Synthmania-EDM-Soundset-JT-4000.syx")
        lib.move(1, 3)
        datas = [lib.get(i).data for i in range(1, 33)]
        expected = [orig.get(2).data, orig.get(3).data, orig.get(1).data] \
                   + [orig.get(i).data for i in range(4, 33)]
        assert datas == expected
        # multiset of raw records unchanged
        assert sorted(datas) == sorted(orig.get(i).data for i in range(1, 33))

    def test_move_noop_does_not_dirty(self):
        lib = PatchLibrary.from_file(str(FIX / "ALL EMPTY.syx"))
        lib.move(5, 5)
        lib.swap(6, 6)
        assert not lib.dirty

    def test_replace_swaps_in_a_foreign_patch(self):
        lib = PatchLibrary.from_file(str(FIX / "ALL EMPTY.syx"))
        donor = Bank.load(FIX / "ALL INIT SAW.syx").get(1)
        lib.replace(10, donor)
        assert lib.get(10).data == donor.data
        assert lib.get(10).index == 10


# ---------------------------------------------------------------- compare
class TestCompare:
    def test_compare_identical_programs(self):
        lib = PatchLibrary.from_file(str(FIX / "ALL INIT SAW.syx"))
        assert lib.compare_programs(1, 2) == []

    def test_compare_programs_reports_semantic_fields(self):
        lib = PatchLibrary.from_file(str(FIX / "ALL EMPTY.syx"))
        lib.set_parameter(1, "osc1_wave", 4)
        rows = lib.compare_programs(1, 2)
        text = "\n".join(rows)
        assert "OSC1 Wave" in text
        assert "OFF" in text and "SAW" in text  # uses existing semantic map

    def test_compare_banks(self):
        a = PatchLibrary.from_file(str(FIX / "ALL EMPTY.syx"))
        b = PatchLibrary.from_file(str(FIX / "ALL INIT SAW.syx"))
        rows = a.compare_banks(b)
        assert rows
        assert all(r.startswith("P") for r in rows)

    def test_compare_helpers_accept_model_objects(self):
        ea = parse_file(FIX / "ALL EMPTY.syx")
        ib = parse_file(FIX / "ALL INIT SAW.syx")
        ds = bank_diff(ea, ib)
        assert ds
        pd = program_diff(Bank.load(FIX / "ALL INIT SAW.syx").get(1),
                          Bank.load(FIX / "ALL EMPTY.syx").get(1))
        assert any(d.field == "OSC1 Wave" for d in pd)


# ----------------------------------------------------------- dirty state
class TestDirtyState:
    def test_clean_after_load_modified_after_change_clean_after_export(self, tmp_path):
        lib = PatchLibrary.from_file(str(FIX / "ALL EMPTY.syx"))
        assert not lib.dirty
        lib.rename(1, "DIRTYTEST")
        assert lib.dirty
        out = tmp_path / "dirty.syx"
        lib.save_bank(str(out))
        assert not lib.dirty
        lib.set_parameter(2, "osc1_wave", 4)
        assert lib.dirty
        lib.undo()
        assert lib.dirty  # undo is itself a change relative to saved file

    def test_failed_export_keeps_dirty(self):
        lib = PatchLibrary.from_file(str(FIX / "ALL EMPTY.syx"))
        lib.rename(1, "STILLDIRTY")
        with pytest.raises(Exception):
            lib.save_bank("/nonexistent-dir-xyz/out.syx")
        assert lib.dirty

    def test_save_without_path_raises(self):
        lib = PatchLibrary(Bank.empty())
        with pytest.raises(ValueError):
            lib.save_bank()


# ------------------------------------------------------------- undo/redo
class TestUndoRedo:
    def _changed(self, lib, idx, key="osc1_wave", val=4):
        lib.set_parameter(idx, key, val)

    def test_undo_redo_parameter(self):
        lib = PatchLibrary.from_file(str(FIX / "ALL EMPTY.syx"))
        before = lib.get(1).data
        self._changed(lib, 1)
        assert lib.get(1).data != before
        assert lib.undo()
        assert lib.get(1).data == before
        assert lib.redo()
        assert lib.get(1).data != before

    @pytest.mark.parametrize("op", ["rename", "duplicate", "swap", "move", "replace"])
    def test_undo_restores_every_operation_kind(self, op):
        lib = PatchLibrary.from_file(str(FIX / "Synthmania-EDM-Soundset-JT-4000.syx"))
        snap = lib.snapshot()
        donor = Bank.load(FIX / "ALL INIT SAW.syx").get(1)
        if op == "rename":
            lib.rename(3, "UNDOTEST")
        elif op == "duplicate":
            lib.duplicate(3, 8)
        elif op == "swap":
            lib.swap(3, 8)
        elif op == "move":
            lib.move(3, 8)
        elif op == "replace":
            lib.replace(3, donor)
        assert lib.get(3).data != snap.bank.get(3).data or op == "duplicate"
        assert lib.undo()
        assert [p.data for p in lib.bank.programs] == [p.data for p in snap.bank.programs]

    def test_new_edit_clears_redo(self):
        lib = PatchLibrary.from_file(str(FIX / "ALL EMPTY.syx"))
        self._changed(lib, 1)
        lib.undo()
        assert lib.can_redo()
        self._changed(lib, 2)
        assert not lib.can_redo()

    def test_undo_on_empty_history_returns_false(self):
        lib = PatchLibrary.from_file(str(FIX / "ALL EMPTY.syx"))
        assert not lib.undo()
        assert not lib.redo()

    def test_history_limit(self):
        lib = PatchLibrary.from_file(str(FIX / "ALL EMPTY.syx"))
        for i in range(PatchLibrary.HISTORY_LIMIT + 25):
            lib.set_parameter(1, "osc1_wave", 0 if i % 2 else 4)
        assert len(lib._undo) == PatchLibrary.HISTORY_LIMIT


# ------------------------------------------------------ snapshot/restore
class TestSnapshotRestore:
    def test_snapshot_restore_round_trip(self):
        lib = PatchLibrary.from_file(str(FIX / "ALL INIT SAW.syx"))
        snap = lib.snapshot()
        lib.rename(2, "GONE")
        lib.swap(1, 32)
        lib.set_parameter(5, "filter_cutoff", 120)
        lib.restore(snap)
        assert [p.data for p in lib.bank.programs] == \
               [p.data for p in Bank.load(FIX / "ALL INIT SAW.syx").programs]
        assert lib.dirty  # restore is an explicit modification

    def test_restore_is_undoable(self):
        lib = PatchLibrary.from_file(str(FIX / "ALL INIT SAW.syx"))
        lib.rename(1, "BEFORE")
        snap = lib.snapshot()
        lib.rename(1, "AFTER")
        lib.restore(snap)
        assert lib.get(1).name == "BEFORE"
        lib.undo()
        assert lib.get(1).name == "AFTER"

    def test_snapshot_captures_selection(self):
        lib = PatchLibrary.from_file(str(FIX / "ALL EMPTY.syx"))
        lib.select(7)
        snap = lib.snapshot()
        lib.select(20)
        lib.restore(snap)
        assert lib.selected == 7


# ------------------------------------------------------------------- CLI
def run_cli(*argv):
    return subprocess.run([sys.executable, "-m", "jt4000m.cli", *argv],
                          cwd=ROOT, capture_output=True, text=True)


class TestLibraryCLI:
    def test_library_inspect(self):
        r = run_cli("library", "inspect", "fixtures/ALL INIT SAW.syx")
        assert r.returncode == 0, r.stderr
        assert "programs: 32" in r.stdout
        assert "checksum" in r.stdout

    def test_library_rename_dry_run_does_not_touch_file(self, tmp_path):
        src = FIX / "ALL EMPTY.syx"
        before = src.read_bytes()
        r = run_cli("library", "rename", "fixtures/ALL EMPTY.syx", "1", "MY PATCH")
        assert r.returncode == 0, r.stderr
        assert "dry run" in r.stdout
        assert src.read_bytes() == before

    def test_library_rename_with_output(self, tmp_path):
        out = tmp_path / "renamed.syx"
        r = run_cli("library", "rename", "fixtures/ALL EMPTY.syx", "1",
                    "MY PATCH", "--output", str(out))
        assert r.returncode == 0, r.stderr
        bank = Bank.load(out)
        assert bank.get(1).name == "MY PATCH"
        assert parse_file(out).checksum_ok

    def test_library_duplicate(self, tmp_path):
        out = tmp_path / "dup.syx"
        r = run_cli("library", "duplicate", "fixtures/Synthmania-EDM-Soundset-JT-4000.syx",
                    "1", "2", "--output", str(out))
        assert r.returncode == 0, r.stderr
        bank = Bank.load(out)
        assert bank.get(2).data == Bank.load(FIX / "Synthmania-EDM-Soundset-JT-4000.syx").get(1).data

    def test_library_swap(self, tmp_path):
        out = tmp_path / "swap.syx"
        r = run_cli("library", "swap", "fixtures/Synthmania-EDM-Soundset-JT-4000.syx",
                    "1", "2", "--output", str(out))
        assert r.returncode == 0, r.stderr
        orig = Bank.load(FIX / "Synthmania-EDM-Soundset-JT-4000.syx")
        bank = Bank.load(out)
        assert bank.get(1).data == orig.get(2).data
        assert bank.get(2).data == orig.get(1).data

    def test_library_export_roundtrip(self, tmp_path):
        out = tmp_path / "export.syx"
        r = run_cli("library", "export", "fixtures/ALL INIT SAW.syx", str(out))
        assert r.returncode == 0, r.stderr
        assert "re-parse: OK" in r.stdout
        assert out.read_bytes() == (FIX / "ALL INIT SAW.syx").read_bytes()

    def test_invalid_slot_rejected(self):
        r = run_cli("library", "rename", "fixtures/ALL EMPTY.syx", "33", "X")
        assert r.returncode != 0
        assert "1..32" in (r.stderr + r.stdout)

    @pytest.mark.parametrize("cmd", [
        ["inspect", "fixtures/ALL EMPTY.syx"],
        ["program", "fixtures/ALL INIT SAW.syx", "1"],
        ["diff", "fixtures/ALL EMPTY.syx", "fixtures/ALL INIT SAW.syx"],
        ["raw-diff", "fixtures/ALL EMPTY.syx", "fixtures/ALL INIT SAW.syx"],
        ["cross-bank", "fixtures/ALL EMPTY.syx", "fixtures/ALL INIT SAW.syx"],
        ["parameter-map"],
    ])
    def test_existing_commands_still_work(self, cmd):
        r = run_cli(*cmd)
        assert r.returncode == 0, r.stderr
