# JT-4000M Experiment Report

- timestamp: `2026-09-29T09:12:42+00:00`
- program: `01`
- before: `fixtures/ALL EMPTY.syx` (REFERENCE_FIXTURE)
- after: `fixtures/ALL INIT SAW.syx` (REFERENCE_FIXTURE)
- hypothesis: `osc1_wave`
- expected CC: 24
- verdict: **CONFIRMED**
- evidence: `A/B_SYSEX`

| offset | old | new | field | class | confidence | semantic |
|--------|-----|-----|-------|-------|------------|----------|
| 0x00 | 00 | 04 | OSC1 Wave | KNOWN_PARAMETER | experimentally_confirmed | OFF → SAW |
| 0x37 | 45 | 49 | Name[0] | PATCH_NAME | observed | 'E' → 'I' |
| 0x38 | 4D | 4E | Name[1] | PATCH_NAME | observed | 'M' → 'N' |
| 0x39 | 50 | 49 | Name[2] | PATCH_NAME | observed | 'P' → 'I' |
| 0x3B | 59 | 20 | Name[4] | PATCH_NAME | observed | 'Y' → ' ' |
| 0x3C | 20 | 53 | Name[5] | PATCH_NAME | observed | ' ' → 'S' |
| 0x3D | 20 | 41 | Name[6] | PATCH_NAME | observed | ' ' → 'A' |
| 0x3E | 20 | 57 | Name[7] | PATCH_NAME | observed | ' ' → 'W' |

## Notes
- Only the hypothesised offset changed (name bytes treated as PATCH_NAME); parameter mapping EXPERIMENTALLY CONFIRMED.

> TRANSPORT VERIFIED and DEVICE BEHAVIOR VERIFIED are
> different claims; this report describes captured state
> differences only.