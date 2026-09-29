from __future__ import annotations
import csv, json
from dataclasses import asdict
from pathlib import Path
from .model import PARAMETERS


def rows():
    return [asdict(p) for p in PARAMETERS]


def write_csv(path: str | Path):
    rows_ = rows()
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=rows_[0].keys())
        w.writeheader(); w.writerows(rows_)


def write_json(path: str | Path):
    Path(path).write_text(json.dumps(rows(), ensure_ascii=False, indent=2), encoding='utf-8')
