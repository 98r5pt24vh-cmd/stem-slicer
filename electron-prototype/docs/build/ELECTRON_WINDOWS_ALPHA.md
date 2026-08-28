# Slicer Electron — Windows Cloud alpha

This document covers only the Electron prototype. It does not replace the accepted PySide 1.9B release runbook.

## Recorded constraints

- Build on a native `windows-2025` runner, not by cross-compiling from macOS.
- Use official CPython 3.12.10 x64 and validate the exact version before packaging.
- Package the Python bridge, engine source, models, FFmpeg, Bungee and OpenKeyScan outside `app.asar` so the native runtime can execute them.
- Keep subprocess consoles hidden through `windowsHide: true`.
- Produce an unsigned ZIP for the private alpha. This is not a public release and Windows SmartScreen may warn when it opens.
- Audit the packaged directory, expand the final ZIP, audit it again, and launch the exact extracted `Slicer.exe` before retaining the artifact.
- Record the clean Git revision in the artifact.

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

At runtime, Electron resolves this layout from `process.resourcesPath`. Development continues to resolve the canonical source repository and the local `.runtime` without changing the accepted engine behavior.

## Remaining validation before the private handoff

1. Confirm the new Cloud profile visually on macOS, including a real +NRGY photo and a distinct XT photo.
2. Trigger the dedicated Electron Windows alpha workflow from a recorded clean commit.
3. Download its ZIP onto the Windows test machine.
4. Confirm startup, Browse and native file drop.
5. Sign in as XT and verify the profile photo, shared library, Cloud-only Generate, audio playback and exported attribution.
6. Treat any failed complete MIDI test, hidden-console regression or missing native dependency as release-blocking.
