"""Opt-in hardware checks — run manually with:

    JT4000M_HARDWARE_TEST=1 pytest tests/hardware -q

These are DISCOVERY/REPORTING checks only. They never transmit CC or SysEx
to the synthesizer, because TRANSPORT VERIFIED and DEVICE BEHAVIOR VERIFIED
are different claims and sending unverified traffic is out of scope until a
human drives it interactively via `python -m jt4000m.cli midi ...`.
"""
import pytest


def _transport():
    from jt4000m.transport import MidiTransport
    return MidiTransport()


def test_backend_available():
    tr = _transport()
    assert tr.available, f"no MIDI backend: {tr.note}"


def test_jt4000m_endpoints_visible_by_name():
    """Windows should show 'JT-4000M MICRO' as both input and output."""
    tr = _transport()
    hits = tr.find("JT-4000M")
    directions = {p.direction for p in hits}
    assert "input" in directions, (
        "JT-4000M MIDI INPUT endpoint not found — check USB/MIDI drivers")
    assert "output" in directions, (
        "JT-4000M MIDI OUTPUT endpoint not found — check USB/MIDI drivers")
    # We deliberately do NOT assert numeric port indices.


def test_probe_cli_reports_discovery_only(capsys):
    from jt4000m.cli import main
    main(["midi", "probe"])
    out = capsys.readouterr().out
    assert "NO SysEx was sent" in out


def test_offline_experiment_on_fixtures(all_empty, all_init_saw):
    # Pure file analysis; included here so the opt-in hardware session also
    # exercises the full compare path on real-world dumps.
    from jt4000m.experiment import compare_experiment
    res = compare_experiment(all_empty, all_init_saw, program=1,
                             hypothesis="osc1_wave")
    assert res.verdict == "CONFIRMED"
