# Stem Slicer 1.7B

Stem Slicer 1.7B is the PySide6 implementation of the validated 1.7B interface.
It extracts loop layers, analyzes musical key and Loop-mode BPM, converts BPM
and key with Bungee, and provides the Quick Extract, Quick Scan and Quick
Convert workflows from the same fixed-layout desktop application.

## Runtime layout

The main application remains deliberately lightweight:

- FFmpeg decodes, measures and encodes audio;
- the open-source Bungee command-line engine performs pitch/time conversion;
- OpenKeyScan and DeepRhythm run in one isolated analyzer child bundle;
- Basic Pitch uses the single ONNX model bundled by the parent application;
- PySide6 provides the fixed-size, percentage-scaled interface and multimedia
  preview.

The key/BPM analyzer stays an opaque child bundle so its Torch runtime is not
collected a second time by the parent PyInstaller build.

## Development

Use CPython 3.12 for the currently pinned dependencies:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
QT_QPA_PLATFORM=offscreen STEM_SLICER_DISABLE_ENGINE_AUTOSTART=1 \
  .venv/bin/python -m unittest discover -s tests -v
```

The repository intentionally does not contain generated application bundles,
Windows vendor folders, Bungee binaries or analyzer build directories.

## Windows build

`.github/workflows/build-windows.yml` performs a clean Windows x64 build on
GitHub Actions. It:

1. validates the committed model and warm-up assets by SHA-256;
2. builds the custom OpenKeyScan + DeepRhythm analyzer with pinned CPU-only
   Torch 2.2.2 wheels;
3. builds Bungee from commit
   `746833f68a574d997ec50443e7cfd2d37b026302` using its MinGW preset and a
   static library;
4. downloads the pinned FFmpeg executable and verifies its SHA-256;
5. runs the complete local unit-test suite;
6. builds the portable PyInstaller `onedir` application;
7. smoke-tests the GUI PE subsystem, FFmpeg, Bungee, the robust Loop-mode BPM
   analyzer, Basic Pitch and the Qt interface;
8. audits the finished payload for duplicate engines, models and Torch DLLs;
9. publishes the `Stem-Slicer-1.7B-Windows` Actions artifact.

The Windows application executable is built with `console=False`. Every
FFmpeg, Bungee and analyzer subprocess is also started with
`CREATE_NO_WINDOW`, `STARTF_USESHOWWINDOW` and `SW_HIDE`. The analyzer itself
retains its standard-input/output channel because that channel carries its
NDJSON protocol; its parent process is responsible for keeping it invisible.

The workflow is prepared locally but must pass its first GitHub Actions run
before the Windows bundle can be called validated on real Windows.
