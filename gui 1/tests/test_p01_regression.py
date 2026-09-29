"""P0.1 regression suite: Program/Bank model + local SYX loading + 32-preset list.

These tests lock in the behaviour required by P0.1 and guard against parser or
model regressions (rule 20 of the project brief). They are pure-software
tests: no MIDI, no hardware, only local files under fixtures/.
"""
from pathlib import Path

import pytest

from jt4000m.model import BY_KEY, decode_program, set_name, set_parameter
from jt4000m.patch import Bank, JTProgram, program_to_single
from jt4000m.syx import (
    HEADER_PREFIX,
    Program,
    checksum,
    field_name,
    parse,
    parse_file,
    serialize_bulk,
    semantic_value,
)

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "fixtures"


# --------------------------------------------------------------------------
# Parser regression: format must not change silently.
# --------------------------------------------------------------------------

def test_empty_single_format_locked():
    s = parse_file(FIX / "EMPTY.syx")
    assert s.mode == "single"
    assert len(s.raw) == 75
    assert s.header == HEADER_PREFIX + bytes([0x15])
    assert s.reserved == b"\x00"
    assert s.checksum_value == 0x58 and s.checksum_ok
    assert len(s.programs) == 1 and len(s.programs[0].data) == 64
    assert s.programs[0].name == "EMPTY"


@pytest.mark.parametrize("name", ["ALL EMPTY.syx", "ALL INIT SAW.syx"])
def test_bulk_format_locked(name):
    s = parse_file(FIX / name)
    assert s.mode == "bulk"
    assert len(s.raw) == 8 + 32 * 64 + 2
    assert len(s.programs) == 32
    assert all(len(p.data) == 64 for p in s.programs)
    assert s.checksum_ok


def test_all_empty_bank_checksum_is_zero():
    s = parse_file(FIX / "ALL EMPTY.syx")
    assert s.checksum_value == 0x00


def test_synthmania_bank_loads_32_programs():
    s = parse_file(FIX / "Synthmania-EDM-Soundset-JT-4000.syx")
    assert s.mode == "bulk" and len(s.programs) == 32
    assert s.checksum_ok
    # Names exist and are non-empty for a commercial bank.
    names = [p.name for p in s.programs]
    assert all(n for n in names)
    assert len(set(names)) > 1


def test_parser_rejects_bad_input():
    with pytest.raises(ValueError):
        parse(b"\xf0\x00\x20\x32\x00\x01\x38\x10garbage\xf7")  # wrong length
    with pytest.raises(ValueError):
        parse(bytes(HEADER_PREFIX) + b"\x99" + bytes(2074) + b"\x00\xf7")  # unknown cmd
    with pytest.raises(ValueError):
        parse(b"F0 not a sysex at all")


# --------------------------------------------------------------------------
# Program-level regression: name parsing, 64-byte data, known offsets.
# --------------------------------------------------------------------------

def test_program_name_padding_and_truncation_field():
    s = parse_file(FIX / "ALL INIT SAW.syx")
    p = s.programs[0]
    assert p.data[55:64] == b"INIT SAW "  # 8 chars + space padding to 9
    assert p.name == "INIT SAW"


def test_known_offsets_init_saw():
    d = parse_file(FIX / "ALL INIT SAW.syx").programs[0].data
    assert d[0x00] == 4      # OSC1 Wave = SAW
    assert d[0x01] == 0      # OSC2 Wave = OFF
    assert semantic_value(0, d[0]) == "SAW"
    assert semantic_value(1, d[1]) == "OFF"


def test_program_byte_accessor():
    p = parse_file(FIX / "ALL INIT SAW.syx").programs[0]
    assert p.byte(0x0C) == p.data[12]


# --------------------------------------------------------------------------
# Model: get/set parameter, validation, name handling.
# --------------------------------------------------------------------------

def test_get_set_roundtrip_does_not_mutate_original():
    bank = Bank.load(str(FIX / "ALL INIT SAW.syx"))
    original = bank.get(1).data
    edited = bank.set_parameter(1, "filter_cutoff", 99)
    assert edited.get(1).data[12] == 99
    assert bank.get(1).data == original  # immutable copy-on-write


def test_range_validation():
    p = parse_file(FIX / "ALL INIT SAW.syx").programs[0]
    with pytest.raises(ValueError):
        set_parameter(p, "filter_cutoff", 128)
    with pytest.raises(ValueError):
        set_parameter(p, "filter_cutoff", -1)
    with pytest.raises(ValueError):
        set_parameter(p, "filter_cutoff", "64")  # type check


