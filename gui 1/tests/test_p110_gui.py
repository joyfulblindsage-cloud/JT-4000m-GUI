"""P1.10 — GUI foundation tests: the Tkinter editor must be a thin
presentation layer over EditorModel / EditorHistory.

Vertical slice contract (§14):

    load → 32 patches → select → edit → MODIFIED → undo → CLEAN
        → redo → MODIFIED → save → CLEAN → reload → state preserved

GUI tests touch the app ONLY through public model APIs and widget event
handlers (apply_parameter / apply_name / undo / redo / _write).  Raw-byte
assertions live at the model/parser level, never inside the GUI code path.
"""
from __future__ import annotations

import pytest

from pathlib import Path

FIX = Path(__file__).resolve().parents[1]

tk = pytest.importorskip("tkinter")

try:
    _probe = tk.Tk()
    _probe.destroy()
    _HAS_DISPLAY = True
except tk.TclError:
    _HAS_DISPLAY = False

gui_test = pytest.mark.skipif(not _HAS_DISPLAY, reason="no display available")

from jt4000m.model import BY_KEY                       # noqa: E402
from jt4000m.syx import parse, parse_file               # noqa: E402


@pytest.fixture()
def app():
    from jt4000m.gui import Editor
    a = Editor()
    yield a
    a.destroy()


@pytest.fixture()
def quiet(monkeypatch):
    """Silence modal dialogs; record that an error dialog was raised."""
    from tkinter import messagebox as mb
    shown = []
    monkeypatch.setattr(mb, "showerror",
                        lambda *a, **k: shown.append(a))
    monkeypatch.setattr(mb, "showinfo", lambda *a, **k: None)
    return shown


# --------------------------------------------------------------- §14 slice
@gui_test
def test_vertical_slice_full_cycle(app, tmp_path):
    src = FIX / "ALL INIT SAW.syx"
    app.load_path(src)

    # 32 patches visible, listbox in sync with the model
    assert app.listbox.size() == 32
    assert len(app.editor.patches()) == 32

    # select patch 5 through the GUI path -> model selection follows
    app.select_program(5)
    assert app.editor.selected == 5
    assert app.selected_index == 5

    # load -> CLEAN
    assert not app.editor.is_dirty()
    assert app.modified_var.get() == ""

    # baseline fixture value must differ from our edit target
    key, new_raw = "filter_resonance", 99
    old_raw = app.editor.get_patch(5).get_raw(key)
    assert old_raw != new_raw

    # edit known parameter -> MODIFIED
    app.vars[key].set(new_raw)
    app.apply_parameter(key)
    assert app.editor.bank.get(5).get_parameter(key) == new_raw
    assert app.editor.is_dirty()
    assert "Modified" in app.modified_var.get()

    # undo -> CLEAN (back to exact loaded baseline)
    app.undo()
    assert app.editor.bank.get(5).get_parameter(key) == old_raw
    assert not app.editor.is_dirty()
    assert app.modified_var.get() == ""

    # redo -> MODIFIED again
    app.redo()
    assert app.editor.bank.get(5).get_parameter(key) == new_raw
    assert app.editor.is_dirty()
    assert "Modified" in app.modified_var.get()

    # save -> CLEAN (checksum/baseline handled by model+serializer)
    out = tmp_path / "slice.syx"
    app._write(out)
    assert not app.editor.is_dirty()
    assert app.modified_var.get() == ""

    # reload -> edited state survives, fresh session is CLEAN
    app.load_path(out)
    app.select_program(5)
    assert app.editor.get_patch(5).get_raw(key) == new_raw
    assert not app.editor.is_dirty()
    assert app.modified_var.get() == ""


# ----------------------------------------------------------------- §15 name
@gui_test
def test_rename_short_name_roundtrip(app, tmp_path, quiet):
    app.load_path(FIX / "ALL INIT SAW.syx")
    app.select_program(3)
    app.name_var.set("TEST")
    app.apply_name()
    assert app.editor.get_patch(3).name == "TEST"
    assert app.editor.is_dirty()
    out = tmp_path / "renamed.syx"
    app._write(out)
    syx = parse(out.read_bytes())
    assert syx.checksum_ok
    assert syx.programs[2].name == "TEST"
    # reload through the GUI shows exactly the model name
    app.load_path(out)
    app.select_program(3)
    assert app.name_var.get() == "TEST"
    assert app.editor.get_patch(3).name == app.name_var.get()


