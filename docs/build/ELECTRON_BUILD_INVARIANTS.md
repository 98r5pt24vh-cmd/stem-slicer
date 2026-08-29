# Electron build invariants

These rules block a Slicer Electron package.

1. Build only from a recorded clean Git revision.
2. Use Node 24 and pnpm 11.19.0 with the committed lockfile.
3. Use exactly CPython 3.12.13 arm64 on macOS development and exactly official
   CPython 3.12.10 x64 on Windows packaging.
4. Create one fresh `electron-app/.runtime/python`. The test roster,
   engine smokes and packaged application must use that same runtime.
5. Verify the pinned offline MERT tree with
   `scripts/verify_external_payloads.py --profile electron`.
6. Stage engine resources only through
   `electron-app/python/engine-manifest.json`. Never copy every root
   Python file or an old virtual environment, app, ZIP, build or cache.
7. Preserve hidden Windows subprocess consoles, native Browse ownership,
   native drop zones, incremental library caches and the strict complete MIDI
   gate.
8. Preserve the accepted FFmpeg, Bungee, OpenKeyScan, DeepRhythm, Basic Pitch,
   MERT and classifier behavior unless a replacement is explicitly evaluated.
9. Test the packaged application and the exact application freshly extracted
   from the final ZIP before retaining an artifact.
10. Never delete `~/Library/Caches/Stem Slicer/1.9` during cleanup or builds.

The accepted PySide 1.9B release and its build rules remain historical source
in `/Users/nrgy/Documents/Stem Slicer Repository`; they are not Electron build
inputs.
