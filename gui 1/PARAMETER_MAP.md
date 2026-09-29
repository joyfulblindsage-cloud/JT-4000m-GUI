# JT-4000M parameter map

This is the first editor-facing model: one parameter specification links the semantic parameter to its observed SysEx offset and documented MIDI CC where available.

## Layers

```text
GUI control
    ↕
ParameterSpec
    ↕             ↕
SysEx byte      MIDI CC
```

The model deliberately leaves a field unresolved when the project evidence does not establish a SysEx offset. In particular, modulation and portamento time currently have documented MIDI CCs but no asserted SysEx offset.

The MIDI CC side is based on the Behringer manual and the independent MIDI Guide database. The SysEx side is the current project semantic map extracted from the supplied `.syx` banks.

## Status

- 32 editor parameters are represented.
- Most documented CCs have a semantic SysEx offset.
- `Modulation` CC 1 remains SysEx-unresolved.
- `Portamento Time` CC 5 remains SysEx-unresolved.
- `Portamento Mode` has a SysEx offset but no documented CC in the current map.
- Unknown/reserved SysEx bytes are not assigned invented meanings.
