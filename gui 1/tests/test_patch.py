from pathlib import Path
from jt4000m.syx import parse_file
from jt4000m.patch import Bank, JTProgram, program_to_single

FIX = Path('fixtures')


def test_bank_edit_recalculates_checksum_and_preserves_unknown_bytes():
    s = parse_file(FIX / 'ALL INIT SAW.syx')
    bank = Bank.from_sysex(s)
    original = bank.get(1).data
    edited = bank.set_parameter(1, 'filter_cutoff', 99).set_name(1, 'TEST')
    data = edited.get(1).data
    assert data[12] == 99
    assert data[55:64] == b'TEST     '
    for off in list(range(64)):
        if off not in (12, *range(55, 64)):
            assert data[off] == original[off]
    out = edited.to_sysex()
    reparsed = __import__('jt4000m.syx', fromlist=['parse']).parse(out)
    assert reparsed.checksum_ok
    assert reparsed.programs[0].name == 'TEST'
    assert reparsed.programs[0].data[12] == 99


def test_single_conversion():
    p = JTProgram.from_program(parse_file(FIX / 'EMPTY.syx').programs[0])
    from jt4000m.syx import parse
    assert parse(program_to_single(p)).programs[0].name == 'EMPTY'
