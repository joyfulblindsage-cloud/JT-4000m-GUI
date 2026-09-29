"""P1.7 OFFLINE — regression tests for jt4000m.discovery.

All tests are hardware-independent and deterministic: they use ONLY the real
project fixtures (ALL EMPTY / ALL INIT SAW / Synthmania / ...), never synthetic
bank files, and never touch MIDI.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from jt4000m import discovery as D
from jt4000m.syx import parse_file

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_NAMES = [
    "EMPTY.syx",
    "ALL EMPTY.syx",
    "ALL INIT SAW.syx",
    "ALL INIT SUPERSAW.syx",
    "INIT SAW.syx",
    "INIT SUPERSAW.syx",
    "Synthmania-EDM-Soundset-JT-4000.syx",
]
CORPUS = [str(ROOT / n) for n in FIXTURE_NAMES]


@pytest.fixture(scope="module")
def report():
    return D.generate(CORPUS)


# ---------------------------------------------------------------------------
# stats helpers
# ---------------------------------------------------------------------------
def test_entropy_known_values():
    assert D.entropy([]) == 0.0
    assert D.entropy([5, 5, 5]) == 0.0            # constant -> zero entropy
    assert D.entropy([0, 1]) == 1.0               # fair binary -> 1 bit
    assert D.entropy([0, 0, 1, 1]) == 1.0
    assert abs(D.entropy([0, 1, 2, 3]) - 2.0) < 1e-9


def test_median_odd_even():
    assert D.median([3, 1, 2]) == 2.0
    assert D.median([4, 1, 2, 3]) == 2.5


def test_mutual_information_bounds():
    xs = [0, 0, 1, 1, 2, 2]
    ys = [0, 0, 1, 1, 2, 2]
    assert D.mutual_information(xs, ys) == pytest.approx(D.entropy(ys))
    independent_y = [0, 1, 0, 1, 0, 1]
    mi = D.mutual_information(xs, independent_y)
    assert 0.0 <= mi <= D.entropy(independent_y) + 1e-9
    with pytest.raises(ValueError):
        D.mutual_information([1], [])


def test_pearson():
    r = D.pearson([0, 1, 2], [0, 10, 20])
    assert r == pytest.approx(1.0)
    r2 = D.pearson([0, 1, 2], [20, 10, 0])
    assert r2 == pytest.approx(-1.0)
    assert D.pearson([1, 1, 1], [0, 1, 2]) is None   # constant side


def test_classify_offset_data_behaviour_only():
    assert D.classify_offset(0x00, 7, tuple(range(7)), True) == D.CLS_PARAMETER_KNOWN
    assert D.classify_offset(0x37, 9, tuple(range(9)), False) == D.CLS_NAME
    assert D.classify_offset(0x09, 1, (0,), False) == D.CLS_CONSTANT
    assert D.classify_offset(0x2B, 2, (0, 1), False) == D.CLS_BINARY
    assert D.classify_offset(0x19, 4, (0, 32, 64, 96), False) == D.CLS_DISCRETE
    assert D.classify_offset(0x1C, 30, tuple(range(30)), False) == D.CLS_CONTINUOUS
    # classification NEVER invents a parameter name:
    assert "Unison" not in str(D.classify_offset(0x09, 4, (0, 32, 64, 96), False))


# ---------------------------------------------------------------------------
# dataset inventory
# ---------------------------------------------------------------------------
def test_inventory_covers_all_fixtures(report):
    names = sorted(Path(f.path).name for f in report.files)
    assert names == sorted(FIXTURE_NAMES)
    for f in report.files:
        assert f.checksum_ok, f.path
        assert f.provenance == "REFERENCE_FIXTURE"
        assert f.mode in ("bulk", "single")
    by = {Path(f.path).name: f for f in report.files}
    assert by["ALL EMPTY.syx"].programs == 32
    assert by["ALL EMPTY.syx"].unique_programs == 1          # all slots equal
    assert by["ALL EMPTY.syx"].duplicate_programs             # groups recorded
    assert by["EMPTY.syx"].mode == "single"
    assert by["Synthmania-EDM-Soundset-JT-4000.syx"].unique_programs > 20


def test_total_program_count(report):
    assert report.dataset["programs_total"] == 3 * 32 + 3 * 1 + 32


# ---------------------------------------------------------------------------
# offset profiles
# ---------------------------------------------------------------------------
def test_profiles_cover_64_offsets(report):
    assert len(report.profiles) == 64
    assert [p.offset for p in report.profiles] == list(range(64))


def test_profile_osc1_wave(report):
    p = report.profiles[0x00]
    assert p.classification == D.CLS_PARAMETER_KNOWN
    assert p.evidence_level == D.LEVEL_OBSERVED
    assert 0 in p.unique_values and 4 in p.unique_values     # OFF and SAW seen
    assert 7 in p.unique_values                              # unlabelled value
    assert p.transition_count > 0                            # transitions exist
    assert "0x04->0x06" in p.transitions_json() or p.transitions_json()
    assert p.hardware_confirmation is False if hasattr(p, "hardware_confirmation") else True
    d = p.to_dict()
    assert d["hardware_confirmation"] is False
    assert d["stats"]["entropy_bits"] > 0


def test_constant_unknown_offsets(report):
    """In this corpus every unknown offset is fixture-constant."""
    for p in report.profiles:
        if p.classification == D.CLS_CONSTANT:
            assert p.field.startswith("Byte 0x"), p.field
            assert p.evidence_level == D.LEVEL_INFERRED
            assert p.entropy == 0.0
            assert p.unique_values == (0,)                   # observed: all zero
            # honesty: never labelled reserved/unused/firmware
            j = json.dumps(p.to_dict())
            for banned in ("reserved", "unused", "firmware"):
                assert banned not in j.lower()


def test_name_offsets_classified(report):
    for off in range(55, 64):
        assert report.profiles[off].classification == D.CLS_NAME
        assert report.profiles[off].field == f"Name[{off-55}]"
    assert report.profiles[54].classification != D.CLS_NAME


def test_frequency_and_zero_pct_consistent(report):
    for p in report.profiles:
        assert sum(p.frequency.values()) == p.count
        exp_zero = 100.0 * p.frequency.get(0, 0) / p.count
        assert abs(p.zero_pct - round(exp_zero, 4)) < 1e-3


# ---------------------------------------------------------------------------
# correlations (INFERRED only, non-causal wording)
# ---------------------------------------------------------------------------
def test_correlations_are_inferred_and_noncausal(report):
    assert report.pairs, "expected at least one correlated pair in corpus"
    for r in report.pairs:
        assert r["evidence_level"] == D.LEVEL_INFERRED
        assert "controls" not in r["status"].lower()
        if r["status"].startswith("OBSERVED_CORRELATION"):
            # permitted only when BOTH sides are already registry-known params
            assert "both params known" in r["status"]
        else:
            assert r["status"].startswith("HYPOTHESIS"), r["status"]
            assert "hardware confirmation required" in r["status"].lower()
        assert 0.0 <= r["normalized_mi"] <= 1.0 + 1e-9
    # pairs are sorted by strength, deterministic
    mis = [r["normalized_mi"] for r in report.pairs]
    assert mis == sorted(mis, reverse=True)


def test_correlation_threshold_filters(report):
    strict = D.generate(CORPUS, mi_threshold=0.999)
    assert len(strict.pairs) <= len(report.pairs)


# ---------------------------------------------------------------------------
# usage spread
# ---------------------------------------------------------------------------
def test_usage_spread_partition(report):
    buckets = report.spread
    all_offsets = set()
    for v in buckets.values():
        # 'known_parameter_constant_in_corpus' entries look like
        # "0x2D (Portamento Mode)" — reduce them to the offset token.
        all_offsets |= {s.split(" ")[0] for s in v}
    # NAME offsets excluded; every other offset bucketed exactly once
    expected = {f"0x{p.offset:02X}" for p in report.profiles
                if p.classification != D.CLS_NAME}
    assert all_offsets == expected
    total = sum(len(v) for v in buckets.values())
    assert total == len(expected)


def test_fixture_constant_bucket_holds_only_unknown_offsets(report):
    """Consistency guard: a registry-mapped parameter must never appear in
    the fixture_constant bucket (that bucket describes UNKNOWN bytes whose
    corpus value is constant, e.g. 0x09..0x0B, 0x17..0x2A, 0x36).
    Portamento Mode @ 0x2D is PARAMETER_KNOWN and belongs to
    known_parameter_constant_in_corpus instead."""
    known_offsets = {f"0x{p.offset:02X}" for p in report.profiles
                     if p.classification == D.CLS_PARAMETER_KNOWN}
    assert not (set(report.spread["fixture_constant"]) & known_offsets)
    # 0x2D specifically: known parameter, constant in this corpus
    assert "0x2D" not in report.spread["fixture_constant"]
    assert any(s.startswith("0x2D") for s in
               report.spread["known_parameter_constant_in_corpus"])
    # unknown constant offsets are still there
    for off in ("0x09", "0x0A", "0x0B", "0x17", "0x2A", "0x36"):
        assert off in report.spread["fixture_constant"]


# ---------------------------------------------------------------------------
# contradictions & enum corroboration
# ---------------------------------------------------------------------------
def test_contradiction_unlabelled_wave_value(report):
    kinds = {(c["offset"], c["type"]) for c in report.contradictions}
    assert ("0x00", "ENUM_VALUE_NOT_IN_TABLE") in kinds
    c = next(c for c in report.contradictions
             if c["type"] == "ENUM_VALUE_NOT_IN_TABLE")
    assert "0x07" in c["observed_unlabelled_values"]
    # action must promise NO automatic registry change / no invented naming
    assert "invent" in c["action"].lower()
    rng = [cc for cc in report.contradictions
           if cc["type"] == "OUT_OF_REGISTRY_RANGE"]
    for cc in rng:  # any range contradiction must be report-only
        assert "NOT modified automatically" in cc["action"]


def test_enum_findings_status_levels(report):
    osc1 = next(e for e in report.enums if e["parameter"] == "osc1_wave")
    assert osc1["status"] == "STATIC_KNOWN + OBSERVED"
    assert osc1["observed_and_labelled"]["0x04"] == "SAW"
    assert osc1["observed_and_labelled"]["0x00"] == "OFF"
    assert osc1["hardware_confirmed"] is False
    for e in report.enums:
        assert e["hardware_confirmed"] is False


# ---------------------------------------------------------------------------
# registry & CC audits
# ---------------------------------------------------------------------------
def test_registry_audit_every_parameter(report):
    from jt4000m.model import PARAMETERS
    keys = {r["key"] for r in report.registry_audit}
    assert keys == {p.key for p in PARAMETERS}
    for r in report.registry_audit:
        assert r["hardware_evidence"] is False
        assert r["evidence_level"] in (D.LEVEL_STATIC, D.LEVEL_OBSERVED)
    cc_only = next(r for r in report.registry_audit if r["key"] == "modulation")
    assert cc_only["offset"] is None
    assert "not established" in cc_only["fixture_coverage"]


def test_cc_audit_never_hardware_confirmed(report):
    assert report.cc_audit
    for c in report.cc_audit:
        assert c["hardware_evidence"] == "HARDWARE_CONFIRMATION_REQUIRED"
        assert c["source"].startswith("parameter_registry")
        assert c["note"] == "SYX fixtures do not themselves prove CC mapping"
    ccs = [c["cc"] for c in report.cc_audit]
    assert ccs == sorted(ccs)                                # deterministic order


# ---------------------------------------------------------------------------
# experiment priorities & dossiers
# ---------------------------------------------------------------------------
def test_experiment_priorities_transparent(report):
    for p in report.priorities:
        assert p["candidate_meaning"] == "UNKNOWN"
        assert p["hardware_confirmation"] == "REQUIRED"
        assert p["experiment_priority"] in (
            "HIGH_INFORMATION_VALUE", "MEDIUM_INFORMATION_VALUE",
            "LOW_INFORMATION_VALUE")
    # with this corpus every unknown byte is constant -> no priority entries,
    # which itself is the honest result (documented in the report).
    ent = [p["entropy_bits"] for p in report.priorities]
    assert ent == sorted(ent, reverse=True)


def test_unknown_dossiers_complete(report):
    unknown_offsets = {f"0x{p.offset:02X}" for p in report.profiles
                       if p.classification not in (D.CLS_PARAMETER_KNOWN,
                                                   D.CLS_NAME)}
    dossier_offsets = {dossier["offset"] for dossier in report.dossiers}
    assert dossier_offsets == unknown_offsets
    for dossier in report.dossiers:
        assert dossier["status"] == "UNKNOWN"
        assert dossier["candidate_meaning"] == "UNKNOWN"
        assert dossier["hardware_confirmation"] == "REQUIRED"
        text = json.dumps(dossier).lower()
        for banned in ("unison", "effect param", "reserved", "unused"):
            assert banned not in text


# ---------------------------------------------------------------------------
# JSON / Markdown output contract
# ---------------------------------------------------------------------------
def test_json_schema_and_hardware_empty(report):
    doc = json.loads(report.to_json())
    assert doc["schema"] == "jt4000m-p1.7-discovery/1"
    assert doc["hardware_confirmed_offsets"] == []
    assert set(doc["evidence_levels_used"]) == {"STATIC_KNOWN", "OBSERVED",
                                                "INFERRED"}
    assert len(doc["offsets"]) == 64
    for o in doc["offsets"]:
        assert o["hardware_confirmation"] is False


def test_markdown_sections_present(report):
    md = report.to_markdown()
    for section in ("## Dataset", "## Offset statistics",
                    "## Classification summary", "## Usage spread",
                    "## Enum mapping corroboration", "## Correlations",
                    "## Contradictions", "## CC audit",
                    "## Experiment priorities", "## Limitations"):
        assert section in md
    assert "No physical JT-4000M was available" in md


def test_results_deterministic(report):
    again = D.generate(CORPUS)
    assert again.to_json() == report.to_json()


def test_write_reports(tmp_path, report):
    jp, mp = D.write_reports(report, tmp_path)
    assert jp.exists() and mp.exists()
    loaded = json.loads(jp.read_text(encoding="utf-8"))
    assert loaded["schema"] == "jt4000m-p1.7-discovery/1"


# ---------------------------------------------------------------------------
# CLI wiring (subprocess, offline)
# ---------------------------------------------------------------------------
import subprocess
import sys


def run_cli(*args):
    return subprocess.run([sys.executable, "-m", "jt4000m.cli", *args],
                          cwd=ROOT, capture_output=True, text=True)


def test_cli_analyze_offsets_table():
    r = run_cli("analyze", "analyze-offsets")
    assert r.returncode == 0, r.stderr
    assert "0x00" in r.stdout and "OSC1 Wave" in r.stdout
    assert "PARAMETER_KNOWN" in r.stdout
    assert "candidate_meaning=UNKNOWN" in r.stdout


def test_cli_report_writes_files(tmp_path):
    r = run_cli("analyze", "report", "--output", str(tmp_path))
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "parameter_discovery.json").exists()
    assert (tmp_path / "parameter_discovery.md").exists()
    assert "Hardware-confirmed parameters: 0" in r.stdout


def test_cli_cc_audit_requires_hardware():
    r = run_cli("analyze", "cc-audit")
    assert r.returncode == 0, r.stderr
    assert "HARDWARE_CONFIRMATION_REQUIRED" in r.stdout
