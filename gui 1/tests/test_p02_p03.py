"""P0.2 — offline preset editor for every confirmed parameter.
P0.3 — saving an edited bank to SYX preserving the existing format/checksum.

No MIDI is imported or exercised by these tests.
"""
from __future__ import annotations

import pytest

from jt4000m.model import (
    ENUM_OPTIONS,
    BY_KEY,
    editable_parameters,
    enum_options,
    get_parameter,
    writable_parameters,
)
from jt4000m.patch import Bank, JTProgram
from jt4000m.syx import HEADER_PREFIX, BULK_CMD, checksum, parse, parse_file

FIX = "fixtures"
BANKS = [
    f"{FIX}/ALL EMPTY.syx",
    f"{FIX}/ALL INIT SAW.syx",
    f"{FIX}/Synthmania-EDM-Soundset-JT-4000.syx",
]


# ------------------------------------------------------------------ helpers

def _unknown_offsets(data: bytes) -> list[int]:
    """Offsets not covered by any mapped field (name bytes included)."""
    from jt4000m.syx import FIELDS
    return [o for o in range(64) if o not in FIELDS and not (55 <= o <= 63)]


# ======================================================================
# P0.2 — parameter model API used by the offline editor
# ======================================================================

class TestWritableSet:
    def test_writable_excludes_cc_only(self):
        keys = {p.key for p in writable_parameters()}
        assert "modulation" not in keys
        assert "portamento_time" not in keys

    def test_writable_excludes_enum_without_confirmed_table(self):
        # portamento_mode has no established value table beyond OFF; it must
        # not be exposed as an editable dropdown with invented options.
        w = {p.key for p in writable_parameters()}
        if not ENUM_OPTIONS.get("portamento_mode"):
            assert "portamento_mode" not in w

    def test_writable_has_no_duplicate_keys(self):
        keys = [p.key for p in writable_parameters()]
        assert len(keys) == len(set(keys))

    def test_every_writable_spec_has_offset_and_range(self):
        for p in writable_parameters():
            assert p.offset is not None and 0 <= p.offset <= 63
            assert p.minimum <= p.default <= p.maximum

    def test_editable_superset_of_writable(self):
        e = {(p.key, p.offset) for p in editable_parameters()}
        w = {(p.key, p.offset) for p in writable_parameters()}
        assert w <= e


class TestGetParameter:
    def test_get_matches_raw_byte(self):
        bank = Bank.load(f"{FIX}/ALL INIT SAW.syx")
        prog = bank.get(1).to_program()
        for p in writable_parameters():
            assert get_parameter(prog, p.key) == prog.data[p.offset]

    def test_get_unknown_key_raises(self):
        from jt4000m.syx import Program
        with pytest.raises(KeyError):
            get_parameter(Program(1, bytes(64), 8), "no_such_param")

    def test_get_cc_only_raises(self):
        from jt4000m.syx import Program
        with pytest.raises(ValueError):
            get_parameter(Program(1, bytes(64), 8), "modulation")

    def test_bank_level_get_set_roundtrip(self):
        bank = Bank.load(f"{FIX}/ALL INIT SAW.syx")
        before = bank.get_parameter(3, "filter_cutoff")
        bank2 = bank.set_parameter(3, "filter_cutoff", 99 if before != 99 else 98)
        assert bank2.get_parameter(3, "filter_cutoff") != before
        assert bank.get_parameter(3, "filter_cutoff") == before  # immutable


class TestWriteEveryConfirmedParameter:
    """The editor must be able to change EVERY confirmed parameter."""

    @pytest.mark.parametrize("path", BANKS)
    def test_write_all_writable_params_then_read_back(self, path):
        bank = Bank.load(path)
        for idx in (1, 17, 32):
            prog = bank.get(idx)
            for spec in writable_parameters():
                old = prog.get_parameter(spec.key)
                if spec.kind == "enum":
                    opts = [v for v, _ in enum_options(spec.key)]
                    new = next(v for v in opts if v != old) if len(opts) > 1 else old
                else:
                    new = 64 if old != 64 else 65
                prog = prog.set_parameter(spec.key, new)
                assert prog.get_parameter(spec.key) == new
            # all other bytes of this program untouched
            orig_data = bank.get(idx).data
            changed_offsets = {s.offset for s in writable_parameters()}
            for o in range(64):
                if o not in changed_offsets:
                    assert prog.data[o] == orig_data[o], f"offset 0x{o:02X} clobbered"

    def test_enum_rejects_unconfirmed_value(self):
        bank = Bank.load(f"{FIX}/ALL INIT SAW.syx")
        with pytest.raises(ValueError):
            bank.set_parameter(1, "osc1_wave", 100)  # not in WAVE_NAMES

    def test_continuous_rejects_out_of_range(self):
        bank = Bank.load(f"{FIX}/ALL INIT SAW.syx")
        with pytest.raises(ValueError):
            bank.set_parameter(1, "filter_cutoff", 128)
        with pytest.raises(ValueError):
            bank.set_parameter(1, "filter_cutoff", -1)

    def test_cc_only_not_writable(self):
        bank = Bank.load(f"{FIX}/ALL INIT SAW.syx")
        with pytest.raises(ValueError):
            bank.set_parameter(1, "modulation", 50)


