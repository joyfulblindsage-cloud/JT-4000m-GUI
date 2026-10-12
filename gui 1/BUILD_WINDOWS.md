# Windows standalone build — JT-4000M Studio

This creates a portable **onedir** Windows build. It does not install anything
on the target computer and does not need Python there. Copy the *entire*
`dist/JT4000M-Studio/` directory; the executable relies on the adjacent
PyInstaller runtime files.

## Build on Windows

Requirements: Windows 10/11 and Python 3.10 or newer. Open PowerShell in
`gui 1` and run:

```powershell
.\build_windows.ps1
```

The script creates a local `.venv`, installs the package plus build/test tools,
runs the test suite, and builds the application. To skip tests deliberately:

```powershell
.\build_windows.ps1 -SkipTests
```

Output:

```text
gui 1\dist\JT4000M-Studio\JT4000M-Studio.exe
```

The build uses the native Windows WinMM MIDI backend. `python-rtmidi` remains
optional and is not installed by the default build; if it is already installed
in the build environment, the spec includes it as a fallback backend.

## Smoke test on a clean Windows account

1. Copy the entire `JT4000M-Studio` output directory to a Windows machine.
2. Launch `JT4000M-Studio.exe` with no synthesizer connected. The GUI should
   open in offline mode; it must not open MIDI ports automatically.
3. Open a known bulk `.syx` bank, select a preset, edit a knob and a slider,
   then use Undo/Redo.
4. Save the bank under a new name and reopen that saved file.
5. Resize the window and switch SYNTH / PRESETS / RESEARCH tabs.
6. Only if a JT-4000M is available: connect it explicitly, verify that
   knob/slider drags send a continuous sequence of CC values, then disconnect.

The source-only test/build job does not prove hardware response. A successful
MIDI API send is not proof that the synthesizer applied the parameter.

## Automated Windows build

The GitHub Actions workflow `.github/workflows/windows-build.yml` runs the
tests and builds the same onedir artifact on Windows for pull requests and
pushes affecting `gui 1/`. Download the `JT4000M-Studio-Windows` workflow
artifact to inspect/run the packaged app.
