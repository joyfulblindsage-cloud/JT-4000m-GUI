"""P0.1 regression suite: Program/Bank model + local SYX loading + 32-preset list.

These tests lock in the behaviour required by P0.1 and guard against parser or
model regressions (rule 20 of the project brief). They are pure-software
tests: no MIDI, no hardware, only local files under fixtures/.
"""
from pathlib import Path

import pytest

from jt4000m.model import (BY_KEY, ENUM_OPTIONS, decode_program, display_value,
                           editable_parameters, enum_options, reset_parameter,
                           set_name, set_parameter)
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
    # Highest confirmed enum value is writable; one above it is rejected both
    # by the enum table and by the spec range.
    max_confirmed = max(ENUM_OPTIONS["osc1_wave"])
    set_parameter(p, "osc1_wave", max_confirmed)  # boundary OK
    with pytest.raises(ValueError):
        set_parameter(p, "osc1_wave", max_confirmed + 1)
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


# --------------------------------------------------------------------------
# P0.2: offline preset editor for every confirmed parameter (model level).
# --------------------------------------------------------------------------

CONFIRMED_KEYS = [p.key for p in editable_parameters()]


def test_every_confirmed_parameter_is_editable():
    """All 31 offset-mapped parameters must be settable through the model."""
    p = parse_file(FIX / "ALL EMPTY.syx").programs[0]
    for spec in editable_parameters():
        if spec.kind == "enum":
            value = min(ENUM_OPTIONS[spec.key])  # a confirmed enum value
        else:
            value = spec.default
        q = set_parameter(p, spec.key, value)
        assert q.data[spec.offset] == value
        assert len(q.data) == 64


def test_cc_only_params_are_not_editable():
    p = parse_file(FIX / "ALL EMPTY.syx").programs[0]
    from jt4000m.model import PARAMETERS
    for spec in PARAMETERS:
        if spec.offset is None:
            with pytest.raises(ValueError):
                set_parameter(p, spec.key, 10)


def test_enum_write_rejects_unconfirmed_values():
    p = parse_file(FIX / "ALL EMPTY.syx").programs[0]
    for key in ("osc1_wave", "lfo1_wave", "lfo1_destination", "portamento_mode"):
        allowed = set(ENUM_OPTIONS[key])
        bad = next(v for v in range(128) if v not in allowed and v >= BY_KEY[key].minimum)
        with pytest.raises(ValueError):
            set_parameter(p, key, bad)


def test_ring_mod_toggle_uses_observed_zero_one_values():
    p = parse_file(FIX / "ALL EMPTY.syx").programs[0]
    off = BY_KEY["ring_mod_toggle"].offset
    assert set_parameter(p, "ring_mod_toggle", 0).data[off] == 0
    assert set_parameter(p, "ring_mod_toggle", 1).data[off] == 1
    with pytest.raises(ValueError):
        set_parameter(p, "ring_mod_toggle", 127)  # not an observed value


def test_display_value_semantics():
    assert display_value("osc1_wave", 4) == "SAW"
    assert display_value("osc2_wave", 0) == "OFF"
    assert display_value("osc1_coarse", 64) == "+0"
    assert display_value("osc1_coarse", 70) == "+6"
    assert display_value("filter_cutoff", 62) == "62"
    assert display_value("ring_mod_toggle", 0) == "OFF"
    assert display_value("ring_mod_toggle", 1) == "ON"
    # unconfirmed raw values never get invented names
    assert display_value("osc1_wave", 9) == "Unknown (0x09)"
    assert "Unknown (0x3F)" in display_value("ring_mod_toggle", 63)


def test_enum_options_only_confirmed_values():
    opts = dict(enum_options("osc1_wave"))
    assert opts == ENUM_OPTIONS["osc1_wave"]
    assert all(isinstance(k, int) and 0 <= k <= 127 for k in opts)
    # portamento mode: only OFF is established so far
    assert dict(enum_options("portamento_mode")) == {0: "OFF"}


def test_reset_parameter_restores_documented_default():
    p = parse_file(FIX / "ALL INIT SAW.syx").programs[0]
    q = set_parameter(p, "osc_balance", 100)
    r = reset_parameter(q, "osc_balance")
    assert r.data[BY_KEY["osc_balance"].offset] == BY_KEY["osc_balance"].default


def test_existing_banks_load_with_all_confirmed_params_readonly_safe():
    """Third-party banks may hold raw values outside our tables; loading and
    displaying them must never crash and must not rewrite anything."""
    for name in ("Synthmania-EDM-Soundset-JT-4000.syx", "ALL INIT SAW.syx",
                 "ALL EMPTY.syx"):
        bank = Bank.load(FIX / name)
        for prog in bank.programs:
            for spec in editable_parameters():
                raw = prog.data[spec.offset]
                disp = display_value(spec.key, raw)
                assert isinstance(disp, str) and disp != ""
        # round-trip stays byte-identical when nothing was edited
        assert bank.to_sysex() == (FIX / name).read_bytes()