@gui_test
def test_rename_truncates_to_nine_chars(app, quiet):
    """Contract: max 9 bytes/chars, longer names truncate; byte 54 and all
    bytes outside 55..63 stay untouched (checked at MODEL level — the GUI
    itself knows nothing about offsets)."""
    app.load_path(FIX / "ALL INIT SAW.syx")
    app.select_program(1)
    before = bytes(app.editor.get_patch(1).data)

    app.name_var.set("1234567890")            # 10 chars
    app.apply_name()
    assert not quiet                          # no error dialog expected
    after = bytes(app.editor.get_patch(1).data)
    assert app.editor.get_patch(1).name == "123456789"
    changed = [i for i in range(len(before)) if before[i] != after[i]]
    assert changed and all(55 <= i <= 63 for i in changed), \
        f"rename touched offsets outside 55..63: {changed}"
    assert after[54] == before[54] == 0x00    # structural byte preserved


@gui_test
def test_rename_undo_redo(app):
    app.load_path(FIX / "Synthmania-EDM-Soundset-JT-4000.syx")
    app.select_program(1)
    original = app.editor.get_patch(1).name
    app.name_var.set("SLOT SEVEN")
    app.apply_name()
    # 10 chars truncate to the exact 9-byte field capacity (documented
    # contract, see model.set_name / test_p19_api / test_p110_history)
    assert app.editor.get_patch(1).name == "SLOT SEVE"
    app.undo()
    assert app.editor.get_patch(1).name == original
    assert not app.editor.is_dirty()
    app.redo()
    assert app.editor.get_patch(1).name == "SLOT SEVE"    # truncated form
    assert app.editor.is_dirty()


# ------------------------------------------- §16 fixture integration cycle
@pytest.mark.parametrize("fname", [
    "ALL EMPTY.syx",
    "ALL INIT SAW.syx",
    "Synthmania-EDM-Soundset-JT-4000.syx",
])
@gui_test
def test_fixture_integration_cycle(app, tmp_path, fname):
    src = FIX / fname
    original_bytes = src.read_bytes()
    app.load_path(src)
    assert len(app.editor.patches()) == 32
    assert not app.editor.is_dirty()

    app.select_program(2)
    key = "filter_cutoff"
    old = app.editor.get_patch(2).get_raw(key)
    new = 42 if old != 42 else 43
    app.vars[key].set(new)
    app.apply_parameter(key)
    assert app.editor.is_dirty()

    app.undo()
    assert app.editor.get_patch(2).get_raw(key) == old
    app.redo()
    assert app.editor.get_patch(2).get_raw(key) == new

    app.name_var.set("GUIEDIT")
    app.apply_name()

    out = tmp_path / f"saved_{fname}"
    app._write(out)
    assert not app.editor.is_dirty()

    # ---- reload & verify at parser/model level --------------------------
    saved = out.read_bytes()
    syx = parse(saved)
    assert syx.checksum_ok
    assert len(syx.programs) == 32
    src_syx = parse(original_bytes)
    assert [p.index for p in syx.programs] == [p.index for p in src_syx.programs]

    prog2 = syx.programs[1]
    assert prog2.data[BY_KEY[key].offset] == new          # known param changed
    assert prog2.name == "GUIEDIT"                        # name changed
    assert prog2.data[54] == src_syx.programs[1].data[54] == 0x00

    # every program except slot 2 must be byte-identical to the source
    for i in range(32):
        if i != 1:
            assert syx.programs[i].data == src_syx.programs[i].data

    # unknown bytes of the edited program are preserved
    unk_before = dict((o, b) for o, b in enumerate(src_syx.programs[1].data)
                      if o not in set(BY_KEY[k].offset for k in BY_KEY
                                      if BY_KEY[k].offset is not None)
                      and not (55 <= o <= 63))
    unk_after = dict((o, b) for o, b in enumerate(prog2.data)
                     if o not in set(BY_KEY[k].offset for k in BY_KEY
                                     if BY_KEY[k].offset is not None)
                     and not (55 <= o <= 63))
    unk_before.pop(BY_KEY[key].offset, None)
    unk_after.pop(BY_KEY[key].offset, None)
    assert unk_before == unk_after


