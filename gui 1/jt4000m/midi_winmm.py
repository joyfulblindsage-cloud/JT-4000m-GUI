"""Windows WinMM MIDI backend.

Short MIDI messages (including CC and Program Change) and SysEx input are
queued from the WinMM callback and consumed by MidiTransport's existing poll
loop. The callback never touches Tkinter or application state.
"""
from __future__ import annotations

import ctypes
import os
import queue
import time
from ctypes import wintypes
from dataclasses import dataclass

if os.name != "nt":
    raise RuntimeError("midi_winmm requires Windows")

winmm = ctypes.WinDLL("winmm")
UINT = wintypes.UINT
DWORD = wintypes.DWORD
DWORD_PTR = wintypes.WPARAM
HMIDIOUT = wintypes.HANDLE
HMIDIIN = wintypes.HANDLE
CALLBACK_FUNCTION = 0x00030000

MIM_OPEN = 0x3C1
MIM_CLOSE = 0x3C2
MIM_DATA = 0x3C3
MIM_LONGDATA = 0x3C4
MIM_ERROR = 0x3C5
MIM_LONGERROR = 0x3C6
MHDR_DONE = 0x00000001
MAXPNAMELEN = 32


class MIDIOUTCAPS(ctypes.Structure):
    _fields_ = [
        ("wMid", wintypes.WORD), ("wPid", wintypes.WORD),
        ("vDriverVersion", wintypes.UINT),
        ("szPname", wintypes.WCHAR * MAXPNAMELEN),
        ("wTechnology", wintypes.WORD), ("wVoices", wintypes.WORD),
        ("wNotes", wintypes.WORD), ("wChannelMask", wintypes.WORD),
        ("dwSupport", wintypes.DWORD),
    ]


class MIDIINCAPS(ctypes.Structure):
    _fields_ = [
        ("wMid", wintypes.WORD), ("wPid", wintypes.WORD),
        ("vDriverVersion", wintypes.UINT),
        ("szPname", wintypes.WCHAR * MAXPNAMELEN),
        ("dwSupport", wintypes.DWORD),
    ]


class MIDIHDR(ctypes.Structure):
    # MIDIHDR.dwReserved is an array of eight pointer-sized values.
    _fields_ = [
        ("lpData", ctypes.POINTER(ctypes.c_ubyte)),
        ("dwBufferLength", DWORD), ("dwBytesRecorded", DWORD),
        ("dwUser", DWORD_PTR), ("dwFlags", DWORD),
        ("lpNext", ctypes.c_void_p), ("reserved", DWORD_PTR * 8),
    ]


for _name, _restype, _argtypes in [
    ("midiOutGetNumDevs", UINT, []),
    ("midiInGetNumDevs", UINT, []),
    ("midiOutGetDevCapsW", UINT, [UINT, ctypes.POINTER(MIDIOUTCAPS), UINT]),
    ("midiInGetDevCapsW", UINT, [UINT, ctypes.POINTER(MIDIINCAPS), UINT]),
    ("midiOutOpen", UINT, [ctypes.POINTER(HMIDIOUT), UINT, DWORD_PTR, DWORD_PTR, DWORD]),
    ("midiOutClose", UINT, [HMIDIOUT]),
    ("midiOutShortMsg", UINT, [HMIDIOUT, DWORD]),
    ("midiOutPrepareHeader", UINT, [HMIDIOUT, ctypes.POINTER(MIDIHDR), UINT]),
    ("midiOutUnprepareHeader", UINT, [HMIDIOUT, ctypes.POINTER(MIDIHDR), UINT]),
    ("midiOutLongMsg", UINT, [HMIDIOUT, ctypes.POINTER(MIDIHDR), UINT]),
    ("midiInStart", UINT, [HMIDIIN]),
    ("midiInStop", UINT, [HMIDIIN]),
    ("midiInReset", UINT, [HMIDIIN]),
    ("midiInClose", UINT, [HMIDIIN]),
    ("midiInPrepareHeader", UINT, [HMIDIIN, ctypes.POINTER(MIDIHDR), UINT]),
    ("midiInUnprepareHeader", UINT, [HMIDIIN, ctypes.POINTER(MIDIHDR), UINT]),
    ("midiInAddBuffer", UINT, [HMIDIIN, ctypes.POINTER(MIDIHDR), UINT]),
]:
    _fn = getattr(winmm, _name)
    _fn.restype = _restype
    _fn.argtypes = _argtypes

