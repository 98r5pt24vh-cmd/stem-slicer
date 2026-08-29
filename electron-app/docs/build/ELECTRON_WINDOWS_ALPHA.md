# Slicer Electron — Windows Cloud alpha

This document covers the Electron application and its private Windows alpha.

## Recorded constraints

- Build on a native `windows-2025` runner, not by cross-compiling from macOS.
- Use official CPython 3.12.10 x64 and validate the exact version before packaging.
- Create one fresh `.runtime/python` and use that same runtime for Python tests,
  the strict MIDI gate and the packaged application.
- Package the Python bridge, engine source, models, FFmpeg, Bungee and OpenKeyScan outside `app.asar` so the native runtime can execute them.
- Stage engine files only from `python/engine-manifest.json`; never copy every
  root Python file into the Electron bundle.
- Keep subprocess consoles hidden through `windowsHide: true`.
- Produce an unsigned ZIP for the private alpha. This is not a public release and Windows SmartScreen may warn when it opens.
- Audit the packaged directory, expand the final ZIP, audit it again, and launch the exact extracted `Slicer.exe` before retaining the artifact.
- Record the clean Git revision in the artifact.
- Fetch and verify the pinned MERT payload before the source roster. Run the
  strict MIDI gate before expensive native builds. Verify the complete Windows
  engine manifest only after Bungee and FFmpeg also exist, and before packaging.

## Resource layout

```text
Slicer.exe
resources/
  app.asar
  python/engine_bridge.py
  engine/
    engine.py
    generation_policy.py
    generation_renderer.py
    assets/
    analyzer/
    basic_pitch/
    models/
    bin/bungee.exe
    vendor-windows/
  .runtime/
    python/python.exe
```

At runtime, Electron resolves this layout from `process.resourcesPath`.
Development resolves the repository containing `electron-app` and its
local `.runtime`; it never falls back to another checkout. The OpenKeyScan
server runs as an isolated Python subprocess from the curated analyzer source,
using the same pinned runtime as the bridge. No unused PySide runtime or second
frozen analyzer is bundled in the Electron application.

## Remaining validation before the private handoff

1. Confirm the new Cloud profile visually on macOS, including a real +NRGY photo and a distinct XT photo.
2. Trigger the dedicated Electron Windows alpha workflow from a recorded clean commit.
3. Download its ZIP onto the Windows test machine.
4. Confirm startup, Browse and native file drop.
5. Sign in as XT and verify the profile photo, shared library, Cloud-only Generate, audio playback and exported attribution.
6. Treat any failed complete MIDI test, hidden-console regression or missing native dependency as release-blocking.
