# P1.7 — Offline Parameter Discovery & Statistical RE

**No physical JT-4000M was available. Zero findings in this report are HARDWARE_CONFIRMED.**

## Dataset
| file | mode | programs | bytes | checksum | provenance | unique patches |
|---|---|---|---|---|---|---|
| EMPTY.syx | single | 1 | 75 | 88/OK | REFERENCE_FIXTURE | 1 |
| ALL EMPTY.syx | bulk | 32 | 2058 | 0/OK | REFERENCE_FIXTURE | 1 |
| ALL INIT SAW.syx | bulk | 32 | 2058 | 0/OK | REFERENCE_FIXTURE | 1 |
| ALL INIT SUPERSAW.syx | bulk | 32 | 2058 | 64/OK | REFERENCE_FIXTURE | 1 |
| INIT SAW.syx | single | 1 | 75 | 4/OK | REFERENCE_FIXTURE | 1 |
| INIT SUPERSAW.syx | single | 1 | 75 | 82/OK | REFERENCE_FIXTURE | 1 |
| Synthmania-EDM-Soundset-JT-4000.syx | bulk | 32 | 2058 | 49/OK | REFERENCE_FIXTURE | 32 |

## Offset statistics (0x00–0x3F)
| off | field | class | level | N uniq | ent | min | max | zero% | trans |
|---|---|---|---|---|---|---|---|---|---|
| 0x00 | OSC1 Wave | PARAMETER_KNOWN | OBSERVED | 7 | 2.118 | 0x00 | 0x07 | 25.2 | 29 |
| 0x01 | OSC2 Wave | PARAMETER_KNOWN | OBSERVED | 5 | 0.968 | 0x00 | 0x04 | 83.2 | 27 |
| 0x02 | OSC1 PWM / Detune / FM | PARAMETER_KNOWN | OBSERVED | 22 | 2.374 | 0x00 | 0x5B | 9.2 | 27 |
| 0x03 | OSC2 PWM | PARAMETER_KNOWN | OBSERVED | 15 | 0.945 | 0x00 | 0x4C | 88.5 | 22 |
| 0x04 | OSC1 Coarse | PARAMETER_KNOWN | OBSERVED | 8 | 0.791 | 0x00 | 0x18 | 87.8 | 21 |
| 0x05 | OSC1 Fine | PARAMETER_KNOWN | OBSERVED | 16 | 1.009 | 0x00 | 0x39 | 87.8 | 23 |
| 0x06 | OSC2 Coarse | PARAMETER_KNOWN | OBSERVED | 7 | 0.802 | 0x00 | 0x18 | 87.8 | 22 |
| 0x07 | OSC2 Fine | PARAMETER_KNOWN | OBSERVED | 12 | 1.240 | 0x00 | 0x19 | 15.3 | 22 |
| 0x08 | OSC Balance | PARAMETER_KNOWN | OBSERVED | 9 | 1.168 | 0x40 | 0x77 | 0.0 | 14 |
| 0x09 | Byte 0x09 | CONSTANT | INFERRED | 1 | 0.000 | 0x00 | 0x00 | 100.0 | 0 |
| 0x0A | Byte 0x0A | CONSTANT | INFERRED | 1 | 0.000 | 0x00 | 0x00 | 100.0 | 0 |
| 0x0B | Byte 0x0B | CONSTANT | INFERRED | 1 | 0.000 | 0x00 | 0x00 | 100.0 | 0 |
| 0x0C | Filter Frequency | PARAMETER_KNOWN | OBSERVED | 26 | 1.901 | 0x00 | 0x63 | 0.8 | 30 |
| 0x0D | Filter Resonance | PARAMETER_KNOWN | OBSERVED | 23 | 1.657 | 0x00 | 0x63 | 78.6 | 27 |
| 0x0E | VCF Attack | PARAMETER_KNOWN | OBSERVED | 20 | 1.213 | 0x00 | 0x60 | 85.5 | 25 |
| 0x0F | VCF Decay | PARAMETER_KNOWN | OBSERVED | 22 | 1.710 | 0x00 | 0x63 | 77.9 | 30 |
| 0x10 | VCF Sustain | PARAMETER_KNOWN | OBSERVED | 17 | 1.263 | 0x00 | 0x63 | 84.0 | 25 |
| 0x11 | VCF Release | PARAMETER_KNOWN | OBSERVED | 27 | 1.787 | 0x00 | 0x63 | 77.9 | 28 |
| 0x12 | VCA Attack | PARAMETER_KNOWN | OBSERVED | 18 | 1.087 | 0x00 | 0x48 | 87.0 | 23 |
| 0x13 | VCA Decay | PARAMETER_KNOWN | OBSERVED | 20 | 1.668 | 0x00 | 0x63 | 77.1 | 28 |
| 0x14 | VCA Sustain | PARAMETER_KNOWN | OBSERVED | 21 | 1.438 | 0x00 | 0x63 | 3.8 | 29 |
| 0x15 | VCA Release | PARAMETER_KNOWN | OBSERVED | 21 | 1.777 | 0x00 | 0x4C | 76.3 | 31 |
| 0x16 | VCF Amount | PARAMETER_KNOWN | OBSERVED | 28 | 1.895 | 0x00 | 0x63 | 76.3 | 31 |
| 0x17 | Byte 0x17 | CONSTANT | INFERRED | 1 | 0.000 | 0x00 | 0x00 | 100.0 | 0 |
| 0x18 | Byte 0x18 | CONSTANT | INFERRED | 1 | 0.000 | 0x00 | 0x00 | 100.0 | 0 |
| 0x19 | Byte 0x19 | CONSTANT | INFERRED | 1 | 0.000 | 0x00 | 0x00 | 100.0 | 0 |
| 0x1A | Byte 0x1A | CONSTANT | INFERRED | 1 | 0.000 | 0x00 | 0x00 | 100.0 | 0 |
| 0x1B | Byte 0x1B | CONSTANT | INFERRED | 1 | 0.000 | 0x00 | 0x00 | 100.0 | 0 |
| 0x1C | Byte 0x1C | CONSTANT | INFERRED | 1 | 0.000 | 0x00 | 0x00 | 100.0 | 0 |
| 0x1D | Byte 0x1D | CONSTANT | INFERRED | 1 | 0.000 | 0x00 | 0x00 | 100.0 | 0 |
| 0x1E | Byte 0x1E | CONSTANT | INFERRED | 1 | 0.000 | 0x00 | 0x00 | 100.0 | 0 |
| 0x1F | Byte 0x1F | CONSTANT | INFERRED | 1 | 0.000 | 0x00 | 0x00 | 100.0 | 0 |
| 0x20 | Byte 0x20 | CONSTANT | INFERRED | 1 | 0.000 | 0x00 | 0x00 | 100.0 | 0 |
| 0x21 | Byte 0x21 | CONSTANT | INFERRED | 1 | 0.000 | 0x00 | 0x00 | 100.0 | 0 |
| 0x22 | Byte 0x22 | CONSTANT | INFERRED | 1 | 0.000 | 0x00 | 0x00 | 100.0 | 0 |
| 0x23 | Byte 0x23 | CONSTANT | INFERRED | 1 | 0.000 | 0x00 | 0x00 | 100.0 | 0 |
| 0x24 | Byte 0x24 | CONSTANT | INFERRED | 1 | 0.000 | 0x00 | 0x00 | 100.0 | 0 |
| 0x25 | Byte 0x25 | CONSTANT | INFERRED | 1 | 0.000 | 0x00 | 0x00 | 100.0 | 0 |
| 0x26 | Byte 0x26 | CONSTANT | INFERRED | 1 | 0.000 | 0x00 | 0x00 | 100.0 | 0 |
| 0x27 | Byte 0x27 | CONSTANT | INFERRED | 1 | 0.000 | 0x00 | 0x00 | 100.0 | 0 |
| 0x28 | Byte 0x28 | CONSTANT | INFERRED | 1 | 0.000 | 0x00 | 0x00 | 100.0 | 0 |
| 0x29 | Byte 0x29 | CONSTANT | INFERRED | 1 | 0.000 | 0x00 | 0x00 | 100.0 | 0 |
| 0x2A | Byte 0x2A | CONSTANT | INFERRED | 1 | 0.000 | 0x00 | 0x00 | 100.0 | 0 |
| 0x2B | Ring Mod On/Off | PARAMETER_KNOWN | OBSERVED | 2 | 0.234 | 0x00 | 0x01 | 96.2 | 8 |
| 0x2C | Ring Mod Amount | PARAMETER_KNOWN | OBSERVED | 10 | 0.579 | 0x00 | 0x63 | 93.1 | 15 |
| 0x2D | Portamento Mode | PARAMETER_KNOWN | STATIC_KNOWN | 1 | 0.000 | 0x00 | 0x00 | 100.0 | 0 |
| 0x2E | Portamento Amount | PARAMETER_KNOWN | OBSERVED | 3 | 0.178 | 0x00 | 0x04 | 97.7 | 6 |
| 0x2F | LFO1 Wave | PARAMETER_KNOWN | OBSERVED | 3 | 0.261 | 0x00 | 0x02 | 96.2 | 7 |
| 0x30 | LFO2 Wave | PARAMETER_KNOWN | OBSERVED | 2 | 0.234 | 0x00 | 0x02 | 96.2 | 8 |
| 0x31 | LFO1 Speed | PARAMETER_KNOWN | OBSERVED | 12 | 0.846 | 0x00 | 0x63 | 89.3 | 20 |
| 0x32 | LFO1 Amount | PARAMETER_KNOWN | OBSERVED | 16 | 1.057 | 0x00 | 0x63 | 87.0 | 22 |
| 0x33 | LFO2 Speed | PARAMETER_KNOWN | OBSERVED | 8 | 0.591 | 0x00 | 0x63 | 92.4 | 14 |
| 0x34 | LFO2 Amount | PARAMETER_KNOWN | OBSERVED | 16 | 0.961 | 0x00 | 0x50 | 88.5 | 21 |
| 0x35 | LFO1 Destination | PARAMETER_KNOWN | OBSERVED | 2 | 0.703 | 0x00 | 0x01 | 19.1 | 12 |
| 0x36 | Byte 0x36 | CONSTANT | INFERRED | 1 | 0.000 | 0x00 | 0x00 | 100.0 | 0 |
| 0x37 | Name[0] | NAME | OBSERVED | 21 | 2.452 | 0x33 | 0x5A | 0.0 | 30 |
| 0x38 | Name[1] | NAME | OBSERVED | 17 | 2.312 | 0x33 | 0x56 | 0.0 | 28 |
| 0x39 | Name[2] | NAME | OBSERVED | 18 | 2.372 | 0x20 | 0x59 | 0.0 | 28 |
| 0x3A | Name[3] | NAME | OBSERVED | 16 | 1.616 | 0x20 | 0x57 | 0.0 | 28 |
| 0x3B | Name[4] | NAME | OBSERVED | 15 | 2.144 | 0x20 | 0x59 | 0.0 | 28 |
| 0x3C | Name[5] | NAME | OBSERVED | 14 | 2.195 | 0x20 | 0x5A | 0.0 | 24 |
| 0x3D | Name[6] | NAME | OBSERVED | 12 | 2.301 | 0x20 | 0x55 | 0.0 | 28 |
| 0x3E | Name[7] | NAME | OBSERVED | 14 | 2.404 | 0x20 | 0x57 | 0.0 | 27 |
| 0x3F | Name[8] | NAME | OBSERVED | 9 | 1.395 | 0x20 | 0x59 | 0.0 | 16 |

