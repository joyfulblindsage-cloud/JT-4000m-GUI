"""P1.29d backend fallback checks; no real MIDI ports are opened."""
from __future__ import annotations

import importlib
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from jt4000m import transport


def test_winmm_source_compiles_on_all_platforms():
    source = Path(__file__).resolve().parents[1] / "jt4000m" / "midi_winmm.py"
    compile(source.read_text(encoding="utf-8"), str(source), "exec")


def test_windows_falls_back_to_rtmidi_when_winmm_import_fails(monkeypatch):
    fake_rtmidi = SimpleNamespace(MidiIn=object, MidiOut=object)
    real_import = importlib.import_module

    def fake_import(name, package=None):
        if name == "jt4000m.midi_winmm":
            raise ImportError("simulated WinMM import failure")
        if name == "rtmidi":
            return fake_rtmidi
        return real_import(name, package)

    monkeypatch.setattr(importlib, "import_module", fake_import)
    name, backend, note = transport._load_backend(platform="nt")

    assert name == "rtmidi"
    assert backend is fake_rtmidi
    assert "winmm unavailable" in note
    assert "fallback" in note


def test_windows_prefers_winmm_when_it_imports(monkeypatch):
    fake_winmm = SimpleNamespace(list_inputs=lambda: [], list_outputs=lambda: [])
    real_import = importlib.import_module

    def fake_import(name, package=None):
        if name == "jt4000m.midi_winmm":
            return fake_winmm
        if name == "rtmidi":
            raise AssertionError("rtmidi should not be imported when WinMM works")
        return real_import(name, package)

    monkeypatch.setattr(importlib, "import_module", fake_import)
    name, backend, note = transport._load_backend(platform="nt")

    assert (name, backend, note) == ("winmm", fake_winmm, "")


def test_no_backend_message_reports_both_failures(monkeypatch):
    real_import = importlib.import_module

    def fake_import(name, package=None):
        if name in ("jt4000m.midi_winmm", "rtmidi"):
            raise ImportError(f"simulated missing {name}")
        return real_import(name, package)

    monkeypatch.setattr(importlib, "import_module", fake_import)
    name, backend, note = transport._load_backend(platform="nt")

    assert name == "none"
    assert backend is None
    assert "winmm unavailable" in note
    assert "python-rtmidi unavailable" in note


@pytest.mark.skipif(
    os.name != "nt" and not os.environ.get("DISPLAY"),
    reason="requires a graphical display",
)
def test_gui_shows_reason_when_no_midi_backend_is_available(monkeypatch):
    monkeypatch.setattr(
        transport, "_load_backend",
        lambda: ("none", None, "simulated: install python-rtmidi"),
    )
    from jt4000m.gui import Editor

    app = Editor()
    try:
        app.refresh_midi_ports()
        assert "MIDI unavailable" in app.status_var.get()
        assert "install python-rtmidi" in app.status_var.get()
        assert app._midi_status == "error"
    finally:
        app.destroy()


@pytest.mark.skipif(os.name != "nt", reason="requires Windows WinMM")
def test_winmm_short_message_decoder_handles_cc_and_program_change():
    from jt4000m.midi_winmm import _short_message_from_packed

    assert _short_message_from_packed(0x00404AB0) == bytes([0xB0, 74, 64])
    assert _short_message_from_packed(0x000010C0) == bytes([0xC0, 16])
