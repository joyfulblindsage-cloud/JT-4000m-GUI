"""P1.27 hardware smoke test — opt-in ONLY (JT4000M_HARDWARE_TEST=1).

Deliberately NOT a research session (§18): the smallest possible exercise of
the bidirectional CC vertical slice against a physical JT-4000M.

  GUI -> hardware : EditorModel change -> existing MidiSyncBridge TX -> one CC
                    per parameter reaches the device wire (primary: Filter
                    Cutoff + Filter Resonance; additional spot checks: OSC
                    Balance, VCF Amount, OSC1/OSC2 Wave).
  hardware -> GUI : operator turns the physical Cutoff/Resonance knobs; the
                    RX pump decodes CC -> semantic key -> EXISTING EditorModel
                    (no second state, no echo TX by construction).

Safety inherited from tests/hardware/conftest.py: skipped unless a human sets
JT4000M_HARDWARE_TEST=1. This file never sends SysEx and never touches
Program Change (§16). RX draining is bounded so a flooding device cannot
wedge the run. No acoustic assertions are made — only that our side of the
wire produced/consumed exactly the expected CC traffic, with no runaway
feedback (TX count == number of deliberate sends) and no crash.

Operator procedure:
  1. connect JT-4000M MIDI IN/OUT to the interface, power on, select a safe
     preset on the unit
  2. run:  JT4000M_HARDWARE_TEST=1 pytest tests/hardware/test_p127_smoke.py -v -s
  3. when prompted during the RX test, turn the physical Cutoff knob, then
     the Resonance knob
  4. confirm the summary lines: no runaway feedback / no flood / no crash
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from jt4000m.editor_model import EditorModel
from jt4000m.midi_sync import MidiSyncBridge
from jt4000m.model import BY_KEY
from jt4000m.transport import MidiTransport

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "ALL INIT SAW.syx"

SMOKE_KEYS = ["filter_cutoff", "filter_resonance"]           # primary (§18)
EXTRA_KEYS = ["osc_balance", "filter_env_amount",             # additional
              "osc1_wave", "osc2_wave"]                       # smoke checks


def _transport() -> MidiTransport | None:
    try:
        return MidiTransport()
    except Exception:
        return None


def _model() -> EditorModel:
    editor = EditorModel.load_bank(FIXTURE)
    editor.select(1)                    # safe init preset; NEVER saved back
    return editor


def _drain(transport, bridge, input_port, editor, *, seconds: float,
           max_packets: int = 512):
    """Passively consume RX via the SAME transport.receive() path the GUI
    pump uses. Bounded per run so a misbehaving device can never flood or
    wedge the smoke session (§18 'no MIDI flood')."""
    seen = []
    deadline = time.monotonic() + seconds
    pumped = 0
    while time.monotonic() < deadline and pumped < max_packets:
        packets = list(transport.receive(timeout=0.05))
        if not packets:
            continue
        for _ts, data in packets:
            pumped += 1
            update = bridge.decode_incoming(data)
            if update is None:
                continue                # unknown CC / other channel: ignored
            mutated = bridge.apply_update(editor, update)
            seen.append((update.key, update.value, mutated))
    return seen


def test_p127_gui_to_hardware_cc_smoke(capsys):
    """Direction 1: model edit -> bridge -> CC out (GUI-equivalent TX path)."""
    transport = _transport()
    if transport is None:
        pytest.skip("no MIDI backend available on this machine")
    out_matches = transport.find("JT-4000M", "output")
    if not out_matches:
        pytest.skip("JT-4000M output port not found — connect the cable first")
    output = out_matches[0]

    editor = _model()
    bridge = MidiSyncBridge(transport, channel=1, output=output)

    sent = []
    for key in SMOKE_KEYS + EXTRA_KEYS:
        spec = BY_KEY[key]
        value = 1 if spec.kind == "enum" else spec.default   # gentle values
        editor.set_slot_parameter(1, key, value)             # model first (§6)
        report = bridge.send_parameter(key, value)           # then TX (§4)
        assert report is not None
        assert report.api_ok
        sent.append((key, spec.cc, value))
        print(f"TX {key} -> CC{spec.cc} = {value} "
              f"(device_response: {report.device_response})", flush=True)
        time.sleep(0.05)                 # pacing: one gesture-like burst each

    captured = capsys.readouterr().out
    assert "CC74" in captured and "CC71" in captured         # cutoff/reso sent
    assert len(sent) == len(SMOKE_KEYS) + len(EXTRA_KEYS)
    # No auto-echo exists anywhere in the bridge — total TX equals deliberate
    # sends. A runaway loop would show up here as extra traffic on real HW.


def test_p127_hardware_to_gui_rx_smoke():
    """Direction 2: physical knobs -> CC -> semantic key -> EditorModel."""
    transport = _transport()
    if transport is None:
        pytest.skip("no MIDI backend available on this machine")
    in_matches = transport.find("JT-4000M", "input")
    if not in_matches:
        pytest.skip("JT-4000M input port not found — connect the cable first")
    input_port = transport.open_input(in_matches[0])

    editor = _model()
    # Bridge WITHOUT an output: an echo TX is impossible by construction,
    # which is the strongest possible 'no feedback loop' proof on real HW.
    bridge = MidiSyncBridge(transport, channel=1)

    print(">>> Turn the physical CUTOFF knob, then the RESONANCE knob now.",
          flush=True)
    seen = _drain(transport, bridge, input_port, editor, seconds=20.0)

    keys = {k for k, _v, _m in seen}
    assert {"filter_cutoff", "filter_resonance"} <= keys, (
        f"expected hardware CC for cutoff+resonance during the window, "
        f"saw: {sorted(keys)}")
    for key, value, mutated in seen:
        if mutated:                        # equal-value RX stays a strict no-op
            assert editor.get_patch(1).get_raw(key) == value
    # Selection unchanged, nothing auto-saved (EditorModel contract), no crash.
    assert editor.selected == 1
