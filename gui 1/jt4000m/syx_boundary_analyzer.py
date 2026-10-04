from __future__ import annotations

import argparse
from pathlib import Path

from .syx import parse


def _common_prefix(items: list[bytes]) -> int:
    if not items:
        return 0
    n = min(map(len, items))
    for i in range(n):
        b = items[0][i]
        if any(x[i] != b for x in items[1:]):
            return i
    return n


def _hex(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


def inspect(path: Path) -> dict:
    raw = path.read_bytes()
    parsed = parse(raw)
    return {
        "path": path,
        "size": len(raw),
        "mode": parsed.mode,
        "header_len": len(parsed.header),
        "header": parsed.header,
        "program_count": len(parsed.programs),
        "program_len": 64,
        "payload_start": 8,
        "payload_end": 8 + len(parsed.programs) * 64,
        "checksum_offset": len(raw) - 2,
        "checksum": raw[-2],
        "trailer": raw[-2:],
        "checksum_ok": parsed.checksum_ok,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="syx-boundary-analyzer",
        description="Compare JT-4000M SysEx framing against known banks.",
    )
    ap.add_argument("files", nargs="+", help=".syx files to compare")
    args = ap.parse_args(argv)

    infos = [inspect(Path(p)) for p in args.files]

    print("JT-4000M SYX BOUNDARY ANALYSIS")
    print("=" * 32)
    for x in infos:
        print(f"\n{x['path']}")
        print(f"  size           : {x['size']}")
        print(f"  mode           : {x['mode']}")
        print(f"  header         : 0..{x['header_len'] - 1} ({x['header_len']} bytes)")
        print(f"  payload        : {x['payload_start']}..{x['payload_end'] - 1} "
              f"({x['program_count']} x {x['program_len']} bytes)")
        print(f"  checksum       : offset {x['checksum_offset']} = 0x{x['checksum']:02X}")
        print(f"  trailer        : {x['checksum_offset']}..{x['size'] - 1} = {_hex(x['trailer'])}")
        print(f"  checksum valid : {x['checksum_ok']}")
        print(f"  header bytes   : {_hex(x['header'])}")

    raws = [Path(p).read_bytes() for p in args.files]
    if len(raws) >= 2:
        cp = _common_prefix(raws)
        print("\nCross-file framing checks")
        print("--------------------------")
        print(f"Common prefix length: {cp} bytes")
        print("Expected bulk layout: 8-byte header + 32*64-byte payload + 2-byte trailer")
        print("Expected total:      2058 bytes")
        for p, raw in zip(args.files, raws):
            ok = (
                len(raw) == 2058
                and raw[:7] == bytes([0xF0, 0x00, 0x20, 0x32, 0x00, 0x01, 0x38])
                and raw[7] == 0x10
                and raw[-1] == 0xF7
            )
            print(f"  {p}: {'BULK FRAME MATCH' if ok else 'DIFFERS'}")

        if cp < 8:
            print("WARNING: files do not share the expected 8-byte header.")
        elif cp >= 8:
            print("Header agreement: all compared files share bytes 0..7.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