# -------------------------------------------------- §17 byte-level safety
@gui_test
def test_parameter_edit_changes_only_its_byte(app, quiet):
    app.load_path(FIX / "ALL INIT SAW.syx")
    app.select_program(1)
    spec = BY_KEY["vca_attack"]
    before = bytes(app.editor.get_patch(1).data)
    new = 23 if before[spec.offset] != 23 else 24
    app.vars["vca_attack"].set(new)
    app.apply_parameter("vca_attack")
    after = bytes(app.editor.get_patch(1).data)
    changed = [i for i in range(64) if before[i] != after[i]]
    assert changed == [spec.offset]


@gui_test
def test_duplicate_swap_move_via_model_and_undo(app):
    """P1.15 corrective contract: dirty reflects STATE CHANGE, not the fact
    a mutation method was called.  ALL INIT SAW has byte-identical slots, so
    duplicate(1->2)/swap(1,3) there are genuine no-ops and must NOT flip
    dirty.  To exercise the real mutation + undo path we use Synthmania,
    whose slots differ."""
    app.load_path(FIX / "Synthmania-EDM-Soundset-JT-4000.syx")
    app.select_program(1)
    pre = {i: bytes(app.editor.get_patch(i).data) for i in range(1, 33)}
    base_bytes = app.editor.bank.to_sysex()

    app.duplicate_program()                    # 1 -> 2 (via EditorModel)
    assert bytes(app.editor.get_patch(2).data) == pre[1]
    assert app.editor.bank.to_sysex() != base_bytes   # real state change
    assert app.editor.is_dirty()
    app.undo()
    assert bytes(app.editor.get_patch(2).data) == pre[2]
    assert app.editor.bank.to_sysex() == base_bytes

    m = app.editor
    m.commit()
    app._history.push()
    m.swap_patches(1, 3)                       # slots genuinely differ
    app._after_mutation()
    assert bytes(m.get_patch(1).data) == pre[3]  # swapped content
    assert bytes(m.get_patch(3).data) == pre[1]
    assert m.is_dirty()
    app.undo()
    assert bytes(m.get_patch(1).data) == pre[1]
    assert bytes(m.get_patch(3).data) == pre[3]


@gui_test
def test_identical_slot_ops_are_noop(app):
    """ALL INIT SAW: every slot holds the same record, so duplicate/swap/move
    between any two slots leave the bank byte-identical → no dirty flip, no
    history growth (P1.15 corrective semantics)."""
    app.load_path(FIX / "ALL INIT SAW.syx")
    app.select_program(1)
    base_bytes = app.editor.bank.to_sysex()
    hist_before = len(app._history._undo) if hasattr(app._history, "_undo") else None

    app.duplicate_program()                    # 1 -> 2, identical records
    assert app.editor.bank.to_sysex() == base_bytes
    assert not app.editor.is_dirty()           # no-op → stays CLEAN

    app.editor.swap_patches(1, 3)              # identical records
    app.editor.move_patch(1, 5)                # identical records
    assert app.editor.bank.to_sysex() == base_bytes
    assert not app.editor.is_dirty()
    if hist_before is not None:
        assert len(app._history._undo) == hist_before  # no history entries


@gui_test
def test_copy_paste_roundtrip_preserves_unknown_bytes(app):
    src = FIX / "Synthmania-EDM-Soundset-JT-4000.syx"
    app.load_path(src)
    app.select_program(1)
    app.copy_program()                          # pure read via model API
    app.select_program(4)
    dst_unknown_before = dict(app.editor.get_patch(4).unknown_bytes())
    app.paste_program()                         # mutation via model API
    pasted = bytes(app.editor.get_patch(4).data)
    assert pasted == bytes(app.editor.get_patch(1).data)
    # paste replaced the whole record — undo restores everything incl. unknowns
    app.undo()
    now = app.editor.get_patch(4)
    assert dict(now.unknown_bytes()) == dst_unknown_before


