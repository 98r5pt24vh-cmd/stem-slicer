# Stem Slicer 1.4 Qt Prototype

Cross-platform PySide6 interface built around the validated Stem Slicer 1.0b
extraction engine and the embedded OpenKeyScan musical-key analyzer.

## Default workflow

- Stem Slicer is enabled.
- Key Analysis is disabled.
- Original loop filenames are preserved exactly.
- Extracted files receive only their `_L1`, `_L2`, ... suffix.

## Key workflow

Enabling Key Analysis automatically enables structured output naming. The
default order is:

`[KEY] [LOOP NAME] [BPM] [PROD NAME]`

The chips remain visible while analysis is disabled, but become draggable only
when analysis is active. Existing key text is replaced by a fresh audio
analysis.

Supported process combinations:

- extraction only;
- key analysis and extraction;
- key analysis only, either copied to an output folder or renamed in place.

## Development

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python app.py
```

Run tests:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -v
```

Build macOS:

```bash
.venv/bin/python -m PyInstaller --clean --noconfirm StemSlicer.spec
```

The Windows GitHub Actions workflow builds the same Qt interface, builds the
Windows OpenKeyScan analyzer, bundles FFmpeg, runs the tests, and publishes an
artifact containing the Windows executable.
