from jt4000m.syx import parse_file
from jt4000m.model import decode_program, set_parameter, set_name


def test_decode_and_mutate():
    p = parse_file('fixtures/ALL INIT SAW.syx').programs[0]
    d = decode_program(p)
    assert d['osc1_wave'] == 4
    assert d['name'] == 'INIT SAW'
    p2 = set_parameter(p, 'filter_cutoff', 99)
    assert p2.data[12] == 99
    p3 = set_name(p2, 'TEST')
    assert p3.name == 'TEST'


def test_unresolved_parameter_does_not_fake_offset():
    p = parse_file('fixtures/ALL INIT SAW.syx').programs[0]
    try:
        set_parameter(p, 'modulation', 10)
    except ValueError as e:
        assert 'no established SysEx offset' in str(e)
    else:
        raise AssertionError('expected unresolved SysEx offset error')