# ------------------------------------------------------------- §10 dirty UI
@gui_test
def test_failed_save_keeps_modified(app, quiet, monkeypatch):
    app.load_path(FIX / "ALL INIT SAW.syx")
    app.select_program(1)
    app.vars["filter_cutoff"].set(5)
    app.apply_parameter("filter_cutoff")
    assert "Modified" in app.modified_var.get()

    def boom(*a, **k):
        raise OSError("disk on fire")
    monkeypatch.setattr("jt4000m.patch.Bank.save", boom)
    app._write(Path("/tmp/definitely-not-written-P110.syx"))
    assert Path("/tmp/definitely-not-written-P110.syx").exists() is False
    assert app.editor.is_dirty()                # baseline unchanged
    assert "Modified" in app.modified_var.get() # GUI keeps showing MODIFIED
    assert quiet                                # error dialog was raised


@gui_test
def test_gui_has_no_private_dirty_or_undo_state(app):
    """P1.10 §9/§10: the old GUI-side history/dirty mechanism is gone —
    single source of truth is EditorModel + EditorHistory."""
    for attr in ("_undo", "_redo", "_push_undo", "_saved_snapshot", "gui_dirty"):
        assert not hasattr(app, attr), f"stale GUI-side state: {attr}"
    # dirty indicator is a projection, not a stored flag
    app.load_path(FIX / "ALL INIT SAW.syx")
    assert app.modified_var.get() == ""
    app.editor.select_patch(1)
    app.editor.set_parameter("filter_cutoff", 3)
    app.editor.commit()
    app._update_modified()
    assert "Modified" in app.modified_var.get()


@gui_test
def test_history_buttons_reflect_can_undo_redo(app):
    app.load_path(FIX / "ALL INIT SAW.syx")
    assert not app._history.can_undo
    assert not app._history.can_redo
    app.select_program(1)
    app.vars["filter_cutoff"].set(66)
    app.apply_parameter("filter_cutoff")
    assert app._history.can_undo
    app.undo()
    assert app._history.can_redo
    app.redo()
    assert not app._history.can_redo


# ----------------------------------------------------- registry-driven UI
@gui_test
def test_parameters_rendered_from_registry_groups(app):
    """Controls come from the Parameter Registry groups — no hardcoded list
    duplicated in the GUI."""
    app.load_path(FIX / "ALL EMPTY.syx")
    rendered = {spec.key for spec in
                (__import__("jt4000m.model", fromlist=["PARAMETERS"]).PARAMETERS)
                if spec.offset is not None}
    assert rendered <= set(app.vars.keys())
    # group metadata drives sections; every registry section appears
    from jt4000m.editor_model import all_definitions
    groups = {d.group for d in all_definitions()} - {"UNMAPPED"}
    titles = {lbl.cget("text") for lbl in app.section_labels.values()}
    assert groups <= {"OSCILLATORS", "FILTER", "VCF ENVELOPE", "VCA ENVELOPE",
                      "LFO", "MODULATION"}


@gui_test
def test_reset_one_uses_new_public_api(app):
    app.load_path(FIX / "Synthmania-EDM-Soundset-JT-4000.syx")
    app.select_program(1)
    before = app.editor.get_patch(1).get_raw("osc_balance")
    app.reset_one("osc_balance")
    assert app.editor.get_patch(1).get_raw("osc_balance") == \
        BY_KEY["osc_balance"].default
    assert app.editor.is_dirty()
    app.undo()
    assert app.editor.get_patch(1).get_raw("osc_balance") == before


@gui_test
def test_reload_from_disk_uses_model_parser(app, tmp_path):
    out = tmp_path / "copy.syx"
    app.load_path(FIX / "ALL INIT SAW.syx")
    app.select_program(1)
    app.vars["filter_cutoff"].set(7)
    app.apply_parameter("filter_cutoff")
    app._write(out)
    app.path = out
    app.reload_from_disk()
    assert not app.editor.is_dirty()
    app.select_program(1)
    assert app.editor.get_patch(1).get_raw("filter_cutoff") == 7


