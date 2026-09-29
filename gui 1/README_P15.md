# P1.5 — Hardware Experiment Protocol (jt4000m-editor)

## Evidence levels — never conflated

| Level | Meaning | How it can be earned |
|---|---|---|
| TX / TRANSPORT VERIFIED | MIDI API accepted the message | `midi cc`, `midi sysex-send` report this ONLY |
| RX | device actually sent MIDI bytes | observed by `midi listen` / `midi capture` |
| STATE EFFECT / DEVICE BEHAVIOR VERIFIED | synth really changed a parameter | ONLY via A/B SysEx capture + `experiment compare` |
| SYSEX RESPONSE | device sent an altered dump | captured file with CAPTURED_FROM_DEVICE provenance |

A successful send NEVER implies any of the lower rows. Reports always print
`Device response: NOT VERIFIED` unless a capture proves otherwise.

## Modules

* `jt4000m/transport.py` — `MidiTransport` façade over the EXISTING backends
  (Windows: ctypes WinMM from `midi_winmm.py`; elsewhere optional
  python-rtmidi). No new MIDI library. Injectable fake backend for offline
  tests. Never opens devices unless a human runs a CLI send/listen command.
* `jt4000m/experiment.py` — `compare_experiment(A, B, program, hypothesis)` →
  `ExperimentResult` with per-byte classification
  (`KNOWN_PARAMETER` / `PATCH_NAME` / `UNKNOWN_OFFSET` / checksum…), verdicts
  (`CONFIRMED` / `AMBIGUOUS` / `NOT_CONFIRMED` / `NO_CHANGE` / `OBSERVED`),
  JSON+Markdown export, append-only evidence log
  (`experiments/evidence_log.jsonl`) and `registry_status()` which joins the
  static Parameter Registry with logged evidence. The registry source code is
  never rewritten automatically; promotion to
  `experimentally_confirmed` requires an explicit-hypothesis A/B experiment
  whose verdict was CONFIRMED.
* Provenance labels: `REFERENCE_FIXTURE` vs `CAPTURED_FROM_DEVICE` vs
  `SOFTWARE_GENERATED` — fixtures are NOT treated as device proof.

## CLI

```
python -m jt4000m.cli midi list                  # enumerate endpoints
python -m jt4000m.cli midi probe [--name X]      # find JT-4000M by NAME only
python -m jt4000m.cli midi cc 1 74 64            # TX diagnostic (honest report)
python -m jt4000m.cli midi sysex-send FILE.syx   # parse+checksum gate, YES-confirm
python -m jt4000m.cli midi listen --timeout 10   # RX viewer
python -m jt4000m.cli midi capture --output AFTER.syx
python -m jt4000m.cli experiment compare BEFORE.syx AFTER.syx --program 1 \
        --hypothesis osc1_wave --before-prov device --after-prov device \
        --json r.json --md r.md --log
python -m jt4000m.cli experiment report osc1_wave --program 1   # workflow guide
python -m jt4000m.cli experiment registry-status
```

## Safety rules (enforced)

* Default `pytest` NEVER sends MIDI. Transport unit tests inject a fake
  backend; hardware probes live in `tests/hardware/` and skip unless
  `JT4000M_HARDWARE_TEST=1 pytest tests/hardware -q` is set by a human.
* Even opt-in hardware tests only enumerate ports and run offline analysis;
  they never transmit unknown SysEx or change synth state.
* Unknown changed bytes stay `UNKNOWN_OFFSET` ("Byte 0xNN", confidence
  `observed`); no invented parameter names, no automatic CC guesses.
