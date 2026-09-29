# JT-4000M cross-bank analysis

Generated from three 32-program SysEx banks:

- `ALL EMPTY.syx`
- `ALL INIT SAW.syx`
- `Synthmania-EDM-Soundset-JT-4000.syx`

Total sample size: **96 program records × 64 bytes**.

## Interpretation rules

The analyzer reports, for every relative program offset `0x00..0x3F`:

- `unique_count` — number of distinct byte values across all supplied programs;
- `unique_values` — the exact observed values;
- `min` / `max` — observed byte range;
- `frequency` — value → number of programs containing that value;
- per-bank unique values, frequencies, min and max;
- `kind` — a conservative hypothesis, not a confirmed protocol definition.

`UNKNOWN` is used when the current semantic map has no name for the byte. `TEXT` is used for the nine-byte patch name. `LIKELY_ENUM` is used for fields already known to behave as categorical controls. `LIKELY_CONTINUOUS` is used for known numeric controls with enough observed variation. `INVARIANT` means only one value was observed in the supplied sample.

An invariant byte is **not proven unused**. More hardware dumps may reveal changes.

## Important current observations

- `0x09..0x0B` are `00` in all 96 records.
- `0x17..0x2A` are `00` in all 96 records.
- `0x36` is `00` in all 96 records.
- `0x2D` (currently labelled `Portamento Mode`) is `00` in all 96 records, so its current value is invariant in this sample.
- `0x00` (`OSC1 Wave`) shows 7 observed values: `00, 02, 03, 04, 05, 06, 07`. `0x07` is not in the current known waveform table and therefore remains an observed-but-unmapped value.
- `0x01` (`OSC2 Wave`) shows 5 observed values: `00..04` except no `05+` in this sample.
- `0x2B` (`Ring Mod On/Off`) shows exactly `00` and `01`.
- `0x35` (`LFO1 Destination`) shows exactly `00` and `01`.
- The name occupies `0x37..0x3F` and is analyzed as text rather than as numeric control data.

The two synthetic banks (`ALL EMPTY` and `ALL INIT SAW`) intentionally repeat one patch 32 times, so frequency counts are strongly weighted toward their repeated values. `Synthmania` supplies the main source of natural variation in this three-bank experiment.
