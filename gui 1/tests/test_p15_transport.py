"""P1.5 — transport abstraction tests. OFFLINE ONLY: a FakeMidiBackend is
injected explicitly; these tests never enumerate or touch real MIDI devices."""
import pytest

from jt4000m.transport import MidiTransport, PortInfo, TransportReport


def test_discovery_by_name(fake_transport):
    ins = fake_transport.list_inputs()
    outs = fake_transport.list_outputs()
    assert [p.name for p in ins] == ["JT-4000M MICRO"]
    assert "Microsoft GS Wavetable Synth" in [p.name for p in outs]
    hits = fake_transport.find("jt-4000m")
    assert {p.direction for p in hits} == {"input", "output"}
    # no numeric-index assumption: matching is purely by name substring
    assert fake_transport.find("no-such-device") == []


def test_send_cc_report_is_tx_only(fake_transport, fake_backend):
    port = fake_transport.find("JT-4000M", "output")[0]
    rep = fake_transport.send_cc(port, 1, 74, 64)
    assert rep.tx_bytes == bytes([0xB0, 0x4A, 0x40])
    assert rep.api_ok is True
    assert rep.device_response == "NOT VERIFIED"
    assert fake_backend.tx_log == [bytes([0xB0, 0x4A, 0x40])]
    text = rep.format()
    assert "B0 4A 40" in text
    assert "Transport:" in text and "OK" in text
    assert "Device response:" in text and "NOT VERIFIED" in text
    assert "TRANSPORT VERIFIED != DEVICE BEHAVIOR VERIFIED" in text


def test_send_sysex_records_exact_bytes(fake_transport, fake_backend,
                                        all_empty):
    from jt4000m.syx import parse_file
    syx = parse_file(all_empty)
    port = fake_transport.find("JT-4000M", "output")[0]
    rep = fake_transport.send_sysex(port, syx.raw)
    assert rep.api_ok
    assert fake_backend.tx_log == [syx.raw]


def test_receive_yields_queued_messages(fake_transport, fake_backend):
    fake_backend.rx_queue = [bytes([0xB0, 1, 2]), b"\xF0\x00\x20\xF7"]
    port = fake_transport.find("JT-4000M", "input")[0]
    fake_transport.open_input(port)
    msgs = [data for _ts, data in fake_transport.receive(timeout=0.2)]
    assert len(msgs) == 2
    assert msgs[1].startswith(b"\xF0")


def test_no_backend_reports_honestly(monkeypatch):
    monkeypatch.setattr("jt4000m.transport._load_backend",
                        lambda: ("none", None, "simulated: no backend"))
    tr = MidiTransport()
    assert not tr.available
    assert tr.list_inputs() == []
    port = PortInfo(0, "ghost", "output")
    rep = tr.send_cc(port, 1, 7, 64)
    assert rep.api_ok is False          # honest failure, no exception crash
    assert "FAILED" in rep.format()
    with pytest.raises(RuntimeError):
        tr.open_input(port)


def test_invalid_cc_range_rejected(fake_transport):
    port = fake_transport.find("JT-4000M", "output")[0]
    with pytest.raises(ValueError):
        fake_transport.send_cc(port, 1, 74, 999)


# ------------------------------------------------------------------------- CLI

def _args(**kw):
    import argparse
    return argparse.Namespace(**kw)


def test_cli_midi_list_with_fake(monkeypatch, capsys, fake_backend):
    import jt4000m.cli as cli
    monkeypatch.setattr(cli, "_transport",
                        lambda: MidiTransport(backend=fake_backend,
                                              backend_name="rtmidi"))
    cli.main(["midi", "list"])
    out = capsys.readouterr().out
    assert "MIDI INPUTS" in out and "JT-4000M MICRO" in out
    assert "Microsoft GS Wavetable Synth" in out


def test_cli_midi_probe_finds_by_name(monkeypatch, capsys, fake_backend):
    import jt4000m.cli as cli
    monkeypatch.setattr(cli, "_transport",
                        lambda: MidiTransport(backend=fake_backend,
                                              backend_name="rtmidi"))
    cli.main(["midi", "probe"])
    out = capsys.readouterr().out
    assert "PROBE for 'JT-4000M'" in out
    assert "[input]" in out and "[output]" in out
    assert "NO SysEx was sent" in out