@gui_test
def test_gui_module_does_not_import_midi():
    import sys
    import subprocess
    code = ("import sys; import jt4000m.gui;"
            "print('midi' in ' '.join(m for m in sys.modules "
            "if m.startswith('jt4000m')))")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "False"


# ------------------------------------------------- P1.10 UX polish: waveforms
def test_shape_for_known_labels():
    """Pure presentation mapping: registry display label -> shape kind."""
    from jt4000m.waveforms import shape_for
    assert shape_for("SAW") == "saw"
    assert shape_for("SUPER SAW") == "supersaw"
    assert shape_for("OFF") == "off"
    # Unknown values must NOT get an invented shape (evidence policy).
    assert shape_for("Unknown (0x07)") is None


@gui_test
def test_wave_tiles_follow_selection(app):
    """Wave tiles are driven by the model read API, not raw bytes."""
    app.load_path(FIX / "ALL INIT SAW.syx")           # OSC1/OSC2 = SAW
    assert app._osc_tiles["osc1_wave"].kind == "saw"
    app.select_program(1)
    app.editor.commit()
    app.editor.rename("ZZ")                            # some other patch? no-op rename
    # Switch to ALL EMPTY bank content via reload of a different fixture
    app.load_path(FIX / "Synthmania-EDM-Soundset-JT-4000.syx")
    kinds = {app._osc_tiles[k].kind for k in ("osc1_wave", "osc2_wave")}
    assert all(k is None or isinstance(k, str) for k in kinds)
    # A patch with an unknown wave value must render placeholder, never a lie
    found_unknown = False
    for idx in range(1, 33):
        app.select_program(idx)
        if app._osc_tiles["osc1_wave"].kind is None and \
                app.editor.get_patch(idx).get_parameter("osc1_wave").raw not in (0,):
            found_unknown = True
            break
    # Synthmania contains FUNMYLEAD/CLAP with wave 0x07 => placeholder expected
    assert found_unknown, "unknown enum value should map to no established shape"


@gui_test
def test_keyboard_navigation_selects_through_model(app):
    """Arrow navigation routes selection through EditorModel.select_patch."""
    app.load_path(FIX / "Synthmania-EDM-Soundset-JT-4000.syx")
    assert app.selected_index == 1
    app.listbox.selection_clear(0, "end")
    app.listbox.selection_set(4)                       # cursor on slot 5
    app._sync_selection_from_cursor()
    assert app.selected_index == 5
    assert app.editor.selected == 5                    # model state, not GUI copy


@gui_test
def test_adsr_graph_uses_attack_decay_sustain_and_release(app):
    """Each ADSR parameter must visibly affect its corresponding curve segment."""
    from jt4000m.widgets import EnvelopeView

    view = EnvelopeView(app.controls, title="test", width=330, height=70)
    try:
        view.set_values(0, 0, 0, 0)
        base = view._points()

        view.set_values(127, 0, 0, 0)
        attack = view._points()
        assert attack[1][0] != base[1][0]  # attack width

        view.set_values(0, 127, 0, 0)
        decay = view._points()
        assert decay[2][0] != base[2][0]  # decay width

        view.set_values(0, 0, 127, 0)
        sustain = view._points()
        assert sustain[2][1] != base[2][1]  # sustain level

        view.set_values(0, 0, 0, 127)
        release = view._points()
        assert release[3][0] != base[3][0]  # release segment width
    finally:
        view.destroy()


@gui_test
def test_adsr_slider_edit_refreshes_curve_and_wave_tiles_are_readable(app):
    app.load_path(FIX / "ALL INIT SAW.syx")
    assert app._osc_tiles["osc1_wave"].width == 176
    assert app._osc_tiles["osc2_wave"].width == 176

    before = app.vca_env_view._points()
    app.vars["vca_attack"].set(127)
    app.apply_parameter("vca_attack")
    after = app.vca_env_view._points()
    assert after != before
    assert app.vca_env_view._vals["attack"] == pytest.approx(1.0)


