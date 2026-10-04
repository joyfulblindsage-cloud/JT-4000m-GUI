from __future__ import annotations

import argparse
from pathlib import Path

from .transport import MidiTransport


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="syx-capture",
        description="Capture one raw JT-4000M SysEx dump without changing MidiTransport.",
    )
    ap.add_argument("--input", type=int, default=0, help="MIDI input index")
    ap.add_argument("--output", required=True, help="Output .syx filename")
    ap.add_argument("--timeout", type=float, default=15.0)
    args = ap.parse_args(argv)

    t = MidiTransport()
    try:
        ports = t.list_inputs()
        port = next((p for p in ports if p.index == args.input), None)
        if port is None:
            ap.error(f"No MIDI input with index {args.input}.")
        t.open_input(port)
        print(f"Waiting on input {port.index}: {port.name}")
        print(f"Capture timeout: {args.timeout:.1f}s")
        print("Now use JT-4000M: PROG -> BULK SYX SEND")
        print("The first complete SysEx dump will be saved verbatim.")

        messages = list(t.receive(args.timeout))
        sysex = [
            data for _, data in messages
            if data[:1] == b"\xF0" and data[-1:] == b"\xF7"
        ]

        if not sysex:
            print("No complete SysEx received.")
            return 1

        if len(sysex) > 1:
            print(f"Warning: received {len(sysex)} SysEx messages; saving the first.")

        data = bytes(sysex[0])
        path = Path(args.output)
        path.write_bytes(data)

        print(f"Saved: {path}")
        print(f"Bytes: {len(data)}")
        print("Header: " + " ".join(f"{b:02X}" for b in data[:8]))
        print("Trailer: " + " ".join(f"{b:02X}" for b in data[-2:]))
        return 0
    except (OSError, RuntimeError, ValueError) as e:
        ap.error(str(e))
    finally:
        t.close()


if __name__ == "__main__":
    raise SystemExit(main())
