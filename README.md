# Stem Slicer 1.5S Beta

Cross-platform PySide6 interface built around the validated Stem Slicer 1.0b
extraction engine and the embedded OpenKeyScan musical-key analyzer.

Current validated scope includes the batch Stem Slicer workflows, automatic
OpenKeyScan warm-up, Quick Scan, Quick Extract, real waveforms, Qt Multimedia
preview, external file drag, managed persistent storage, and an in-app Quick
Extract history manager. The handoff copy also contains
`01_Documentation/PROJECT_STATUS_2026-07-13.md` as the authoritative status.

Version 1.5S Beta is an alternative interface skin built from the complete 1.5
Beta application. The real header, brand assets, tabs and Quick Tools page are
unchanged. Only the batch Stem Slicer page is reorganized as a guided workflow:
Source Folder, Operations, Output, then Process Status. The shared source stays
available for extraction-only, extraction plus analysis, and key-analysis-only
workflows. MIDI behavior remains identical to 1.5 Beta.

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

The validated macOS build environment is CPython 3.12.x on Apple Silicon.
Keep the build pinned to Python 3.12 until a later runtime has passed the full
audio, extraction, key-analysis and MIDI test suite.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python app.py
```

Run tests:

```bash
QT_QPA_PLATFORM=offscreen STEM_SLICER_DISABLE_ENGINE_AUTOSTART=1 .venv/bin/python -m unittest discover -s tests -v
```

Build macOS:

```bash
.venv/bin/python -m PyInstaller --noconfirm StemSlicer.spec
cp -cR vendor/openkeyscan-analyzer \
  "dist/Stem Slicer 1.5S Beta.app/Contents/Resources/openkeyscan-analyzer"
codesign --force --deep --sign - "dist/Stem Slicer 1.5S Beta.app"
codesign --verify --deep --strict "dist/Stem Slicer 1.5S Beta.app"
```

Sur APFS, `cp -cR` crée une copie clone autonome sans doubler temporairement
l’espace physique. Utiliser `ditto` à sa place sur un autre système de fichiers.
Avant de relancer PyInstaller, déplacer tout ancien `build` ou `dist` vers la
Corbeille : PyInstaller remplace sinon ses dossiers de sortie.

`StemSlicer.spec` collecte l’application Qt 6.11.1, FFmpeg et le modèle ONNX de
Basic Pitch. FFprobe n’est plus embarqué : la durée audio passe par le fallback
FFmpeg, validé sur une extraction canonique identique. OpenKeyScan reste un
payload opaque afin de ne pas collecter Torch une deuxième fois ; il est ajouté
après PyInstaller, puis le bundle complet est resigné en profondeur.

Le bundle Mac 1.5 Beta de référence mesure 0,953 Go logiques et 0,959 Go alloués sur
le volume de test, en unités décimales macOS. L’audit ne trouve qu’un modèle
OpenKeyScan, qu’un modèle Basic Pitch et 0,051 Go de bibliothèques strictement
identiques entre leurs deux runtimes isolés. Ces copies ne sont pas mutualisées
car cela fragiliserait les chemins dynamiques et la signature du bundle.

Qt Multimedia 6.11.1 est requis pour le correctif CoreAudio. Le test matériel
validé lit un MP3 à 44,1 kHz tout en maintenant la sortie Mac à 48 000 Hz et
512 frames avant, pendant et après la lecture.

## Windows build

The GitHub Actions workflow builds the same fixed-size 1440 × 864 Qt interface,
builds the Windows OpenKeyScan analyzer, bundles FFmpeg and Qt
Multimedia, runs the tests, and publishes `Stem-Slicer-1.5S-Beta-Windows`.

Windows subprocesses use both `CREATE_NO_WINDOW` and `SW_HIDE`. The workflow
also rejects any main executable that is not compiled with the Windows GUI PE
subsystem, runs real bundled FFmpeg/OpenKeyScan/Basic Pitch smoke tests, and
checks that each model and the isolated `torch_cpu` binary appear exactly once.

Le format Windows actuellement validé est un bundle portable `onedir`. Il faut
extraire le ZIP complet, puis conserver `Stem Slicer 1.5S Beta.exe` à côté du
dossier `_internal`; aucune installation n'est nécessaire. Le build DropFix a
été validé sur une machine Windows réelle pour le symbole Pause, le drag entrant
de dossiers et fichiers audio, le drag sortant et Qt Multimedia. L'application
doit être lancée par double-clic normal, sans élévation administrateur.

Un futur build PyInstaller `onefile` en EXE unique est possible, mais il
extrairait automatiquement Qt, PyTorch, FFmpeg, OpenKeyScan et les autres
dépendances natives dans `%TEMP%\_MEI…` à chaque démarrage. Cette variante doit
rester séparée du `onedir` validé jusqu'à comparaison réelle du temps de
démarrage, de l'espace temporaire, du nettoyage et du comportement antivirus.
Le statut, le lien de build et les empreintes sont documentés dans
`../../06_Windows_Build/WINDOWS_BUILD.md`.