def test_enum_validation_matches_spec_range():
    p = parse_file(FIX / "ALL INIT SAW.syx").programs[0]
    spec = BY_KEY["osc1_wave"]
    set_parameter(p, "osc1_wave", spec.maximum)  # boundary OK
    with pytest.raises(ValueError):
        set_parameter(p, "osc1_wave", spec.maximum + 1)


def test_unknown_key_and_unmapped_key():
    p = parse_file(FIX / "ALL INIT SAW.syx").programs[0]
    with pytest.raises(KeyError):
        set_parameter(p, "no_such_param", 1)
    with pytest.raises(ValueError):  # CC-only params have no SysEx offset
        set_parameter(p, "modulation", 10)


def test_name_behaviour():
    p = parse_file(FIX / "ALL INIT SAW.syx").programs[0]
    # 9-char name fills the field exactly.
    assert set_name(p, "123456789").data[55:64] == b"123456789"
    # Longer names truncate to 9.
    assert set_name(p, "ABCDEFGHIJKLMNOP").name == "ABCDEFGHIJ"[:9]
    # Short names are space padded.
    assert set_name(p, "AB").data[55:64] == b"AB       "
    # Non-ASCII becomes '?' (never crashes, stays 7-bit safe).
    assert set_name(p, "BÄSS").data[55:64] == b"B?SS     "
    # Empty name clears the field.
    assert set_name(p, "").name == ""


def test_decode_program_keys_cover_mapped_parameters():
    p = parse_file(FIX / "ALL INIT SAW.syx").programs[0]
    d = decode_program(p)
    assert d["name"] == "INIT SAW"
    for key, spec in BY_KEY.items():
        if spec.offset is not None:
            assert d[key] == p.data[spec.offset]
            assert f"{key}_display" in d


# --------------------------------------------------------------------------
# Bank model: invariants + 32-program view used by the preset list.
# --------------------------------------------------------------------------

def test_bank_requires_exactly_32_programs():
    blank = bytes(64)
    with pytest.raises(ValueError):
        Bank(tuple(JTProgram(i, blank, 8 + (i - 1) * 64) for i in range(1, 32)))
    with pytest.raises(ValueError):  # wrong index sequence
        progs = [JTProgram(i, blank, 8 + (i - 1) * 64) for i in range(1, 33)]
        progs[5] = JTProgram(99, blank, 0)
        Bank(tuple(progs))
    with pytest.raises(ValueError):  # wrong record size
        progs = [JTProgram(i, blank, 8 + (i - 1) * 64) for i in range(1, 33)]
        progs[0] = JTProgram(1, bytes(63), 8)
        Bank(tuple(progs))


@pytest.mark.parametrize("name,expected_first", [
    ("ALL EMPTY.syx", "EMPTY"),
    ("ALL INIT SAW.syx", "INIT SAW"),
])
def test_bank_load_produces_32_slots_with_names(name, expected_first):
    bank = Bank.load(str(FIX / name))
    assert len(bank.programs) == 32
    assert [p.index for p in bank.programs] == list(range(1, 33))
    assert bank.get(1).name == expected_first
    assert all(len(p.data) == 64 for p in bank.programs)


def test_bank_get_bounds():
    bank = Bank.load(str(FIX / "ALL INIT SAW.syx"))
    with pytest.raises(IndexError):
        bank.get(0)
    with pytest.raises(IndexError):
        bank.get(33)


def test_bank_from_sysex_rejects_single():
    s = parse_file(FIX / "EMPTY.syx")
    with pytest.raises(ValueError, match="bulk"):
        Bank.from_sysex(s)


def test_bank_load_single_places_program_in_own_slot():
    s = parse_file(FIX / "EMPTY.syx")
    slot = s.programs[0].index  # single dumps carry their own program number
    bank = Bank.load(str(FIX / "EMPTY.syx"))
    assert len(bank.programs) == 32
    assert bank.get(slot).data == s.programs[0].data
    assert bank.get(slot).name == "EMPTY"


def test_bank_save_reload_is_lossless(tmp_path):
    src = FIX / "Synthmania-EDM-Soundset-JT-4000.syx"
    bank = Bank.load(str(src))
    out = tmp_path / "roundtrip.syx"
    out.write_bytes(bank.to_sysex())
    reloaded = Bank.load(str(out))
    assert [p.data for p in reloaded.programs] == [p.data for p in bank.programs]
    assert out.read_bytes() == src.read_bytes()  # byte-for-byte identical


