# Stem Slicer 1.4.1 M — Packaging Test

Cross-platform PySide6 interface built around the validated Stem Slicer 1.0b
extraction engine and the embedded OpenKeyScan musical-key analyzer.

Current validated scope includes the batch Stem Slicer workflows, automatic
OpenKeyScan warm-up, Quick Scan, Quick Extract, real waveforms, Qt Multimedia
preview, external file drag, managed persistent storage, and an in-app Quick
Extract history manager. The handoff copy also contains
`01_Documentation/PROJECT_STATUS_2026-07-13.md` as the authoritative status.

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
QT_QPA_PLATFORM=offscreen STEM_SLICER_DISABLE_ENGINE_AUTOSTART=1 .venv/bin/python -m unittest discover -s tests -v
```

Build macOS:

```bash
.venv/bin/python -m PyInstaller --clean --noconfirm StemSlicer.spec
```

`StemSlicer.spec` collecte l’application Qt, FFmpeg et FFprobe, mais conserve
OpenKeyScan comme payload opaque afin de ne pas collecter Torch une deuxième
fois. Après PyInstaller, copier `vendor/openkeyscan-analyzer` dans
`Contents/Resources/openkeyscan-analyzer`, puis signer de nouveau le bundle en
profondeur. Le payload Mac ne doit pas contenir le binaire Windows
`_internal/ffmpeg.exe`.

Le bundle Mac validé après nettoyage mesure environ 0,792 Go en unités
décimales macOS. Ne pas supprimer manuellement des bibliothèques Torch, LLVM ou
Qt sans smoke test réel : leur présence n’est pas une preuve de duplication.

## Windows build

The GitHub Actions workflow builds the same fixed-size 1440 × 864 Qt interface,
builds the Windows OpenKeyScan analyzer, bundles FFmpeg/FFprobe and Qt
Multimedia, runs the tests, and publishes `Stem-Slicer-1.4.1-M-Windows`.

Windows subprocesses use both `CREATE_NO_WINDOW` and `SW_HIDE`. The workflow
also rejects any main executable that is not compiled with the Windows GUI PE
subsystem, runs a real bundled FFmpeg/FFprobe/OpenKeyScan smoke test, and checks
that only one model and one `torch_cpu` binary are present.
