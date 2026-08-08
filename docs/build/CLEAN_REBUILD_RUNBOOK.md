# Clean Rebuild Runbook

This is the short operational checklist for producing a beta artifact without
silently changing its runtime.

## Before either build

1. Read `BUILD_INVARIANTS.md`.
2. Select the exact platform source under `06_Source_Current`.
3. Copy the source to a brand-new working folder; never build inside the
   canonical handoff snapshot.
4. Create a brand-new virtual environment with the required exact Python.
5. Confirm that no `build`, `dist`, `release`, `.venv`, `.venv-build`,
   `__pycache__` or `.pyc` content came from a previous build.
6. Do not copy dependencies from an older `.app`, Windows `_internal` folder or
   virtual environment.

## macOS 1.8.2B

Source: `06_Source_Current/Stem_Slicer_1.8.2B_macOS`

Required runtime:

```text
Python 3.12.13
Architecture arm64
PySide6 6.11.1
```

Pre-build gates:

```bash
/absolute/path/to/python3.12 -c "import platform,sys; assert sys.version_info[:3] == (3,12,13); assert platform.machine() == 'arm64'"
/absolute/path/to/python3.12 -m venv .venv-build-1.8.2B
.venv-build-1.8.2B/bin/python -m pip install --upgrade pip
.venv-build-1.8.2B/bin/python -m pip install -r requirements.txt
.venv-build-1.8.2B/bin/python -m pip check
.venv-build-1.8.2B/bin/python -c "import platform,sys,PySide6; assert sys.version_info[:3] == (3,12,13); assert platform.machine() == 'arm64'; assert PySide6.__version__ == '6.11.1'"
QT_QPA_PLATFORM=offscreen STEM_SLICER_DISABLE_ENGINE_AUTOSTART=1 .venv-build-1.8.2B/bin/python -m unittest discover -s tests -v
.venv-build-1.8.2B/bin/python -m PyInstaller --clean --noconfirm StemSlicer.spec
```

After packaging:

- verify the main executable and `libpython3.12.dylib` are arm64;
- prove Python `3.12.13` from the packaged library/runtime;
- locate `libpyside6.abi3.6.11.dylib`;
- confirm no mutable Numba cache is sealed in the app;
- sign the final app, then run:

```bash
codesign --verify --deep --strict --verbose=2 "Stem Slicer 1.8.2B.app"
```

Create the ZIP with `ditto -c -k --sequesterRsrc --keepParent`, test it with
`unzip -t`, extract it into a fresh temporary folder and repeat deep strict
signature verification on the extracted app.

## Windows 1.8.2B

Source: `06_Source_Current/Stem_Slicer_1.8.2B_Windows`

Required runtime:

```text
Official CPython 3.12.10 x64 from actions/setup-python
PySide6 6.11.1
```

Use `.github/workflows/build-windows.yml`; do not recreate the job manually.
The accepted workflow already:

1. pins and verifies the official runtime;
2. verifies engine/model hashes;
3. installs and checks dependencies;
4. runs the complete Quick Extract MIDI gate on a fresh runner with a strict
   30-second limit;
5. builds the isolated analyzer and pinned Bungee/FFmpeg payloads;
6. runs the full test suite plus native drag-and-drop/Browse regressions;
7. performs a clean PyInstaller build;
8. checks the packaged runtime, engines, Optional Target, Qt, MIDI and hidden
   console behavior;
9. audits the bundle before upload.

Do not upload an artifact unless the packaged runtime smoke reports:

```text
app_version = 1.8.2B
python = 3.12.10
architecture = AMD64/x64
pyside6 = 6.11.1
frozen = true
```

The Windows ZIP name presented to testers must be:

`Stem-Slicer-1.8.2B-Windows.zip`

Do not add diagnostic/runtime wording to the public filename. Keep the
executable and `_internal` together.

## Final upload record

Before sending either platform build, record:

- source folder and Git commit when applicable;
- CI run/job/artifact identifiers when applicable;
- embedded Python, architecture and PySide6;
- packaged smoke/audit results;
- ZIP filename, byte size and SHA-256;
- ZIP integrity result;
- beta-tester validation status.

If the runtime differs from the exact values above, stop and rebuild cleanly.
