# PyInstaller onedir build for JT-4000M Studio.
# Run from this directory with: python -m PyInstaller --clean JT4000M-Studio.spec
from importlib.util import find_spec
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH)
hiddenimports = ["jt4000m.midi_winmm"]  # loaded dynamically by MidiTransport on Windows
# The WinMM backend is native and needs no external MIDI package. Include the
# optional rtmidi fallback only when the build environment has it installed.
if find_spec("rtmidi") is not None:
    hiddenimports += collect_submodules("rtmidi")

a = Analysis(
    [str(ROOT / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="JT4000M-Studio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name="JT4000M-Studio",
)
