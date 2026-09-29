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
