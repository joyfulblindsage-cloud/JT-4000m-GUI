from __future__ import annotations

import argparse
from pathlib import Path

from .syx import parse
from .transport import MidiTransport


def _transport() -> MidiTransport:
    return MidiTransport()


def _port_or_error(transport: MidiTransport, index: int, direction: str):
    ports = transport.list_outputs() if direction == "output" else transport.list_inputs()
    for port in ports:
        if port.index == index:
            return port
    raise ValueError(f"No {direction} MIDI port with index {index}.")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="jt4000m-midi")
    sp = ap.add_subparsers(dest="cmd", required=True)

    sp.add_parser("ports")

    x = sp.add_parser("cc")
    x.add_argument("output", type=int)
    x.add_argument("channel", type=int)
    x.add_argument("controller", type=int)
    x.add_argument("value", type=int)

    x = sp.add_parser("send-syx")
    x.add_argument("output", type=int)
    x.add_argument("file")

    x = sp.add_parser("listen")
    x.add_argument("input", type=int)
    x.add_argument("--timeout", type=float, default=10.0)

    a = ap.parse_args(argv)
    t = _transport()

    try:
        if a.cmd == "ports":
            print("MIDI INPUTS")
            print("-----------")
            for p in t.list_inputs():
                print(f"{p.index}: {p.name}")

            print("\nMIDI OUTPUTS")
            print("------------")
            for p in t.list_outputs():
                print(f"{p.index}: {p.name}")
            return 0

        if a.cmd == "cc":
            if not 1 <= a.channel <= 16:
                ap.error("channel must be 1..16")
            if not 0 <= a.controller <= 127 or not 0 <= a.value <= 127:
                ap.error("CC/value must be 0..127")
            port = _port_or_error(t, a.output, "output")
            report = t.send_cc(port, a.channel, a.controller, a.value)
            print(report.format())
            return 0 if report.api_ok else 1

        if a.cmd == "send-syx":
            data = Path(a.file).read_bytes()
            # Validate before touching MIDI: malformed or foreign SysEx must
            # never be sent accidentally by the lab command.
            parse(data)
            port = _port_or_error(t, a.output, "output")
            report = t.send_sysex(port, data)
            print(report.format())
            return 0 if report.api_ok else 1

        port = _port_or_error(t, a.input, "input")
        t.open_input(port)
        print(f"Listening on input {port.index}: {port.name} for {a.timeout:.1f}s...")
        messages = list(t.receive(a.timeout))
        sysex = [data for _, data in messages if data[:1] == b"\xF0" and data[-1:] == b"\xF7"]
        if not sysex:
            print("RX SysEx: none")
            return 0
        for data in sysex:
            print(f"RX SysEx: {len(data)} bytes")
            print(" ".join(f"{b:02X}" for b in data))
        return 0
    except (OSError, RuntimeError, ValueError) as e:
        ap.error(str(e))
    finally:
        t.close()


if __name__ == "__main__":
    raise SystemExit(main())
