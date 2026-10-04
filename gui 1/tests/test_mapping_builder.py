from pathlib import Path

from jt4000m.mapping_builder import absolute_offset, build_mapping


def test_absolute_offset_formula():
    assert absolute_offset(1, 0x0C) == 0x14
    assert absolute_offset(2, 0x0C) == 0x54
    assert absolute_offset(32, 0x0C) == 0x7D4


def test_mapping_contains_all_32_program_slots(tmp_path):
    doc = build_mapping(Path(__file__).parents[1])
    rows = [r for r in doc["mapping"] if r["parameter"] == "filter_cutoff"]
    assert len(rows) == 32
    assert rows[0]["program"] == 1
    assert rows[0]["relative_offset"] == 0x0C
    assert rows[0]["absolute_offset"] == 0x14
    assert rows[-1]["program"] == 32
    assert rows[-1]["absolute_offset"] == 0x7D4
    assert rows[0]["cc"] == 74