## Classification summary
* CONSTANT: 24
* NAME: 9
* PARAMETER_KNOWN: 31

## Usage spread (local corpus only; rare ≠ unused, constant ≠ reserved)
* widespread: —
* occasional: 0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x0C, 0x0D, 0x0E, 0x0F, 0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x2B, 0x2C, 0x2E, 0x2F, 0x30, 0x31, 0x32, 0x33, 0x34, 0x35
* rare_within_files: —
* fixture_constant: 0x09, 0x0A, 0x0B, 0x17, 0x18, 0x19, 0x1A, 0x1B, 0x1C, 0x1D, 0x1E, 0x1F, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x29, 0x2A, 0x36
* known_parameter_constant_in_corpus: 0x2D (Portamento Mode)

## Enum mapping corroboration (registry vs fixtures)
* `osc1_wave` @ 0x00: STATIC_KNOWN + OBSERVED; unlabelled observed: ['0x07']
* `osc2_wave` @ 0x01: STATIC_KNOWN + OBSERVED; unlabelled observed: none
* `ring_mod_toggle` @ 0x2B: STATIC_KNOWN + OBSERVED; unlabelled observed: none
* `portamento_mode` @ 0x2D: STATIC_KNOWN + OBSERVED; unlabelled observed: none
* `lfo1_wave` @ 0x2F: STATIC_KNOWN + OBSERVED; unlabelled observed: none
* `lfo2_wave` @ 0x30: STATIC_KNOWN + OBSERVED; unlabelled observed: none
* `lfo1_destination` @ 0x35: STATIC_KNOWN + OBSERVED; unlabelled observed: none

