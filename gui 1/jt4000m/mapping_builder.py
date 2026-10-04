"""JT-4000M parameter/offset mapping export.

Builds a flattened, machine-readable mapping from the existing project
knowledge base. It deliberately does not invent meanings for unknown bytes.

The core evidence remains in jt4000m.model + jt4000m.knowledge; this module
only joins it to the fixed 32-program bulk layout:

    absolute = 0x08 + (program - 1) * 0x40 + relative_offset

Hardware confirmation is taken only from the existing evidence log when that
log contains CAPTURED_FROM_DEVICE / experimental records.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from .knowledge import (
    CONF_HW,
    STATUS_KNOWN,
    STATUS_NAME,
    STATUS_UNKNOWN,
    generate,
)
from .syx import HEADER_LEN, PROGRAM_LEN


BULK_PROGRAMS = 32
BULK_HEADER_LEN = HEADER_LEN
BULK_TRAILER_LEN = 2


def absolute_offset(program: int, relative_offset: int) -> int:
    if not 1 <= program <= BULK_PROGRAMS:
        raise ValueError(f"program must be 1..{BULK_PROGRAMS}")
    if not 0 <= relative_offset < PROGRAM_LEN:
        raise ValueError(f"relative_offset must be 0..{PROGRAM_LEN - 1:#x}")
    return BULK_HEADER_LEN + (program - 1) * PROGRAM_LEN + relative_offset


def build_mapping(base: str | Path = ".", fixtures=None) -> dict:
    base = Path(base)
    report = generate(base, fixtures)
    rows = []

    for offset_row in report.offsets:
        if offset_row.status not in (STATUS_KNOWN, STATUS_NAME):
            continue
        for program in range(1, BULK_PROGRAMS + 1):
            rel = offset_row.offset
            rows.append(
                {
                    "program": program,
                    "relative_offset": rel,
                    "absolute_offset": absolute_offset(program, rel),
                    "parameter": offset_row.parameter_key or "",
                    "label": offset_row.field,
                    "kind": offset_row.kind or "",
                    "cc": "" if offset_row.cc is None else offset_row.cc,
                    "status": offset_row.status,
                    "confidence": offset_row.confidence,
                    "hardware_confirmed": offset_row.confidence == CONF_HW,
                    "fixture_constant": offset_row.fixture_constant,
                    "observed_min": offset_row.min,
                    "observed_max": offset_row.max,
                    "evidence_sources": ";".join(offset_row.evidence_sources),
                    "notes": offset_row.notes,
                }
            )

    return {
        "schema": "jt4000m-mapping/1",
        "layout": {
            "header_len": BULK_HEADER_LEN,
            "programs": BULK_PROGRAMS,
            "program_len": PROGRAM_LEN,
            "trailer_len": BULK_TRAILER_LEN,
            "total_len": BULK_HEADER_LEN + BULK_PROGRAMS * PROGRAM_LEN + BULK_TRAILER_LEN,
            "absolute_formula": "0x08 + (program - 1) * 0x40 + relative_offset",
        },
        "source": {
            "type": "jt4000m.knowledge",
            "base": str(base),
            "fixtures": list(fixtures) if fixtures else None,
            "hardware_confirmation_rule": (
                "Only evidence-log CAPTURED_FROM_DEVICE records may produce "
                "hardware_confirmed=true."
            ),
        },
        "mapping": rows,
        "unknown_offsets": [
            {
                "relative_offset": r.offset,
                "label": r.field,
                "status": STATUS_UNKNOWN,
                "confidence": r.confidence,
                "observed_values": [f"0x{v:02X}" for v in r.unique_values],
            }
            for r in report.offsets
            if r.status == STATUS_UNKNOWN
        ],
        "cc_mapping": report.cc_table,
        "conflicts": report.conflicts,
    }


def write_outputs(doc: dict, output_dir: str | Path, stem: str = "mapping") -> tuple[Path, Path]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / f"{stem}.json"
    csv_path = out / f"{stem}.csv"

    json_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True),
                         encoding="utf-8")

    rows = doc["mapping"]
    fieldnames = list(rows[0]) if rows else [
        "program", "relative_offset", "absolute_offset", "parameter", "label",
        "kind", "cc", "status", "confidence", "hardware_confirmed",
        "fixture_constant", "observed_min", "observed_max",
        "evidence_sources", "notes",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return csv_path, json_path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m jt4000m.mapping_builder",
        description="Export JT-4000M CC/SysEx mapping with all 32 absolute offsets.",
    )
    parser.add_argument(
        "--base",
        default=".",
        help="project data root containing the jt4000m fixtures/evidence (default: .)",
    )
    parser.add_argument(
        "--fixture",
        action="append",
        dest="fixtures",
        help="limit analysis to a named fixture; may be repeated",
    )
    parser.add_argument("--output-dir", default="analysis", help="output directory")
    parser.add_argument("--stem", default="mapping", help="output filename stem")
    args = parser.parse_args(argv)

    doc = build_mapping(args.base, args.fixtures)
    csv_path, json_path = write_outputs(doc, args.output_dir, args.stem)

    print(f"Wrote {csv_path}")
    print(f"Wrote {json_path}")
    print(f"Mapping rows: {len(doc['mapping'])}")
    print(f"Unknown offsets: {len(doc['unknown_offsets'])}")
    print(f"Conflicts: {len(doc['conflicts'])}")
    print("Hardware-confirmed rows:",
          sum(1 for r in doc["mapping"] if r["hardware_confirmed"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
