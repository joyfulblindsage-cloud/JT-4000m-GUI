from __future__ import annotations
import os, ctypes, time, queue
from ctypes import wintypes
from dataclasses import dataclass
if os.name != 'nt':
    raise RuntimeError('midi_winmm requires Windows')
winmm=ctypes.WinDLL('winmm')
UINT=wintypes.UINT; DWORD=wintypes.DWORD; DWORD_PTR=wintypes.WPARAM
HMIDIOUT=wintypes.HANDLE; HMIDIIN=wintypes.HANDLE
CALLBACK_FUNCTION=0x00030000

MIM_OPEN = 0x3C1
MIM_CLOSE = 0x3C2
MIM_DATA = 0x3C3
MIM_LONGDATA = 0x3C4
MIM_ERROR = 0x3C5
MIM_LONGERROR = 0x3C6
MIM_MOREDATA = 0x3CC

MHDR_DONE = 1
MAXPNAMELEN=32
class MIDIOUTCAPS(ctypes.Structure):
    _fields_=[('wMid',wintypes.WORD),('wPid',wintypes.WORD),('vDriverVersion',wintypes.UINT),('szPname',wintypes.WCHAR*MAXPNAMELEN),('wTechnology',wintypes.WORD),('wVoices',wintypes.WORD),('wNotes',wintypes.WORD),('wChannelMask',wintypes.WORD),('dwSupport',wintypes.DWORD)]
class MIDIINCAPS(ctypes.Structure):
    _fields_=[('wMid',wintypes.WORD),('wPid',wintypes.WORD),('vDriverVersion',wintypes.UINT),('szPname',wintypes.WCHAR*MAXPNAMELEN),('dwSupport',wintypes.DWORD)]
class MIDIHDR(ctypes.Structure):
    _fields_=[('lpData',ctypes.POINTER(ctypes.c_ubyte)),('dwBufferLength',DWORD),('dwBytesRecorded',DWORD),('dwUser',DWORD_PTR),('dwFlags',DWORD),('lpNext',ctypes.c_void_p),('reserved',DWORD_PTR)]
for fn,rest,args in [
('midiOutGetNumDevs',UINT,[]),('midiInGetNumDevs',UINT,[]),
('midiOutGetDevCapsW',UINT,[UINT,ctypes.POINTER(MIDIOUTCAPS),UINT]),('midiInGetDevCapsW',UINT,[UINT,ctypes.POINTER(MIDIINCAPS),UINT]),
('midiOutOpen',UINT,[ctypes.POINTER(HMIDIOUT),UINT,DWORD_PTR,DWORD_PTR,DWORD]),('midiOutClose',UINT,[HMIDIOUT]),('midiOutShortMsg',UINT,[HMIDIOUT,DWORD]),
('midiOutPrepareHeader',UINT,[HMIDIOUT,ctypes.POINTER(MIDIHDR),UINT]),('midiOutUnprepareHeader',UINT,[HMIDIOUT,ctypes.POINTER(MIDIHDR),UINT]),('midiOutLongMsg',UINT,[HMIDIOUT,ctypes.POINTER(MIDIHDR),UINT]),
('midiInStart',UINT,[HMIDIIN]),('midiInStop',UINT,[HMIDIIN]),('midiInReset',UINT,[HMIDIIN]),('midiInClose',UINT,[HMIDIIN]),('midiInPrepareHeader',UINT,[HMIDIIN,ctypes.POINTER(MIDIHDR),UINT]),('midiInUnprepareHeader',UINT,[HMIDIIN,ctypes.POINTER(MIDIHDR),UINT]),('midiInAddBuffer',UINT,[HMIDIIN,ctypes.POINTER(MIDIHDR),UINT])]:
    f=getattr(winmm,fn); f.restype=rest; f.argtypes=args
MIDIINPROC=ctypes.WINFUNCTYPE(None,HMIDIIN,UINT,DWORD_PTR,DWORD_PTR,DWORD_PTR)
winmm.midiInOpen.argtypes=[ctypes.POINTER(HMIDIIN),UINT,MIDIINPROC,DWORD_PTR,DWORD]; winmm.midiInOpen.restype=UINT