## Correlations (INFERRED — never causal claims)
* 0x02 (OSC1 PWM / Detune / FM) ↔ 0x2E (Portamento Amount): nMI=1.0 — OBSERVED_CORRELATION (both params known; possible shared UI function)
* 0x02 (OSC1 PWM / Detune / FM) ↔ 0x30 (LFO2 Wave): nMI=1.0 — OBSERVED_CORRELATION (both params known; possible shared UI function)
* 0x0E (VCF Attack) ↔ 0x2B (Ring Mod On/Off): nMI=1.0 — OBSERVED_CORRELATION (both params known; possible shared UI function)
* 0x0E (VCF Attack) ↔ 0x2E (Portamento Amount): nMI=1.0 — OBSERVED_CORRELATION (both params known; possible shared UI function)
* 0x11 (VCF Release) ↔ 0x2E (Portamento Amount): nMI=1.0 — OBSERVED_CORRELATION (both params known; possible shared UI function)
* 0x11 (VCF Release) ↔ 0x2F (LFO1 Wave): nMI=1.0 — OBSERVED_CORRELATION (both params known; possible shared UI function)
* 0x12 (VCA Attack) ↔ 0x2E (Portamento Amount): nMI=1.0 — OBSERVED_CORRELATION (both params known; possible shared UI function)
* 0x2B (Ring Mod On/Off) ↔ 0x2C (Ring Mod Amount): nMI=1.0 — OBSERVED_CORRELATION (both params known; possible shared UI function)
* 0x2B (Ring Mod On/Off) ↔ 0x32 (LFO1 Amount): nMI=1.0 — OBSERVED_CORRELATION (both params known; possible shared UI function)
* 0x2E (Portamento Amount) ↔ 0x32 (LFO1 Amount): nMI=1.0 — OBSERVED_CORRELATION (both params known; possible shared UI function)
* 0x31 (LFO1 Speed) ↔ 0x32 (LFO1 Amount): nMI=0.981948 — OBSERVED_CORRELATION (both params known; possible shared UI function)
* 0x10 (VCF Sustain) ↔ 0x11 (VCF Release): nMI=0.971257 — OBSERVED_CORRELATION (both params known; possible shared UI function)
* 0x07 (OSC2 Fine) ↔ 0x0C (Filter Frequency): nMI=0.967715 — OBSERVED_CORRELATION (both params known; possible shared UI function)
* 0x03 (OSC2 PWM) ↔ 0x16 (VCF Amount): nMI=0.961608 — OBSERVED_CORRELATION (both params known; possible shared UI function)
* 0x08 (OSC Balance) ↔ 0x0C (Filter Frequency): nMI=0.960792 — OBSERVED_CORRELATION (both params known; possible shared UI function)
* 0x04 (OSC1 Coarse) ↔ 0x16 (VCF Amount): nMI=0.954111 — OBSERVED_CORRELATION (both params known; possible shared UI function)
* 0x14 (VCA Sustain) ↔ 0x16 (VCF Amount): nMI=0.953538 — OBSERVED_CORRELATION (both params known; possible shared UI function)
* 0x05 (OSC1 Fine) ↔ 0x16 (VCF Amount): nMI=0.948884 — OBSERVED_CORRELATION (both params known; possible shared UI function)
* 0x13 (VCA Decay) ↔ 0x33 (LFO2 Speed): nMI=0.948348 — OBSERVED_CORRELATION (both params known; possible shared UI function)
* 0x0C (Filter Frequency) ↔ 0x16 (VCF Amount): nMI=0.943603 — OBSERVED_CORRELATION (both params known; possible shared UI function)