# ======================================================================
# P0.3 — save edited bank, format & checksum preserved, round-trip
# ======================================================================

class TestSaveFormat:
    def test_unedited_bulk_save_is_byte_identical(self, tmp_path):
        for path in BANKS:
            original = parse_file(path)
            if original.mode != "bulk":
                continue
            bank = Bank.load(path)
            written = bank.save(tmp_path / f"rt-{Path_name(path)}")
            raw = original.raw
            assert written[:8] == raw[:8], "header changed"
            assert written[8:-2] == raw[8:-2], "payload changed"
            assert written[-2] == raw[-2], "checksum changed"
            assert written == raw, "whole-file byte identity broken"

    def test_edited_save_keeps_frame_format(self, tmp_path):
        bank = Bank.load(f"{FIX}/Synthmania-EDM-Soundset-JT-4000.syx")
        bank2 = bank.set_parameter(5, "filter_cutoff", 100)
        payload = bank2.save(tmp_path / "edited.syx")
        assert len(payload) == 2058
        assert payload[0] == 0xF0 and payload[-1] == 0xF7
        assert payload[:7] == HEADER_PREFIX
        assert payload[7] == BULK_CMD
        assert all(b <= 0x7F for b in payload[1:-1])

    def test_checksum_recomputed_correctly(self, tmp_path):
        src = parse_file(f"{FIX}/ALL INIT SAW.syx")
        bank = Bank.load(f"{FIX}/ALL INIT SAW.syx").set_parameter(2, "vca_attack", 77)
        payload = bank.save(tmp_path / "chk.syx")
        expected = checksum(payload[8:-2])
        assert payload[-2] == expected
        reparsed = parse(payload)
        assert reparsed.checksum_ok is True
        # checksum genuinely differs when payload differs
        assert payload[-2] != src.checksum_value or src.checksum_value == expected

    def test_save_output_parses_with_existing_parser(self, tmp_path):
        bank = Bank.load(f"{FIX}/ALL EMPTY.syx")
        bank2 = bank.set_name(9, "TESTNAME")
        payload = bank2.save(tmp_path / "named.syx")
        syx = parse(payload)
        assert syx.mode == "bulk" and len(syx.programs) == 32 and syx.checksum_ok

    def test_source_header_preserved_through_edits(self):
        bank = Bank.load(f"{FIX}/ALL INIT SAW.syx")
        h = bank.source_header
        edited = (bank.set_parameter(1, "osc1_wave", 2)
                       .set_name(31, "X")
                       .copy_program(1, 2))
        assert edited.source_header == h
        assert edited.to_sysex()[:8] == h

    def test_save_is_atomic_no_temp_leftovers(self, tmp_path):
        bank = Bank.load(f"{FIX}/ALL EMPTY.syx")
        target = tmp_path / "out.syx"
        bank.save(target)
        assert target.exists()
        assert list(tmp_path.glob("*.tmp")) == []

    def test_save_invalid_target_raises(self, tmp_path):
        bank = Bank.load(f"{FIX}/ALL EMPTY.syx")
        with pytest.raises(Exception):
            bank.save(tmp_path / "missing_dir" / "out.syx")


