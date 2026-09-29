from __future__ import annotations
import argparse
from pathlib import Path
from .midi_winmm import list_inputs,list_outputs,send_short,send_sysex,receive_sysex

def main(argv=None):
    ap=argparse.ArgumentParser(prog='jt4000m-midi'); sp=ap.add_subparsers(dest='cmd',required=True)
    sp.add_parser('ports')
    x=sp.add_parser('cc'); x.add_argument('output',type=int); x.add_argument('channel',type=int); x.add_argument('controller',type=int); x.add_argument('value',type=int)
    x=sp.add_parser('send-syx'); x.add_argument('output',type=int); x.add_argument('file')
    x=sp.add_parser('listen'); x.add_argument('input',type=int); x.add_argument('--timeout',type=float,default=10)
    a=ap.parse_args(argv)
    if a.cmd=='ports':
        print('MIDI INPUTS'); print('-----------'); [print(f'{p.index}: {p.name}') for p in list_inputs()]
        print('\nMIDI OUTPUTS'); print('------------'); [print(f'{p.index}: {p.name}') for p in list_outputs()]
    elif a.cmd=='cc':
        if not 1<=a.channel<=16 or not 0<=a.controller<=127 or not 0<=a.value<=127: ap.error('channel 1..16, CC/value 0..127')
        data=bytes((0xB0|a.channel-1,a.controller,a.value)); print('TX:',' '.join(f'{b:02X}' for b in data)); send_short(a.output,data); print('OK')
    elif a.cmd=='send-syx':
        data=Path(a.file).read_bytes(); print(f'TX SysEx: {a.file} ({len(data)} bytes)'); send_sysex(a.output,data); print('OK')
    else:
        print(f'Listening on input {a.input} for {a.timeout:.1f}s...'); data=receive_sysex(a.input,a.timeout); print(f'RX SysEx: {len(data)} bytes'); print(' '.join(f'{b:02X}' for b in data))
if __name__=='__main__': main()
