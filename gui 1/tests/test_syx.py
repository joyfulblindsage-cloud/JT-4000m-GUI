from pathlib import Path
from jt4000m.syx import parse_file, checksum, serialize_single, serialize_bulk
ROOT=Path(__file__).resolve().parents[1]
FIX=ROOT/'fixtures'

def test_single_parser_is_75_bytes_and_name_is_not_truncated():
    s=parse_file(FIX/'EMPTY.syx')
    assert s.mode=='single' and len(s.raw)==75
    assert s.programs[0].name=='EMPTY'
    assert s.programs[0].data[55:64]==b'EMPTY    '
    assert s.reserved==b'\x00'
    assert s.checksum_value==0x58 and s.checksum_ok

def test_bulk_parser_and_checksum():
    s=parse_file(FIX/'ALL EMPTY.syx')
    assert s.mode=='bulk' and len(s.programs)==32
    assert all(p.name=='EMPTY' for p in s.programs)
    assert s.checksum_value==0 and s.checksum_ok

def test_bulk_init_saw():
    s=parse_file(FIX/'ALL INIT SAW.syx')
    assert all(p.name=='INIT SAW' for p in s.programs)
    assert s.programs[0].data[0]==4

def test_roundtrip_single():
    s=parse_file(FIX/'EMPTY.syx')
    assert serialize_single(s.programs[0])==s.raw

def test_roundtrip_bulk():
    s=parse_file(FIX/'ALL INIT SAW.syx')
    assert serialize_bulk(s.programs)==s.raw

def test_cross_bank_map_has_64_offsets():
    from jt4000m.analyzer import cross_bank
    banks = [
        ('ALL EMPTY.syx', parse_file(FIX/'ALL EMPTY.syx')),
        ('ALL INIT SAW.syx', parse_file(FIX/'ALL INIT SAW.syx')),
        ('Synthmania-EDM-Soundset-JT-4000.syx', parse_file(ROOT.parent/'Synthmania-EDM-Soundset-JT-4000.syx')),
    ]
    rows = cross_bank(banks)
    assert len(rows) == 64
    assert rows[0]['field'] == 'OSC1 Wave'
    assert rows[0]['unique_count'] == 7
    assert rows[9]['kind'] == 'UNKNOWN'
    assert rows[9]['unique_count'] == 1
    assert rows[53]['kind'] == 'LIKELY_ENUM'
    assert rows[55]['kind'] == 'TEXT'