MIDIINPROC = ctypes.WINFUNCTYPE(
    None, HMIDIIN, UINT, DWORD_PTR, DWORD_PTR, DWORD_PTR
)
winmm.midiInOpen.argtypes = [
    ctypes.POINTER(HMIDIIN), UINT, MIDIINPROC, DWORD_PTR, DWORD
]
winmm.midiInOpen.restype = UINT


def check(rc: int, operation: str) -> None:
    if rc:
        raise OSError(f"{operation} failed, MMRESULT={rc}")


@dataclass(frozen=True)
class MidiPort:
    index: int
    name: str
    direction: str


def list_outputs() -> list[MidiPort]:
    result = []
    for index in range(int(winmm.midiOutGetNumDevs())):
        caps = MIDIOUTCAPS()
        check(winmm.midiOutGetDevCapsW(
            index, ctypes.byref(caps), ctypes.sizeof(caps)
        ), "midiOutGetDevCapsW")
        result.append(MidiPort(index, caps.szPname.rstrip("\0")
    return result


def list_inputs() -> list[MidiPort]:
    result = []
    for index in range(int(winmm.midiInGetNumDevs())):
        caps = MIDIINCAPS()
        check(winmm.midiInGetDevCapsW(
            index, ctypes.byref(caps), ctypes.sizeof(caps)
        ), "midiInGetDevCapsW")
        result.append(MidiPort(index, caps.szPname.rstrip("\0")
    return result


def send_short(index: int, data: bytes) -> None:
    if len(data) not in (1, 2, 3):
        raise ValueError("Short MIDI message must contain 1, 2, or 3 bytes")
    handle = HMIDIOUT()
    check(winmm.midiOutOpen(ctypes.byref(handle), index, 0, 0, 0), "midiOutOpen")
    packed = sum(byte << (8 * i) for i, byte in enumerate(data))
    try:
        check(winmm.midiOutShortMsg(handle, packed), "midiOutShortMsg")
    finally:
        winmm.midiOutClose(handle)


def send_sysex(index: int, data: bytes) -> None:
    if len(data) < 2 or data[0] != 0xF0 or data[-1] != 0xF7:
        raise ValueError("SysEx must start F0 and end F7")
    buffer = (ctypes.c_ubyte * len(data))(*data)
    header = MIDIHDR()
    header.lpData = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
    header.dwBufferLength = len(data)
    handle = HMIDIOUT()
    check(winmm.midiOutOpen(ctypes.byref(handle), index, 0, 0, 0), "midiOutOpen")
    prepared = False
    try:
        check(winmm.midiOutPrepareHeader(
            handle, ctypes.byref(header), ctypes.sizeof(header)
        ), "midiOutPrepareHeader")
        prepared = True
        check(winmm.midiOutLongMsg(
            handle, ctypes.byref(header), ctypes.sizeof(header)
        ), "midiOutLongMsg")
        deadline = time.monotonic() + 5
        while not (header.dwFlags & MHDR_DONE) and time.monotonic() < deadline:
            time.sleep(0.005)
        if not (header.dwFlags & MHDR_DONE):
            raise TimeoutError("Timed out waiting for WinMM SysEx transmission")
    finally:
        if prepared:
            # A completed header can be unprepared directly. On timeout,
            # midiOutUnprepareHeader may report STILLPLAYING; surface that
            # honestly rather than claiming a successful send.
            check(winmm.midiOutUnprepareHeader(
                handle, ctypes.byref(header), ctypes.sizeof(header)
            ), "midiOutUnprepareHeader")
        winmm.midiOutClose(handle)


def _short_message_from_packed(packed: int) -> bytes:
    """Decode WinMM MIM_DATA's packed DWORD into the actual MIDI message."""
    status = packed & 0xFF
    if status < 0x80:
        return b""
    if status >= 0xF8 or status in (0xF6, 0xF7):
        length = 1
    elif status in (0xC0, 0xD0, 0xF1, 0xF3):
        length = 2
    elif status == 0xF2:
        length = 3
    elif status < 0xF0:
        length = 2 if status & 0xE0 == 0xC0 else 3
    else:
        length = 1
    return bytes((packed >> (8 * i)) & 0xFF for i in range(length))


class WinMMInput:
    """One open WinMM input. Callback data is queued for the caller to poll."""

    def __init__(self, index: int, *, buffer_size: int = 4096, buffer_count: int = 4):
        self.index = index
        self._queue: queue.Queue[tuple[float, bytes] | RuntimeError] = queue.Queue()
        self._closed = False
        self._buffers: list[tuple[ctypes.Array, MIDIHDR]] = []
        self._handle = HMIDIIN()
        self._callback = MIDIINPROC(self._on_callback)  # keep callback alive
        check(winmm.midiInOpen(
            ctypes.byref(self._handle), index, self._callback, 0, CALLBACK_FUNCTION
        ), "midiInOpen")
        try:
            for _ in range(buffer_count):
                data_buffer = (ctypes.c_ubyte * buffer_size)()
                header = MIDIHDR()
                header.lpData = ctypes.cast(
                    data_buffer, ctypes.POINTER(ctypes.c_ubyte)
                )
                header.dwBufferLength = buffer_size
                check(winmm.midiInPrepareHeader(
                    self._handle, ctypes.byref(header), ctypes.sizeof(header)
                ), "midiInPrepareHeader")
                self._buffers.append((data_buffer, header))
                check(winmm.midiInAddBuffer(
                    self._handle, ctypes.byref(header), ctypes.sizeof(header)
                ), "midiInAddBuffer")
            check(winmm.midiInStart(self._handle), "midiInStart")
        except Exception:
            self.close()
            raise

    def _on_callback(self, _handle, message, _instance, param1, _param2):
        if self._closed:
            return
        try:
            if message == MIM_DATA:
                raw = _short_message_from_packed(int(param1))
                if raw:
                    self._queue.put((time.monotonic(), raw))
            elif message == MIM_LONGDATA:
                header = ctypes.cast(
                    ctypes.c_void_p(int(param1)), ctypes.POINTER(MIDIHDR)
                ).contents
                length = int(header.dwBytesRecorded)
                if length:
                    raw = bytes(header.lpData[i] for i in range(length))
                    self._queue.put((time.monotonic(), raw))
                if not self._closed:
                    header.dwBytesRecorded = 0
                    rc = winmm.midiInAddBuffer(
                        self._handle,
                        ctypes.byref(header),
                        ctypes.sizeof(header),
                    )
                    if rc:
                        self._queue.put(RuntimeError(
                            f"midiInAddBuffer failed, MMRESULT={rc}"
                        ))
            elif message in (MIM_ERROR, MIM_LONGERROR):
                self._queue.put(RuntimeError(
                    f"WinMM MIDI input error (message=0x{int(message):04X})"
                ))
        except Exception as exc:
            self._queue.put(RuntimeError(f"WinMM MIDI callback failed: {exc}"))

    def get_message(self):
        """Non-blocking rtmidi-compatible (delta, data) result."""
        try:
            item = self._queue.get_nowait()
        except queue.Empty:
            return None
        if isinstance(item, RuntimeError):
            raise item
        _timestamp, data = item
        return 0.0, list(data)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            winmm.midiInStop(self._handle)
            winmm.midiInReset(self._handle)
        finally:
            for _buffer, header in self._buffers:
                try:
                    winmm.midiInUnprepareHeader(
                        self._handle, ctypes.byref(header), ctypes.sizeof(header)
                    )
                except Exception:
                    pass
            self._buffers.clear()
            check(winmm.midiInClose(self._handle), "midiInClose")
            self._callback = None


def open_input(index: int) -> WinMMInput:
    return WinMMInput(index)


def receive_sysex(index: int, timeout: float = 10, buffer_size: int = 4096) -> bytes:
    """Compatibility helper: wait for one SysEx message, ignoring short MIDI."""
    device = WinMMInput(index, buffer_size=buffer_size)
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            item = device.get_message()
            if item is None:
                time.sleep(0.005)
                continue
            _delta, data = item
            raw = bytes(data)
            if raw.startswith(b"\\xF0") and raw.endswith(b"\\xF7"):
                return raw
        raise TimeoutError("Timed out waiting for WinMM SysEx input")
    finally:
        device.close()
