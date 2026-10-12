"""Pure helper for continuous control-to-MIDI value stepping."""


def intermediate_raw_values(previous: int, current: int):
    """Yield every integer value after previous through current.

    UI events can skip raw values when a pointer moves quickly. Sending each
    intermediate value preserves a continuous MIDI CC stream for both knobs
    and sliders. No MIDI mapping or parameter range is inferred here.
    """
    if current > previous:
        return range(previous + 1, current + 1)
    if current < previous:
        return range(previous - 1, current - 1, -1)
    return ()