def test_cli_midi_cc_reports_not_verified(monkeypatch, capsys, fake_backend):
    import jt4000m.cli as cli
    monkeypatch.setattr(cli, "_transport",
                        lambda: MidiTransport(backend=fake_backend,
                                              backend_name="rtmidi"))
    cli.main(["midi", "cc", "1", "74", "64"])
    out = capsys.readouterr().out
    assert "B0 4A 40" in out
    assert "NOT VERIFIED" in out
    assert fake_backend.tx_log  # fake recorded the TX; nothing real happened


def test_cli_sysex_send_requires_yes_confirmation(monkeypatch, capsys,
                                                  fake_backend, all_empty,
                                                  tmp_path, monkeypatch_module=None):
    import jt4000m.cli as cli
    monkeypatch.setattr(cli, "_transport",
                        lambda: MidiTransport(backend=fake_backend,
                                              backend_name="rtmidi"))
    # user answers NO -> nothing may be transmitted
    monkeypatch.setattr("builtins.input", lambda *a: "no")
    cli.main(["midi", "sysex-send", str(all_empty)])
    out = capsys.readouterr().out
    assert "Aborted" in out
    assert fake_backend.tx_log == []
    assert "Checksum:\n  OK" in out and "Mode:\n  bulk" in out


def test_cli_sysex_send_confirmed_yes(monkeypatch, capsys, fake_backend,
                                      all_empty):
    import jt4000m.cli as cli
    monkeypatch.setattr(cli, "_transport",
                        lambda: MidiTransport(backend=fake_backend,
                                              backend_name="rtmidi"))
    monkeypatch.setattr("builtins.input", lambda *a: "YES")
    cli.main(["midi", "sysex-send", str(all_empty)])
    assert len(fake_backend.tx_log) == 1
    assert fake_backend.tx_log[0].startswith(b"\xF0")
    out = capsys.readouterr().out
    assert "Device response:" in out and "NOT VERIFIED" in out


def test_cli_sysex_send_refuses_bad_checksum(monkeypatch, capsys, fake_backend,
                                             all_empty, tmp_path):
    import jt4000m.cli as cli
    bad = bytearray(all_empty.read_bytes())
    bad[-2] ^= 0xFF   # corrupt stored checksum byte
    badfile = tmp_path / "bad.syx"
    badfile.write_bytes(bytes(bad))
    monkeypatch.setattr(cli, "_transport",
                        lambda: MidiTransport(backend=fake_backend,
                                              backend_name="rtmidi"))
    with pytest.raises(SystemExit):
        cli.main(["midi", "sysex-send", str(badfile), "--yes"])
    assert fake_backend.tx_log == []   # refused BEFORE any transmission


def test_cli_capture_saves_received_sysex(monkeypatch, capsys, fake_backend,
                                          all_empty, tmp_path):
    import jt4000m.cli as cli
    raw = all_empty.read_bytes()
    fake_backend.rx_queue = [raw]
    monkeypatch.setattr(cli, "_transport",
                        lambda: MidiTransport(backend=fake_backend,
                                              backend_name="rtmidi"))
    out_file = tmp_path / "captured.syx"
    cli.main(["midi", "capture", "--output", str(out_file), "--timeout", "0.2"])
    assert out_file.read_bytes() == raw
    out = capsys.readouterr().out
    assert "SYSEX" in out


def test_cli_listen_without_rx_is_not_an_error(monkeypatch, capsys,
                                               fake_backend):
    import jt4000m.cli as cli
    monkeypatch.setattr(cli, "_transport",
                        lambda: MidiTransport(backend=fake_backend,
                                              backend_name="rtmidi"))
    cli.main(["midi", "listen", "--timeout", "0.1"])
    out = capsys.readouterr().out
    assert "Waiting for MIDI..." in out
    assert "NOT a Python" in out
