from jt4000m.gesture_steps import intermediate_raw_values


def test_live_gesture_steps_include_every_ascending_raw_value():
    assert list(intermediate_raw_values(10, 15)) == [11, 12, 13, 14, 15]


def test_live_gesture_steps_include_every_descending_raw_value():
    assert list(intermediate_raw_values(15, 10)) == [14, 13, 12, 11, 10]


def test_live_gesture_steps_are_empty_when_value_does_not_change():
    assert list(intermediate_raw_values(64, 64)) == []