@pytest.mark.skipif(not _HAS_DISPLAY, reason="no display available")
def test_synth_workspace_matches_reference_layout_without_scrollbar(app):
    """Three top modules, two separate envelopes, four bottom modules."""
    assert not hasattr(app, "canvas")
    assert app.controls.winfo_manager() == "pack"
    cells = {
        (int(child.grid_info()["row"]), int(child.grid_info()["column"]),
         int(child.grid_info().get("columnspan", 1)))
        for child in app.controls.winfo_children()
        if child.winfo_manager() == "grid"
    }
    assert {(0, 0, 4), (0, 4, 4), (0, 8, 4),
            (1, 0, 5), (1, 5, 5), (1, 10, 2),
            (2, 0, 3), (2, 3, 3), (2, 6, 3), (2, 9, 3)} <= cells
    assert app.current_tab.get() == "SYNTH"
    assert [app.controls.grid_rowconfigure(i)["weight"] for i in range(3)] == [1, 1, 1]
    assert [app.controls.grid_rowconfigure(i)["uniform"] for i in range(3)] == [
        "synth-row", "synth-row", "synth-row"
    ]
    assert hasattr(app, "nav_query_entry")
    assert app.midibtn.cget("text") in ("Connect", "Disconnect")
    # Global history commands remain in Edit; the PRESETS toolbar does not
    # duplicate Undo/Redo buttons.
    assert app._edit_menu.entrycget(0, "label") == "Undo"
    assert app._edit_menu.entrycget(1, "label") == "Redo"

    def descendants(widget):
        for child in widget.winfo_children():
            yield child
            yield from descendants(child)

    assert not any(
        child.winfo_class() == "TButton" and child.cget("text") in ("Undo", "Redo")
        for child in descendants(app.tab_frames["PRESETS"])
    )
    # VCF ADSR must remain a complete, editable set.
    assert {"vcf_attack", "vcf_decay", "vcf_sustain", "vcf_release",
            "filter_env_amount"} <= set(app.vars)
    from jt4000m.model import editable_parameters
    assert {spec.key for spec in editable_parameters()} <= set(app.vars)


@gui_test
def test_window_keeps_900px_width_but_allows_compact_height(app):
    """900x700 is the baseline; reduced heights must be reachable for review."""
    assert app.geometry().split("+")[0] == "900x700"
    assert app.minsize() == (900, 500)


