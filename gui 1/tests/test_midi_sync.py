import pytest

from jt4000m.midi_sync import MidiSyncBridge


def test_bridge_sends_established_parameter_cc(fake_transport, fake_backend):
    output = fake_transport.find("JT-4000M", "output")[0]
    bridge = MidiSyncBridge(fake_transport, channel=2, output=output)
    report = bridge.send_parameter("filter_cutoff", 99)
    assert report is not None and report.api_ok
    assert fake_backend.tx_log == [bytes([0xB1, 74, 99])]


def test_bridge_requires_an_output_for_transmit(fake_transport):
    with pytest.raises(RuntimeError, match="No MIDI output"):
        MidiSyncBridge(fake_transport).send_parameter("filter_cutoff", 1)


def test_bridge_does_not_invent_cc_for_sysex_only_parameter(fake_transport):
    assert MidiSyncBridge(fake_transport).send_parameter("portamento_amount", 1) is None


def test_bridge_decodes_only_matching_established_ccs(fake_transport):
    bridge = MidiSyncBridge(fake_transport, channel=2)
    assert bridge.decode_incoming(bytes([0xB1, 74, 42])).key == "filter_cutoff"
    assert bridge.decode_incoming(bytes([0xB1, 74, 42])).value == 42
    assert bridge.decode_incoming(bytes([0xB0, 74, 42])) is None
    assert bridge.decode_incoming(bytes([0xB1, 127, 42])) is None
    assert bridge.decode_incoming(b"\xF0\x01\xF7") is None


def test_bridge_normalizes_ring_mod_input(fake_transport):
    bridge = MidiSyncBridge(fake_transport)
    assert bridge.decode_incoming(bytes([0xB0, 96, 127])).value == 1