def test_cli_still_shows_unknown_fields_for_raw_edits(tmp_path):
    """Editing known offsets must leave unknown bytes untouched."""
    bank = Bank.load(FIX / "ALL INIT SAW.syx")
    before = bytearray(bank.get(1).data)
    after = bytearray(bank.set_parameter(1, "filter_cutoff", 99).get(1).data)
    known = {p.offset for p in editable_parameters()} | set(range(55, 64))
    for i in range(64):
        if i not in known:
            assert before[i] == after[i], f"unknown byte {i:#x} changed"


# --------------------------------------------------------------------------
# P0.2 GUI editor: controls exist for every confirmed parameter and write
# through to the model. Skipped automatically without a display.
# --------------------------------------------------------------------------

@pytest.mark.skipif(not _HAS_DISPLAY, reason="no display available")
def test_gui_has_control_for_every_confirmed_parameter(editor):
    for spec in editable_parameters():
        assert spec.key in editor.vars, f"missing var for {spec.key}"
        assert spec.key in editor.value_vars, f"missing value label for {spec.key}"
        if spec.kind == "enum" and enum_options(spec.key):
            assert hasattr(editor, f"combo_{spec.key}"), f"missing dropdown for {spec.key}"


@pytest.mark.skipif(not _HAS_DISPLAY, reason="no display available")
def test_gui_enum_dropdown_shows_names_not_numbers(editor):
    combo = editor.combo_osc1_wave
    values = list(combo["values"])
    assert "SAW" in values and "OFF" in values
    assert not any(v.isdigit() for v in values)


@pytest.mark.skipif(not _HAS_DISPLAY, reason="no display available")
def test_gui_ring_mod_toggle_is_off_on_combo(editor):
    editor.load_path(FIX / "ALL INIT SAW.syx")
    editor.select_program(1)
    combo = editor.combo_ring_mod_toggle
    assert list(combo["values"]) == ["OFF", "ON"]
    assert combo.current() == 0  # raw 0 -> OFF
    combo.current(1)
    editor._combo_apply("ring_mod_toggle", combo)
    assert editor.bank.get(1).data[43] == 1
    assert editor.value_vars["ring_mod_toggle"].get() == "ON"


@pytest.mark.skipif(not _HAS_DISPLAY, reason="no display available")
def test_gui_slider_edit_writes_to_model(editor):
    editor.load_path(FIX / "ALL INIT SAW.syx")
    editor.select_program(2)
    editor.vars["vca_attack"].set(33)
    editor.apply_parameter("vca_attack")
    assert editor.bank.get(2).data[18] == 33
    assert editor.value_vars["vca_attack"].get() == "33"
    # unknown bytes untouched
    assert editor.bank.get(2).data[9:12] == (FIX / "ALL INIT SAW.syx").read_bytes()[8+64+9:8+64+12]


@pytest.mark.skipif(not _HAS_DISPLAY, reason="no display available")
def test_gui_rejects_unconfirmed_enum_value_from_model(editor):
    """Even if a widget somehow holds an unconfirmed raw value, apply fails
    loudly instead of writing invented data."""
    editor.load_path(FIX / "ALL INIT SAW.syx")
    editor.select_program(1)
    editor.vars["osc1_wave"].set(9)  # no such waveform established
    import tkinter.messagebox as mb
    orig = mb.showerror
    mb.showerror = lambda *a, **k: None
    try:
        editor.apply_parameter("osc1_wave")
    finally:
        mb.showerror = orig
    assert editor.bank.get(1).data[0] == 4  # unchanged (SAW)


@pytest.mark.skipif(not _HAS_DISPLAY, reason="no display available")
def test_gui_unknown_raw_value_shows_placeholder_not_wrong_option(editor):
    # Synthmania offset 0x2B uses 0/1 (fine); craft a bank byte with 9 via
    # model edit is impossible — so simulate by loading a program whose raw
    # osc value is out-of-table using the underlying bytes directly.
    from jt4000m.patch import JTProgram
    editor.load_path(FIX / "ALL EMPTY.syx")
    data = bytearray(editor.bank.get(1).data)
    data[0] = 9
    editor.bank = editor.bank.replace(1, JTProgram(1, bytes(data)))
    editor.select_program(1)
    assert editor.combo_osc1_wave.current() == -1
    assert editor.value_vars["osc1_wave"].get() == "Unknown (0x09)"


@pytest.mark.skipif(not _HAS_DISPLAY, reason="no display available")
def test_gui_reset_button_restores_default(editor):
    editor.load_path(FIX / "Synthmania-EDM-Soundset-JT-4000.syx")
    editor.select_program(1)
    before = editor.bank.get(1).data[8]
    editor.reset_one("osc_balance")
    after = editor.bank.get(1).data[8]
    assert after == BY_KEY["osc_balance"].default
    assert before != after or before == 64
    editor.undo()
    assert editor.bank.get(1).data[8] == before
