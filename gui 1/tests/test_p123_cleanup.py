"""Regression tests for the post-P1.23 cleanup boundary.

These tests are offline: no physical MIDI device is touched.
"""
from pathlib import Path

from jt4000m.editor_model import EditorHistory, EditorModel
from jt4000m.midi_sync import MidiSyncBridge
from jt4000m.transport import MidiTransport, PortInfo


class FakeBackend:
    def __init__(self):
        self.short = []
        self.sysex = []
        self.inputs = ["JT-4000M IN"]
        self.outputs = ["JT-4000M OUT"]

    def list_inputs(self):
        return [type("P", (), {"index": 2, "name": self.inputs[0]})()]

    def list_outputs(self):
        return [type("P", (), {"index": 3, "name": self.outputs[0]})()]

    def send_short(self, index, data):
        self.short.append((index, bytes(data)))

    def send_sysex(self, index, data):
        self.sysex.append((index, bytes(data)))


def test_transport_uses_injected_backend_for_cc():
    be = FakeBackend()
    t = MidiTransport(backend=be, backend_name="winmm")
    port = PortInfo(3, "JT-4000M OUT", "output")
    report = t.send_cc(port, 1, 74, 42)
    assert report.api_ok
    assert report.device_response == "NOT VERIFIED"
    assert be.short == [(3, bytes([0xB0, 74, 42]))]


def test_transport_sysex_is_explicit_and_reports_transport_only():
    be = FakeBackend()
    t = MidiTransport(backend=be, backend_name="winmm")
    port = PortInfo(3, "JT-4000M OUT", "output")
    raw = bytes.fromhex("F0 00 20 32 00 01 38 10 00 F7")
    report = t.send_sysex(port, raw)
    assert report.api_ok
    assert report.tx_bytes == raw
    assert be.sysex == [(3, raw)]
    assert report.device_response == "NOT VERIFIED"


def test_history_sync_dirty_does_not_access_model_private_dirty():
    # Keep this as a source-level guard: the history adapter must use the
    # public recalculation API introduced during the P1.23 cleanup.
    source = Path(__file__).resolve().parents[1] / "jt4000m" / "editor_model.py"
    text = source.read_text(encoding="utf-8")
    history = text[text.index("class EditorHistory"):text.index("# ---------------------------------------------------------------------------\n# Registry validation")]
    assert "self._model._dirty =" not in history
    assert "self._model.recalculate_dirty()" in history


def test_program_change_remains_selection_only(all_init_saw):
    model = EditorModel()
    model.load_bank(all_init_saw)
    history = EditorHistory(model)
    history.push()
    before = model.bank.to_sysex()
    bridge = MidiSyncBridge(None, channel=1)
    selection = bridge.decode_program_change(bytes([0xC0, 7]))
    assert selection is not None
    model.select_patch(selection.slot)
    assert model.selected == 8
    assert model.bank.to_sysex() == before
    assert model.is_dirty() is False
    assert history.depth_undo == 1