def check(rc,op):
    if rc: raise OSError(f'{op} failed, MMRESULT={rc}')
@dataclass(frozen=True)
class MidiPort:
    index:int; name:str; direction:str

def list_outputs():
    out=[]
    for i in range(int(winmm.midiOutGetNumDevs())):
        c=MIDIOUTCAPS(); check(winmm.midiOutGetDevCapsW(i,ctypes.byref(c),ctypes.sizeof(c)),'midiOutGetDevCapsW'); out.append(MidiPort(i,c.szPname.rstrip('\0'),'output'))
    return out

def list_inputs():
    out=[]
    for i in range(int(winmm.midiInGetNumDevs())):
        c=MIDIINCAPS(); check(winmm.midiInGetDevCapsW(i,ctypes.byref(c),ctypes.sizeof(c)),'midiInGetDevCapsW'); out.append(MidiPort(i,c.szPname.rstrip('\0'),'input'))
    return out

def send_short(index,data):
    if len(data)!=3: raise ValueError('Short MIDI message must be 3 bytes')
    h=HMIDIOUT(); check(winmm.midiOutOpen(ctypes.byref(h),index,0,0,0),'midiOutOpen')
    try: check(winmm.midiOutShortMsg(h,data[0]|data[1]<<8|data[2]<<16),'midiOutShortMsg')
    finally: winmm.midiOutClose(h)

def send_sysex(index,data):
    if len(data)<2 or data[0]!=0xF0 or data[-1]!=0xF7: raise ValueError('SysEx must start F0 and end F7')
    buf=(ctypes.c_ubyte*len(data))(*data); hdr=MIDIHDR(ctypes.cast(buf,ctypes.POINTER(ctypes.c_ubyte)),len(data),0,0,0,None,0); h=HMIDIOUT()
    check(winmm.midiOutOpen(ctypes.byref(h),index,0,0,0),'midiOutOpen')
    try:
        check(winmm.midiOutPrepareHeader(h,ctypes.byref(hdr),ctypes.sizeof(hdr)),'midiOutPrepareHeader')
        try:
            check(winmm.midiOutLongMsg(h,ctypes.byref(hdr),ctypes.sizeof(hdr)),'midiOutLongMsg')
            deadline=time.monotonic()+2
            while not hdr.dwFlags&MHDR_DONE and time.monotonic()<deadline: time.sleep(.005)
        finally: winmm.midiOutUnprepareHeader(h,ctypes.byref(hdr),ctypes.sizeof(hdr))
    finally: winmm.midiOutClose(h)

def receive_sysex(index,timeout=10,buffer_size=4096):
    q=queue.Queue()
    @MIDIINPROC
def cb(_h, msg, _i, param, _t):
    if msg == MIM_DATA:
        raw = bytes([
            param & 0xFF,
            (param >> 8) & 0xFF,
            (param >> 16) & 0xFF,
        ])
        print(f"RAW MIM_DATA: {' '.join(f'{b:02X}' for b in raw)}", flush=True)

    elif msg == MIM_LONGDATA:
        hdr = ctypes.cast(
            param,
            ctypes.POINTER(MIDIHDR)
        ).contents

        data = bytes(
            hdr.lpData[i]
            for i in range(hdr.dwBytesRecorded)
        )

        print(
            f"RAW MIM_LONGDATA: {len(data)} bytes",
            flush=True
        )
        print(
            " ".join(f"{b:02X}" for b in data[:64]),
            "..." if len(data) > 64 else "",
            flush=True
        )

        q.put(data)

    elif msg == MIM_ERROR:
        print(
            f"RAW MIM_ERROR: 0x{msg:04X}",
            flush=True
        )
        q.put(RuntimeError(
            f"MIDI input error 0x{msg:04X}"
        ))

    elif msg == MIM_LONGERROR:
        print(
            f"RAW MIM_LONGERROR: 0x{msg:04X}",
            flush=True
        )
        q.put(RuntimeError(
            f"MIDI long input error 0x{msg:04X}"
        ))

    else:
        print(
            f"RAW MIDI EVENT: 0x{msg:04X}",
            flush=True
        )
