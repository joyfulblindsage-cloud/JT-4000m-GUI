"""Shared pytest fixtures for jt4000m-editor.

P1.5 safety rule: automated tests NEVER touch real MIDI hardware. Tests that
need a transport use the injected FakeMidiBackend below; tests that want to
talk to a physical JT-4000M live in tests/hardware/ and are skipped unless
JT4000M_HARDWARE_TEST=1 is set explicitly by a human operator.
"""
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def all_empty() -> Path:
    return FIXTURES / "ALL EMPTY.syx"


@pytest.fixture
def all_init_saw() -> Path:
    return FIXTURES / "ALL INIT SAW.syx"


@pytest.fixture
def synthmania() -> Path:
    return FIXTURES / "Synthmania-EDM-Soundset-JT-4000.syx"


class FakeMidiPort:
    """rtmidi-shaped fake port object recording everything it is told to do."""

    def __init__(self, backend, direction):
        self._backend = backend
        self._direction = direction
        self.opened_index = None
        self.sent = []

    def get_ports(self):
        return [p.name for p in self._backend.ports
                if p.direction == self._direction]

    def open_port(self, index):
        self.opened_index = index

    def set_buffer_size(self, size):
        pass

    def send_message(self, data):
        self.sent.append(bytes(data))
        self._backend.tx_log.append(bytes(data))

    def get_message(self):
        if self._backend.rx_queue:
            return (0.0, list(self._backend.rx_queue.pop(0)))
        return None

    def close_port(self):
        self.opened_index = None


class FakeMidiBackend:
    """Deterministic offline stand-in for python-rtmidi's module interface."""

    def __init__(self, inputs=("JT-4000M MICRO",),
                 outputs=("Microsoft GS Wavetable Synth", "JT-4000M MICRO"),
                 rx=None):
        from jt4000m.transport import PortInfo
        self.ports = ([PortInfo(i, n, "input") for i, n in enumerate(inputs)]
                      + [PortInfo(i, n, "output") for i, n in enumerate(outputs)])
        self.tx_log = []
        self.rx_queue = list(rx or [])
        self.last_in = None
        self.last_out = None

        backend = self

        class MidiIn(FakeMidiPort):
            def __init__(self):
                super().__init__(backend, "input")
                backend.last_in = self

        class MidiOut(FakeMidiPort):
            def __init__(self):
                super().__init__(backend, "output")
                backend.last_out = self

        self.MidiIn = MidiIn
        self.MidiOut = MidiOut


@pytest.fixture
def fake_backend():
    return FakeMidiBackend()


@pytest.fixture
def fake_transport(fake_backend):
    from jt4000m.transport import MidiTransport
    return MidiTransport(backend=fake_backend, backend_name="rtmidi")


# --------------------------------------------------------------------------
# GUI test hygiene (P1.28 follow-up): deterministic MIDI RX pump in tests.
#
# Root cause of the p127 RX-projection order-dependent flakiness: when a GUI
# test connects MIDI through the production path, connect_midi() starts the
# Tk `after()` RX pump.  Any pending rx_queue packets are then drained by the
# *timer* whenever some other test pumps the event loop (update /
# update_idletasks / event_generate) — including inside teardown destroy() of
# an EARLIER app whose transport still shares the same FakeMidiBackend.  A
# later test that drives app._poll_midi_once() deterministically can then find
# its packets already consumed ("sometimes passes" behavior).
#
# Fix scope decision: gui.py is production code and its timer pump is correct
# runtime behavior, so it must NOT be disabled at the app level.  Instead this
# opt-in autouse fixture monkeypatches Editor.start_midi_polling into a no-op
# for the whole duration of an opted-in module (installed before any test in
# that module connects MIDI), while leaving the deterministic manual pump
# (_poll_midi_once) untouched.  It activates only when the test module
# explicitly sets `midi_pump_control = True`; non-opted-in suites are
# unaffected.
# --------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _deterministic_midi_pump(request):
    """Neutralize the residual Tk MIDI RX timer pump in opted-in GUI modules.

    Determinism strategy (P1.28 follow-up): production gui.py must keep its
    real after() pump (correct runtime behavior), so instead we make the pump
    a NO-OP for the whole duration of an opted-in test module by monkeypatching
    `Editor.start_midi_polling` before any test in that module connects MIDI.
    connect_midi() then completes normally (status/logging unchanged), but no
    timer callback is ever scheduled — rx_queue draining is driven ONLY through
    the deterministic `_poll_midi_once()` hook.  This removes both failure
    modes of a teardown-only guard: (a) a leftover pump firing *during* a test
    while another earlier app pumps the event loop, and (b) destroyed-Tk apps
    whose pending timers cannot be cancelled anymore.

    Module-scoped opt-out semantics: the patch is installed once per module
    (first test) and restored at session teardown, because pytest function
    fixtures undo monkeypatches in reverse order — restoring it after every
    single test would re-arm the pump for the next test in the same module.
    Non-opted-in modules (all pre-existing GUI suites) are completely
    unaffected.  Never raises when tkinter/Editor is unavailable.
    """
    module = getattr(request.node, "module", None)
    if module is None or not getattr(module, "midi_pump_control", False):
        yield
        return
    if not getattr(module, "_midi_pump_patched", False):
        try:
            from jt4000m.gui import Editor as _EditorApp
        except Exception:                  # no Tk / display-less environment
            yield
            return
        _EditorApp.start_midi_polling = lambda self, interval_ms=30: None
        module._midi_pump_patched = True
        _SESSION_PATCHED.append(_EditorApp)
    yield


# Editor classes patched by _deterministic_midi_pump during this session;
# restored at teardown purely for hygiene (pytest already ends the run).
_SESSION_PATCHED = []


@pytest.fixture(scope="session", autouse=True)
def _restore_pumped_classes():
    yield
    for cls in _SESSION_PATCHED:
        try:
            del cls.start_midi_polling     # unshadow the class method
        except AttributeError:
            pass
    _SESSION_PATCHED.clear()