@gui_test
def test_all_three_synth_rows_share_equal_adaptive_height(app):
    """All three grid rows use one uniform sizing group at every height."""
    from types import SimpleNamespace

    for height in (900, 600, 420):
        app._on_synth_resize(SimpleNamespace(width=900, height=height))
        assert app._synth_row_height_px == height // 3
        assert app._synth_row_remainder_px == height - 3 * (height // 3)
        for row in range(3):
            config = app.controls.grid_rowconfigure(row)
            assert config["weight"] == 1
            assert config["uniform"] == "synth-row"
            assert config["minsize"] == 0

    # Width adaptation remains independent from the vertical row geometry.
    app._on_synth_resize(SimpleNamespace(width=800, height=600))
    assert app._synth_row_height_px == 200


@gui_test
def test_arpeggiator_panel_documents_native_settings_without_fake_controls(app):
    """ARP settings are visible, but unmapped device controls must not be faked."""
    assert hasattr(app, "arp_panel")
    labels = [child.cget("text") for child in app.arp_panel.winfo_children()
              if isinstance(child, tk.Label)]
    assert any("Native engine" in label for label in labels)
    assert any("MIDI Start/Stop" in label for label in labels)
    assert { "lfo2_wave", "lfo2_rate", "lfo2_amount" } <= set(app.vars)
    assert "lfo2_destination" not in app.vars


@gui_test
def test_top_patch_selector_accepts_slot_number_and_full_name(app):
    app.load_path(FIX / "Synthmania-EDM-Soundset-JT-4000.syx")
    app.nav_query_var.set("5")
    app._apply_nav_query()
    assert app.selected_index == 5
    name = app.editor.get_patch(2).name
    app.nav_query_var.set(name)
    app._apply_nav_query()
    assert app.selected_index == 2


# ---------------------------------------------------- P1.46 responsive graphs
@gui_test
def test_filter_and_envelope_graph_geometry_tracks_resize(app):
    """Graph coordinates follow the live canvas dimensions after window resize."""
    from types import SimpleNamespace
    from jt4000m.widgets import EnvelopeView, FilterView

    filter_view = FilterView(app.controls, width=150, height=56)
    envelope_view = EnvelopeView(app.controls, title="test", width=150, height=56)
    try:
        filter_view._on_resize(SimpleNamespace(width=520, height=112))
        envelope_view._on_resize(SimpleNamespace(width=520, height=112))
        assert filter_view.width == 520
        assert filter_view.height == 98
        assert envelope_view.width == 520
        assert envelope_view.height == 96
        assert filter_view.find_all()  # redraw happened
        assert envelope_view.find_all()
        assert max(p[0] for p in envelope_view._points()) >= 512
    finally:
        filter_view.destroy()
        envelope_view.destroy()



@gui_test
def test_redundant_parameter_labels_are_hidden_for_knobs_and_combos(app):
    """Controls should not repeat their name in a nearby label or inside a knob."""
    from jt4000m.widgets import Knob

    # OSC Balance keeps its row label, but the knob itself has no caption.
    balance = app._knobs["osc_balance"]
    assert isinstance(balance, Knob)
    assert balance.label == ""

    # Both envelopes use only the four segment names; no VCA/VCF prefix.
    for prefix in ("vca", "vcf"):
        for segment in ("attack", "decay", "sustain", "release"):
            knob = app._knobs[f"{prefix}_{segment}"]
            assert knob.label == ""
            assert app.section_labels[f"{prefix}_{segment}"].cget("text") == segment.capitalize()
    assert app.vca_env_view.title == ""
    assert app.vcf_env_view.title == ""

    # Enum combobox text is the label; hide the duplicate left label/value.
    for key in ("osc1_wave", "osc2_wave", "lfo1_wave", "lfo2_wave", "portamento_mode"):
        combo = getattr(app, f"combo_{key}", None)
        if combo is None:
            continue
        assert app.section_labels[key].winfo_manager() == ""
        reset, value_label = app.reset_buttons[key]
        assert value_label.winfo_manager() == ""
        assert reset.winfo_exists()


@gui_test
def test_adsr_controls_use_compact_knobs_with_requested_arc(app):
    from jt4000m.widgets import Knob

    for prefix in ("vca", "vcf"):
        for segment in ("attack", "decay", "sustain", "release"):
            key = f"{prefix}_{segment}"
            knob = app._knobs[key]
            assert isinstance(knob, Knob)
            assert knob.start_angle == 180.0
            assert knob.sweep_degrees == 180.0
            assert knob.angle_direction == -1
            assert knob.minimum == BY_KEY[key].minimum
            assert knob.maximum == BY_KEY[key].maximum
            assert key in app.vars and key in app.value_vars


@gui_test
def test_compact_controls_hide_numeric_readouts_but_keep_reset_buttons(app):
    """Free horizontal space for controls while keeping per-parameter reset."""
    app.load_path(FIX / "ALL INIT SAW.syx")
    for key in ("osc1_pwm_fm", "osc1_coarse", "osc1_fine",
                "osc2_pwm", "osc2_coarse", "osc2_fine",
                "filter_cutoff", "filter_resonance", "vca_attack",
                "vcf_release", "osc_balance"):
        reset, value_label = app.reset_buttons[key]
        assert reset.winfo_manager() != ""
        assert value_label.winfo_manager() == ""

    assert app._osc_tiles["osc1_wave"].width == 176
    assert app._osc_tiles["osc2_wave"].width == 176
    assert app.midibtn.cget("width") == 8
    refresh = next(child for child in app.midibtn.master.winfo_children()
                   if child.winfo_class() == "TButton" and child.cget("text") == "Refresh")
    assert refresh.cget("width") == 7

    # Slider thumb colour is fixed, not only applied on hover.
    scale = next(s for s in app._parameter_scales
                 if str(s.cget("orient")) == "horizontal")
    assert scale.cget("background") == "#42D9FF"
    assert app._knobs["vca_attack"]._d == 44
