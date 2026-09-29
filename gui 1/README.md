# JT-4000M Editor v0.1.1 — SysEx tools

This build fixes the **single-dump parser** and adds:

- `inspect` for single and bulk SysEx;
- `program` for a 64-byte program record;
- `diff` / `semantic-diff` for parameter-aware changes;
- `raw-diff` for exact byte changes, including header/checksum;
- `cross-bank` for automatic comparison of 32-program banks;
- round-trip serialization tests.

## Important format correction

A JT-4000M single dump is **75 bytes**:

```text
F0 + 7-byte identity/command header
64-byte program record
1-byte reserved field
1-byte 7-bit checksum
F7
```

For the supplied `EMPTY.syx`, the checksum is `0x58` and is calculated from the 64-byte program record. The 9-byte patch name is at relative offsets `0x37..0x3F` (55..63). The byte at relative offset `0x40` is a separate reserved byte and must not be mistaken for the checksum.

A bulk dump is **2058 bytes**:

```text
8-byte header
32 × 64-byte program records
1-byte checksum
F7
```

Checksum used by this version:

```text
checksum = (-sum(payload)) & 0x7F
```

This matches the supplied single and bulk fixtures. It is kept as an observed format rule, not a claim about every firmware revision.

## Windows / PowerShell setup

If `python` is not on PATH but the Python launcher is installed, use `py`:

```powershell
py --version
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -e .
```

If PowerShell blocks activation, you can skip activation and use the venv interpreter directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
```

Run tests:

```powershell
python -m pytest
```

## CLI examples

```powershell
python -m jt4000m.cli inspect "EMPTY.syx"
python -m jt4000m.cli inspect "ALL EMPTY.syx"
python -m jt4000m.cli program "ALL INIT SAW.syx" 1
```

Semantic diff:

```powershell
python -m jt4000m.cli diff "ALL EMPTY.syx" "ALL INIT SAW.syx"
```

Exact byte diff:

```powershell
python -m jt4000m.cli raw-diff "ALL EMPTY.syx" "ALL INIT SAW.syx"
```

Explicit semantic diff:

```powershell
python -m jt4000m.cli semantic-diff "ALL EMPTY.syx" "ALL INIT SAW.syx"
```

Cross-bank analysis:

```powershell
python -m jt4000m.cli cross-bank "ALL EMPTY.syx" "ALL INIT SAW.syx" "Synthmania-EDM-Soundset-JT-4000.syx"
```

CSV output:

```powershell
python -m jt4000m.cli cross-bank "ALL EMPTY.syx" "ALL INIT SAW.syx" "Synthmania-EDM-Soundset-JT-4000.syx" --csv cross_bank.csv
```

## What the cross-bank analyzer does

For every relative offset `0x00..0x3F`, it reports the field name and all values observed in every program of every supplied bank. This makes it easy to separate:

- invariant bytes;
- offsets that vary within a bank;
- offsets that differ between banks;
- patch-name bytes;
- still-unknown/reserved offsets.

The analyzer deliberately does **not** invent semantics for unknown bytes.

## Current semantic map

Known labels are carried over from the current reverse-engineering work. Unknown positions remain `Byte 0xNN` rather than being silently assigned a meaning.

Known groups include OSC1/OSC2, filter, VCF/VCA envelopes, ring mod, portamento, LFOs, and name bytes 55..63.

## Next step

The next useful extension is to feed more real banks and controlled hardware dumps into the cross-bank analyzer, then promote only experimentally confirmed offsets into the semantic map. After that we can add safe patch editing and SysEx export to the Serum-like editor layer.

## v0.1.3 — parameter model

The project now has an editor-facing parameter layer in `jt4000m/model.py`.
It links the current SysEx semantic offsets with documented MIDI CCs without inventing unresolved offsets. `parameter-map` prints or exports this mapping.

Examples:

```powershell
python -m jt4000m.cli parameter-map
python -m jt4000m.cli parameter-map --csv parameter_map.csv --json parameter_map.json
```

The MIDI CC mapping is corroborated by the Behringer JT-4000M manual and the independent MIDI Guide database. The current model keeps Modulation (CC 1) and Portamento Time (CC 5) SysEx offsets unresolved, because the supplied project evidence has not established those offsets.

## v0.1.4 — patch foundation + first GUI

The editor now has an immutable `JTProgram` model, a 32-slot `Bank` model,
checksum-safe bulk export, MIDI CC message helpers, and a first standalone
Tkinter editor. The GUI is intentionally conservative: it exposes only
parameters whose SysEx offsets are currently established and preserves all
other bytes unchanged.

Run the GUI from a source checkout with:

```bash
python -m jt4000m.gui
```

The GUI can open a bulk `.syx`, select any of 32 programs, edit mapped
parameters and names, and save a new bulk dump. MIDI hardware transport is
not connected yet; the MIDI layer currently produces validated 3-byte CC
messages.
