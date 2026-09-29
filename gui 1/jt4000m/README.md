# JT-4000M MIDI LAB patch

Adds a Windows-native MIDI diagnostic layer using winmm.dll. No python-rtmidi required.

Copy `midi_winmm.py` to `jt4000m/midi_winmm.py` and `midi_lab_cli.py` to `jt4000m/midi_lab_cli.py`.

First test:
`python -m jt4000m.midi_lab_cli ports`

Then, after identifying the JT-4000M output/input indices:
`python -m jt4000m.midi_lab_cli cc OUTPUT 1 24 72`
`python -m jt4000m.midi_lab_cli send-syx OUTPUT "EMPTY.syx"`

For receive, start listener first:
`python -m jt4000m.midi_lab_cli listen INPUT --timeout 15`
Then trigger `PROG SING SYX SEND` on the synth.