## Contradictions (report-only; registry untouched)
* 0x00 OSC1 Wave: ENUM_VALUE_NOT_IN_TABLE — ['0x07']
* 0x2E Portamento Amount: LOW_VARIABILITY_FOR_KIND — registry kind=continuous but only 3 distinct values across corpus

## CC audit (all mappings require hardware confirmation)
| CC | parameter | offset | source | fixture evidence | hardware |
|---|---|---|---|---|---|
| 1 | modulation | None | registry/MIDI docs | no offset variation / no offset | HARDWARE_CONFIRMATION_REQUIRED |
| 5 | portamento_time | None | registry/MIDI docs | no offset variation / no offset | HARDWARE_CONFIRMATION_REQUIRED |
| 24 | osc1_wave | 0x00 | registry/MIDI docs | offset varies in fixtures | HARDWARE_CONFIRMATION_REQUIRED |
| 25 | osc2_wave | 0x01 | registry/MIDI docs | offset varies in fixtures | HARDWARE_CONFIRMATION_REQUIRED |
| 28 | lfo2_amount | 0x34 | registry/MIDI docs | offset varies in fixtures | HARDWARE_CONFIRMATION_REQUIRED |
| 29 | osc_balance | 0x08 | registry/MIDI docs | offset varies in fixtures | HARDWARE_CONFIRMATION_REQUIRED |
| 47 | filter_env_amount | 0x16 | registry/MIDI docs | offset varies in fixtures | HARDWARE_CONFIRMATION_REQUIRED |
| 54 | lfo1_wave | 0x2F | registry/MIDI docs | offset varies in fixtures | HARDWARE_CONFIRMATION_REQUIRED |
| 55 | lfo2_wave | 0x30 | registry/MIDI docs | offset varies in fixtures | HARDWARE_CONFIRMATION_REQUIRED |
| 56 | lfo1_destination | 0x35 | registry/MIDI docs | offset varies in fixtures | HARDWARE_CONFIRMATION_REQUIRED |
| 70 | lfo1_amount | 0x32 | registry/MIDI docs | offset varies in fixtures | HARDWARE_CONFIRMATION_REQUIRED |
| 71 | filter_resonance | 0x0D | registry/MIDI docs | offset varies in fixtures | HARDWARE_CONFIRMATION_REQUIRED |
| 72 | lfo1_rate | 0x31 | registry/MIDI docs | offset varies in fixtures | HARDWARE_CONFIRMATION_REQUIRED |
| 73 | lfo2_rate | 0x33 | registry/MIDI docs | offset varies in fixtures | HARDWARE_CONFIRMATION_REQUIRED |
| 74 | filter_cutoff | 0x0C | registry/MIDI docs | offset varies in fixtures | HARDWARE_CONFIRMATION_REQUIRED |
| 81 | vca_attack | 0x12 | registry/MIDI docs | offset varies in fixtures | HARDWARE_CONFIRMATION_REQUIRED |
| 82 | vca_decay | 0x13 | registry/MIDI docs | offset varies in fixtures | HARDWARE_CONFIRMATION_REQUIRED |
| 83 | vca_sustain | 0x14 | registry/MIDI docs | offset varies in fixtures | HARDWARE_CONFIRMATION_REQUIRED |
| 84 | vca_release | 0x15 | registry/MIDI docs | offset varies in fixtures | HARDWARE_CONFIRMATION_REQUIRED |
| 85 | vcf_attack | 0x0E | registry/MIDI docs | offset varies in fixtures | HARDWARE_CONFIRMATION_REQUIRED |
| 86 | vcf_decay | 0x0F | registry/MIDI docs | offset varies in fixtures | HARDWARE_CONFIRMATION_REQUIRED |
| 87 | vcf_sustain | 0x10 | registry/MIDI docs | offset varies in fixtures | HARDWARE_CONFIRMATION_REQUIRED |
| 88 | vcf_release | 0x11 | registry/MIDI docs | offset varies in fixtures | HARDWARE_CONFIRMATION_REQUIRED |
| 95 | ring_mod_amount | 0x2C | registry/MIDI docs | offset varies in fixtures | HARDWARE_CONFIRMATION_REQUIRED |
| 96 | ring_mod_toggle | 0x2B | registry/MIDI docs | offset varies in fixtures | HARDWARE_CONFIRMATION_REQUIRED |
| 111 | osc1_fine | 0x05 | registry/MIDI docs | offset varies in fixtures | HARDWARE_CONFIRMATION_REQUIRED |
| 112 | osc2_fine | 0x07 | registry/MIDI docs | offset varies in fixtures | HARDWARE_CONFIRMATION_REQUIRED |
| 113 | osc1_pwm_fm | 0x02 | registry/MIDI docs | offset varies in fixtures | HARDWARE_CONFIRMATION_REQUIRED |
| 114 | osc2_pwm | 0x03 | registry/MIDI docs | offset varies in fixtures | HARDWARE_CONFIRMATION_REQUIRED |
| 115 | osc1_coarse | 0x04 | registry/MIDI docs | offset varies in fixtures | HARDWARE_CONFIRMATION_REQUIRED |
| 116 | osc2_coarse | 0x06 | registry/MIDI docs | offset varies in fixtures | HARDWARE_CONFIRMATION_REQUIRED |

## Experiment priorities (efficiency ranking, not meaning)

## Limitations
* No physical JT-4000M was available; nothing in this report is hardware-confirmed.
* Corpus = local .syx fixtures only (REFERENCE_FIXTURE provenance).
* Statistical correlation is not causation; candidate meanings stay UNKNOWN.
* SYX files alone cannot prove MIDI CC mappings.
* Fixture-constant bytes may still be meaningful parameters rarely used.

_Levels: STATIC_KNOWN = registry only · OBSERVED = directly seen in fixtures · INFERRED = statistical conclusion · HARDWARE_CONFIRMED = not produced in P1.7._