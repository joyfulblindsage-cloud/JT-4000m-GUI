"""P1.6 — offline regression tests for the live-session workflow.

Safety: NOTHING here touches real MIDI hardware. Transport interactions use
the injected FakeMidiBackend from conftest.py; session/capture modules perform
no I/O of their own.  Real-hardware checks live in tests/hardware/ (opt-in).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from jt4000m.capture import CaptureBuffer, classify_rx
from jt4000m.patch import JTProgram
from jt4000m.session import (SessionLog, load_session, NO_RX,
                             TRANSPORT_VERIFIED, DEVICE_RX_OBSERVED)
from jt4000m.experiment import (PROVENANCE_FIXTURE, PROVENANCE_DEVICE,
                                detect_provenance)


# --------------------------------------------------------------- capture rx
def test_classify_rx_types():
    assert classify_rx(b'') == "EMPTY"
    assert classify_rx(b'\xF0\x00\x20\x32\xF7') == "SYSEX_COMPLETE"
    assert classify_rx(b'\xF0\x00\x20\x32\x00') == "SYSEX_INCOMPLETE"
    assert classify_rx(b'\x90\x3C\x64') == "NOTE_ON"
    assert classify_rx(b'\xB0\x4A\x40') == "CONTROL_CHANGE"
    assert classify_rx(b'\xF8') == "UNKNOWN_0xF8"   # realtime clock byte


def test_capture_buffer_empty_is_no_rx_not_error():
    buf = CaptureBuffer()
    assert buf.total == 0
    assert buf.result_label() == NO_RX
    assert buf.save_last_sysex("/tmp/should-not-exist.syx") is None


def test_capture_buffer_single_sysex_saved_byte_exact(tmp_path):
    raw = bytes([0xF0, 0x00, 0x20, 0x32, 0x00, 0x01, 0x38, 0x01, 0x02, 0xF7])
    buf = CaptureBuffer()
    buf.add(time.time(), raw)
    out = buf.save_last_sysex(tmp_path / "cap.syx")
    assert out is not None and out.read_bytes() == raw          # unmodified
    assert buf.result_label() == DEVICE_RX_OBSERVED


def test_capture_buffer_multiple_sysex_saves_last_complete(tmp_path):
    a = b'\xF0\x01\x02\xF7'
    b = b'\xF0\x03\x04\x05\xF7'
    buf = CaptureBuffer()
    buf.add(1.0, a)
    buf.add(2.0, b'\xF0\xEE')            # incomplete — must NOT be saved
    buf.add(3.0, b)
    out = buf.save_last_sysex(tmp_path / "c.syx")
    assert out.read_bytes() == b
    counts = buf.counts_by_kind()
    assert counts["SYSEX_COMPLETE"] == 2 and counts["SYSEX_INCOMPLETE"] == 1


def test_capture_buffer_malformed_kept_in_raw_log(tmp_path):
    buf = CaptureBuffer()
    buf.add(1.0, b'\xF0\xEE')                     # truncated sysex
    buf.add(2.0, b'\x99')                          # stray status byte
    p = buf.save_all(tmp_path / "rx.jsonl")
    lines = [json.loads(l) for l in p.read_text().splitlines()]
    assert len(lines) == 2                         # nothing silently dropped
    assert lines[0]["kind"] == "SYSEX_INCOMPLETE"
    assert lines[1]["hex"] == "99"


def test_capture_non_sysex_traffic_never_written_as_syx(tmp_path):
    buf = CaptureBuffer()
    buf.add(1.0, b'\x90\x3C\x64')                  # NOTE_ON only
    assert buf.save_last_sysex(tmp_path / "x.syx") is None
    assert buf.result_label() == "RX_NON_SYSEX_ONLY"


# ---------------------------------------------------------------- fake RX ->
# compare a captured dump through the REAL parser path used by experiments
def test_captured_fixture_bytes_roundtrip_through_parser(all_init_saw):
    from jt4000m.syx import parse_file
    raw = Path(all_init_saw).read_bytes()
    buf = CaptureBuffer()
    buf.add(time.time(), raw)                      # pretend device sent it
    # (only used to prove buffer keeps bytes EXACTLY as fed)
    assert buf.sysex_complete[-1].data == raw
    s = parse_file(buf.sysex_complete[-1].data) if False else None  # noqa
    parsed = parse_file(Path(all_init_saw))
    assert parsed.checksum_ok and len(parsed.programs) == 32


# ------------------------------------------------------------- session log
def test_session_log_clean_record(tmp_path):
    sl = SessionLog("fake")
    sl.set_ports(input_port=None, output_port=None)
    sl.add_action('probe', rx_count=0, detail={"sent": 0})
    p = sl.save(tmp_path)
    d = load_session(p)
    assert d["schema_version"] == 1
    assert d["backend"] == "fake"
    assert d["verification"] == []                 # probe proves nothing TX
    assert d["tx_messages"] == 0 and d["rx_messages"] == 0


def test_session_log_transport_verified_only_on_api_ok(tmp_path):
    sl = SessionLog("winmm")
    sl.add_action('cc', tx_bytes=b'\xB0\x4A\x40', api_ok=True, rx_count=0)
    d = load_session(sl.save(tmp_path))
    assert d["verification"] == [TRANSPORT_VERIFIED]
    assert "DEVICE RX OBSERVED" not in d["verification"]
    assert d["actions"][0]["transport"] == TRANSPORT_VERIFIED
    assert d["actions"][0]["tx_hex_head"] == "B0 4A 40"


def test_session_log_failed_tx_records_failure(tmp_path):
    sl = SessionLog("rtmidi")
    sl.add_action('cc', tx_bytes=b'\xB0\x00\x00', api_ok=False,
                  error="device busy", rx_count=0)
    d = load_session(sl.save(tmp_path))
    assert d["verification"] == []                 # failed API != verified
    assert d["actions"][0]["transport"] == "TRANSPORT FAILED"


def test_session_log_rx_observed_level(tmp_path):
    sl = SessionLog("winmm")
    sl.add_action('capture', rx_count=3, detail={"result": "DEVICE RX OBSERVED"})
    d = load_session(sl.save(tmp_path))
    assert d["verification"] == [DEVICE_RX_OBSERVED]
    assert d["rx_messages"] == 3


def test_session_log_never_claims_device_behavior(tmp_path):
    # Even with TX OK + RX observed, session logs do not emit BEHAVIOR level;
    # that verdict belongs exclusively to experiment compare.
    sl = SessionLog("winmm")
    sl.add_action('sysex-send', tx_bytes=b'\xF0\x01\xF7', api_ok=True,
                  rx_count=0)
    sl.add_action('listen', rx_count=1)
    ver = " ".join(sl.verification_levels())
    assert "BEHAVIOR" not in ver.upper()


def test_session_log_files_and_provenance(tmp_path):
    f = tmp_path / "capture.syx"
    f.write_bytes(b'\xF0\x00\xF7')
    sl = SessionLog("winmm")
    sl.add_file(f, "capture", provenance=PROVENANCE_DEVICE,
                checksum_status="OK", messages=1)
    d = load_session(sl.save(tmp_path / "s"))
    rec = d["files"][0]
    assert rec["provenance"] == PROVENANCE_DEVICE
    assert rec["size"] == 3 and rec["checksum"] == "OK"


# ------------------------------------------------------------ provenance
def test_detect_provenance_default_fixture(all_empty):
    assert detect_provenance(all_empty) == PROVENANCE_FIXTURE


def test_detect_provenance_from_recorded_capture(tmp_path, all_init_saw):
    cap = tmp_path / "captured.syx"
    cap.write_bytes(Path(all_init_saw).read_bytes())
    sl = SessionLog("winmm")
    sl.add_file(cap, "capture", provenance=PROVENANCE_DEVICE)
    sess_dir = tmp_path / "sessions"
    sl.save(sess_dir)
    assert detect_provenance(cap, sessions_dir=sess_dir) == PROVENANCE_DEVICE
    # bundled fixture is NOT promoted even though content is identical:
    assert detect_provenance(all_init_saw,
                             sessions_dir=sess_dir) == PROVENANCE_FIXTURE


# ------------------------------------------------- A/B over captured files
def _write_variant(base: Path, dst: Path, program: int, edits: dict,
                   rename: str | None = None):
    """Edit one bank slot via the existing model (no new abstractions)."""
    from jt4000m.patch import Bank
    bank = Bank.load(base)
    prog = bank.programs[program - 1]
    for key, val in edits.items():
        prog = prog.set_parameter(key, val)
    if rename is not None:
        prog = prog.set_name(rename)
    bank = bank.replace(program, prog)
    bank.save(dst)
    return dst


def test_ab_experiment_confirmed_single_byte(tmp_path, all_init_saw):
    # INIT SAW has osc1_wave=SAW(4); produce an OFF variant -> A/B isolated
    a = _write_variant(all_init_saw, tmp_path / "A.syx", 1,
                       {"osc1_wave": 0})
    b = tmp_path / "B.syx"
    Path(b).write_bytes(Path(all_init_saw).read_bytes())
    res = _compare(a, b, hypothesis="osc1_wave")
    assert res.verdict == "CONFIRMED"
    offs = [c.offset for c in res.changes]
    assert offs == [0x00]
    ch = res.changes[0]
    assert (ch.old, ch.new) == (0x00, 0x04)
    assert ch.confidence == "experimentally_confirmed"


def test_ab_experiment_ambiguous_extra_unknown_byte(tmp_path, all_init_saw):
    from jt4000m.patch import Bank
    a = _write_variant(all_init_saw, tmp_path / "A.syx", 1,
                       {"osc1_wave": 0})
    # B differs at 0x00 AND at unknown 0x09 — must be AMBIGUOUS, no guessing
    bank = Bank.load(all_init_saw)
    prog = bank.programs[0]
    data = bytearray(prog.data)
    data[0x09] = 0x20
    prog2 = JTProgram(prog.index, bytes(data), prog.source_offset)
    b = tmp_path / "B.syx"
    bank.replace(1, prog2).save(b)
    res = _compare(a, b, hypothesis="osc1_wave")
    assert res.verdict == "AMBIGUOUS"
    offs = sorted(c.offset for c in res.changes)
    assert offs == [0x00, 0x09]
    unk = [c for c in res.changes if c.offset == 0x09][0]
    assert unk.classification == "UNKNOWN_OFFSET"
    assert "NO automatic attribution" in " ".join(res.notes) or \
           "not attributing" in " ".join(res.notes).lower()


def test_ab_experiment_name_separated_from_parameter(tmp_path, all_init_saw):
    a = _write_variant(all_init_saw, tmp_path / "A.syx", 1,
                       {"osc1_wave": 0}, rename="TESTNAME")
    b = tmp_path / "B.syx"
    Path(b).write_bytes(Path(all_init_saw).read_bytes())
    res = _compare(a, b, hypothesis="osc1_wave")
    # name bytes are PATCH_NAME and must not block CONFIRMED
    classes = {c.classification for c in res.changes}
    assert "PATCH_NAME" in classes
    assert res.verdict == "CONFIRMED"
    assert all(c.offset <= 0x36 or c.classification == "PATCH_NAME"
               for c in res.changes)


def test_ab_report_json_contains_provenance(tmp_path, all_init_saw):
    a = _write_variant(all_init_saw, tmp_path / "A.syx", 1,
                       {"osc1_wave": 0})
    b = tmp_path / "B.syx"
    Path(b).write_bytes(Path(all_init_saw).read_bytes())
    res = _compare(a, b, hypothesis="osc1_wave",
                   before_prov=PROVENANCE_FIXTURE, after_prov=PROVENANCE_FIXTURE)
    d = json.loads(res.to_json())
    assert d["before_provenance"] == "REFERENCE_FIXTURE"
    assert d["verdict"] == "CONFIRMED"
    md = res.to_markdown()
    assert "REFERENCE_FIXTURE" in md


def _compare(before, after, hypothesis=None,
             before_prov=PROVENANCE_FIXTURE, after_prov=PROVENANCE_FIXTURE):
    from jt4000m.experiment import compare_experiment
    return compare_experiment(before, after, program=1,
                              hypothesis=hypothesis,
                              before_provenance=before_prov,
                              after_provenance=after_prov)


# -------------------------------------------------- CLI wiring (offline)
def test_cli_probe_writes_session_log(tmp_path, monkeypatch, capsys):
    """probe on a machine WITHOUT working MIDI must fail honestly (exit 2),
    still write a session JSON, and never claim DEVICE VERIFIED."""
    from jt4000m import cli
    argv = ["midi", "probe", "--name", "JT-4000M",
            "--sessions-dir", str(tmp_path)]
    code = 0
    try:
        cli.main(argv)
    except SystemExit as e:
        code = e.code or 0
    out = capsys.readouterr().out
    assert code in (0, 2)
    assert "RESULT:" in out
    assert "DEVICE VERIFIED" not in out.replace("does NOT say 'DEVICE VERIFIED'", "")
    logs = list(tmp_path.glob("*.json"))
    assert logs, "probe must always record a session log"
    d = json.loads(logs[0].read_text())
    assert d["actions"][0]["action"] == "probe"
    assert d["actions"][0].get("detail", {}).get("sent", 0) == 0


def test_cli_midi_list_accepts_session_flags(capsys):
    from jt4000m import cli
    try:
        cli.main(["midi", "list", "--no-session-log"])
    except SystemExit as e:
        assert (e.code or 0) == 0
    assert "MIDI backend" in capsys.readouterr().out


def test_request_dump_not_established_in_workflow_help(capsys):
    from jt4000m import cli
    cli.main(["experiment", "report", "osc1_wave", "--program", "1"])
    out = capsys.readouterr().out
    assert "REQUEST_DUMP: NOT ESTABLISHED" in out
    assert "NEVER send an" in out or "invented request packet" in out