def test_bank_edit_preserves_unknown_bytes_and_fixes_checksum():
    bank = Bank.load(str(FIX / "ALL INIT SAW.syx"))
    edited = bank.set_parameter(2, "vca_attack", 100).set_name(2, "EDITED")
    blob = edited.to_sysex()
    reparsed = parse(blob)
    assert reparsed.checksum_ok
    assert reparsed.programs[1].data[0x12] == 100
    assert reparsed.programs[1].name == "EDITED"
    untouched = parse_file(FIX / "ALL INIT SAW.syx").programs[1].data
    for off in range(64):
        if off not in (0x12, *range(55, 64)):
            assert reparsed.programs[1].data[off] == untouched[off]


def test_copy_duplicate_and_empty_bank():
    bank = Bank.load(str(FIX / "ALL INIT SAW.syx"))
    copied = bank.copy_program(1, 5)
    assert copied.get(5).data == bank.get(1).data
    assert copied.get(5).source_offset == bank.get(5).source_offset  # slot kept
    empty = Bank.empty()
    assert len(empty.programs) == 32
    assert all(p.data == bytes(64) for p in empty.programs)


def test_program_to_single_export_valid():
    p = Bank.load(str(FIX / "ALL INIT SAW.syx")).get(1)
    blob = program_to_single(p)
    s = parse(blob)
    assert s.mode == "single" and s.checksum_ok
    assert s.programs[0].data == p.data


# --------------------------------------------------------------------------
# CLI smoke regression (backward compatibility, rule 17/26).
# --------------------------------------------------------------------------

def _run_cli(capsys, *argv):
    from jt4000m.cli import main
    main(list(argv))
    return capsys.readouterr().out


def test_cli_inspect_bulk(tmp_path, capsys):
    out = _run_cli(capsys, "inspect", str(FIX / "ALL EMPTY.syx"))
    assert "mode: bulk" in out and "programs: 32" in out
    assert "checksum: 0x00 (OK" in out


def test_cli_inspect_single_and_synthmania(capsys):
    out = _run_cli(capsys, "inspect", str(FIX / "EMPTY.syx"))
    assert "mode: single" in out and "programs: 1" in out
    out = _run_cli(capsys, "inspect", str(FIX / "Synthmania-EDM-Soundset-JT-4000.syx"))
    assert "programs: 32" in out


def test_cli_program_shows_known_and_unknown_fields(capsys):
    out = _run_cli(capsys, "program", str(FIX / "ALL INIT SAW.syx"), "1")
    assert "OSC1 Wave" in out
    assert "Byte 0x09" in out  # unknown offsets stay Unknown/Byte, never invented
    assert "Name[0]" in out


def test_cli_diff_smoke(capsys):
    out = _run_cli(capsys, "diff", str(FIX / "ALL EMPTY.syx"), str(FIX / "ALL INIT SAW.syx"))
    assert "OSC1 Wave" in out and "SAW" in out


# --------------------------------------------------------------------------
# GUI: stable construction + 32-slot list + offline load (not fragile).
# Skipped automatically when no display is available.
# --------------------------------------------------------------------------

tk = pytest.importorskip("tkinter")

try:
    _probe = tk.Tk()
    _probe.destroy()
    _HAS_DISPLAY = True
except tk.TclError:
    _HAS_DISPLAY = False

pytestmark_gui = pytest.mark.skipif(not _HAS_DISPLAY, reason="no display available")


@pytest.fixture()
def editor():
    from jt4000m.gui import Editor
    app = Editor()
    yield app
    app.destroy()


@pytest.mark.skipif(not _HAS_DISPLAY, reason="no display available")
def test_gui_starts_without_midi(editor):
    # GUI module must never pull in MIDI I/O.
    import sys
    assert "jt4000m.midi_winmm" not in sys.modules
    assert editor.bank is None  # starts empty, no crash


@pytest.mark.skipif(not _HAS_DISPLAY, reason="no display available")
def test_gui_loads_bank_and_lists_32_presets(editor):
    editor.load_path(FIX / "ALL INIT SAW.syx")
    assert editor.bank is not None and len(editor.bank.programs) == 32
    assert editor.listbox.size() == 32
    items = list(editor.listbox.get(0, "end"))
    assert items[0].startswith("01") and "INIT SAW" in items[0]
    assert items[31].startswith("32")
    # Selecting a preset syncs the model into the widgets.
    editor.select_program(7)
    assert editor.selected_index == 7
    assert editor.vars["osc1_wave"].get() == 4


@pytest.mark.skipif(not _HAS_DISPLAY, reason="no display available")
def test_gui_edit_updates_model_and_modified_flag(editor):
    editor.load_path(FIX / "ALL INIT SAW.syx")
    editor.select_program(1)
    assert editor.modified_var.get() == ""
    editor.vars["filter_cutoff"].set(64)
    editor.apply_parameter("filter_cutoff")
    assert editor.bank.get(1).data[12] == 64
    assert "Modified" in editor.modified_var.get()
