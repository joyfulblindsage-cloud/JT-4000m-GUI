from pathlib import Path

import pytest

from jt4000m.editor_model import EditorModel


ROOT = Path(__file__).resolve().parents[1]
BANK_PATH = ROOT / "ALL INIT SAW.syx"


def test_load_bytes_accepts_valid_device_bulk_without_disk_path():
    raw = BANK_PATH.read_bytes()
    model = EditorModel()

    bank = model.load_bytes(raw)

    assert len(bank.programs) == 32
    assert model.loaded
    assert model.path is None
    assert model.provenance == "CAPTURED_FROM_DEVICE"
    assert not model.is_dirty()
    assert model.bank.to_sysex() == raw


def test_load_bytes_rejects_bad_checksum_without_replacing_current_bank():
    model = EditorModel()
    model.load_bank(BANK_PATH)
    before = model.bank.to_sysex()
    raw = bytearray(BANK_PATH.read_bytes())
    raw[-2] ^= 1

    with pytest.raises(ValueError, match="checksum mismatch"):
        model.load_bytes(bytes(raw))

    assert model.bank.to_sysex() == before
    assert model.path == BANK_PATH.resolve()
    assert not model.is_dirty()


def test_load_bytes_rejects_single_program_dump():
    single_path = ROOT / "INIT SAW.syx"
    model = EditorModel()

    with pytest.raises(ValueError, match="bulk SysEx dump"):
        model.load_bytes(single_path.read_bytes())
