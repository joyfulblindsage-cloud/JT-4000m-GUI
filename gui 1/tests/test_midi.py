from jt4000m.midi import cc_to_parameter, make_cc, parameter_for_cc, parameter_to_cc


def test_cc_encoding():
    assert make_cc(1, 74, 99).bytes() == bytes([0xB0, 74, 99])
    assert make_cc(16, 74, 99).bytes() == bytes([0xBF, 74, 99])


def test_parameter_cc_mapping():
    msg = parameter_to_cc('filter_cutoff', 100, channel=2)
    assert msg.controller == 74
    assert msg.value == 100
    assert msg.channel == 2
    assert parameter_for_cc(74).key == 'filter_cutoff'


def test_ring_mod_cc_is_normalized_to_its_sysex_boolean_value():
    assert cc_to_parameter(96, 64) == ("ring_mod_toggle", 0)
    assert cc_to_parameter(96, 65) == ("ring_mod_toggle", 1)