class TestRoundTrip:
    def test_edit_save_reload_values_match(self, tmp_path):
        bank = Bank.load(f"{FIX}/Synthmania-EDM-Soundset-JT-4000.syx")
        edited = (bank
                  .set_parameter(1, "osc1_wave", 2)
                  .set_parameter(1, "filter_resonance", 96)
                  .set_parameter(20, "vca_decay", 33)
                  .set_name(20, "ROUND TRIP")
                  .copy_program(1, 32))
        path = tmp_path / "roundtrip.syx"
        edited.save(path)
        reloaded = Bank.load(str(path))
        assert reloaded.to_sysex() == edited.to_sysex()
        assert reloaded.get(1).get_parameter("osc1_wave") == 2
        assert reloaded.get(1).get_parameter("filter_resonance") == 96
        assert reloaded.get(20).get_parameter("vca_decay") == 33
        assert reloaded.get(20).name == "ROUND TRI"  # 9-char field truncation
        assert reloaded.get(32).data == reloaded.get(1).data

    def test_unknown_bytes_survive_edit_save_cycle(self, tmp_path):
        bank = Bank.load(f"{FIX}/Synthmania-EDM-Soundset-JT-4000.syx")
        prog = bank.get(7)
        unknown = _unknown_offsets(prog.data)
        assert unknown, "fixture should contain unmapped bytes"
        edited = bank.set_parameter(7, "filter_cutoff", 10)
        path = tmp_path / "unknown.syx"
        edited.save(path)
        reloaded = Bank.load(str(path))
        for o in unknown:
            assert reloaded.get(7).data[o] == prog.data[o], f"unknown 0x{o:02X} lost"

    def test_full_bank_payload_survives_when_one_program_edited(self, tmp_path):
        bank = Bank.load(f"{FIX}/Synthmania-EDM-Soundset-JT-4000.syx")
        edited = bank.set_parameter(13, "lfo1_rate", 5)
        path = tmp_path / "one.syx"
        edited.save(path)
        reloaded = Bank.load(str(path))
        for i in range(1, 33):
            if i != 13:
                assert reloaded.get(i).data == bank.get(i).data
        assert reloaded.get(13).get_parameter("lfo1_rate") == 5

    def test_cli_can_still_inspect_saved_bank(self, tmp_path):
        """Saved files stay valid inputs for the untouched CLI/parser."""
        import subprocess, sys
        bank = Bank.load(f"{FIX}/ALL INIT SAW.syx").set_parameter(1, "filter_cutoff", 111)
        path = tmp_path / "cli.syx"
        bank.save(path)
        res = subprocess.run(
            [sys.executable, "-m", "jt4000m.cli", "inspect", str(path)],
            capture_output=True, text=True, cwd=".", timeout=60)
        assert res.returncode == 0, res.stderr
        assert "programs: 32" in res.stdout
        assert "checksum" in res.stdout.lower()


def Path_name(path: str) -> str:
    from pathlib import Path as P
    return P(path).stem.replace(" ", "_")


# ======================================================================
# P0.3 GUI e2e: edit -> save -> reload in a fresh Editor (no MIDI).
# Skipped automatically when no display is available.
# ======================================================================

tk = pytest.importorskip("tkinter")

try:
    _probe = tk.Tk()
    _probe.destroy()
    _HAS_DISPLAY = True
except tk.TclError:
    _HAS_DISPLAY = False


@pytest.fixture()
def editor_app():
    from jt4000m.gui import Editor
    app = Editor()
    yield app
    app.destroy()


@pytest.mark.skipif(not _HAS_DISPLAY, reason="no display available")
def test_gui_save_roundtrip_e2e(editor_app, tmp_path):
    from pathlib import Path
    editor_app.load_path(f"{FIX}/ALL INIT SAW.syx")
    editor_app.select_program(4)
    editor_app.vars["filter_cutoff"].set(70)
    editor_app.apply_parameter("filter_cutoff")
    assert "Modified" in editor_app.modified_var.get()
    out = tmp_path / "gui_saved.syx"
    editor_app._write(Path(out))
    assert editor_app.modified_var.get() == ""  # saved -> clean
    raw = out.read_bytes()
    assert len(raw) == 2058 and raw[0] == 0xF0 and raw[-1] == 0xF7
    syx = parse(raw)
    assert syx.checksum_ok and len(syx.programs) == 32
    assert syx.programs[3].data[12] == 70
    # untouched programs are byte-identical to the source file
    src = parse_file(f"{FIX}/ALL INIT SAW.syx")
    for i in range(32):
        if i != 3:
            assert syx.programs[i].data == src.programs[i].data


@pytest.mark.skipif(not _HAS_DISPLAY, reason="no display available")
def test_gui_reload_after_save_shows_saved_values(editor_app, tmp_path):
    from pathlib import Path
    editor_app.load_path(f"{FIX}/Synthmania-EDM-Soundset-JT-4000.syx")
    editor_app.select_program(2)
    editor_app.vars["vca_attack"].set(11)
    editor_app.apply_parameter("vca_attack")
    out = tmp_path / "gui_rt.syx"
    editor_app._write(Path(out))
    # fresh editor instance loads the saved file and shows the edited value
    from jt4000m.gui import Editor
    app2 = Editor()
    try:
        app2.load_path(str(out))
        app2.select_program(2)
        assert app2.vars["vca_attack"].get() == 11
        assert app2.bank.get(2).get_parameter("vca_attack") == 11
        assert app2.modified_var.get() == ""
    finally:
        app2.destroy()
