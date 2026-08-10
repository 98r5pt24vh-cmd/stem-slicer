# Build invariants — Stem Slicer 1.9B

These rules block a release. Verify the packaged artifact itself; a build
environment or requirements file is not proof of what was shipped.

## Canonical source

- The only current source is the Git repository:
  `/Users/nrgy/Documents/Stem Slicer Repository`.
- Record the exact Git commit before every build.
- Never rebuild from an old handoff, `.app`, Windows `_internal`, extracted ZIP,
  `dist`, `build`, virtual environment or PyInstaller cache.
- The accepted release family is **Stem Slicer 1.9B**.

## Clean-build rule

- Start from a clean checkout/worktree of the recorded source revision.
- Create a new build folder and a new virtual environment.
- Fetch or verify the pinned external payloads; never copy them from an older
  packaged application.
- Run the complete source suite before packaging.
- Audit and smoke-test the application extracted from the final ZIP.
- Record runtime versions, architecture, SHA-256, byte size and validation
  results.

## macOS runtime

- Required validated combination: **CPython 3.12.13 arm64 + PySide6 6.11.1**.
- PyInstaller is pinned to **6.18.0** by `requirements.txt`.
- Do not reuse the obsolete PySide6 6.9.3 runtime.
- PySide6 6.11.1 carries the Qt CoreAudio correction required by Stem Slicer.
- Keep mutable Numba, Hugging Face, Transformers, Torch and application caches
  outside the `.app`.
- Verify `arm64`, Python `3.12.13` and PySide6 `6.11.1` in the final bundle.
- Apply ad-hoc signing recursively and pass `codesign --verify --deep --strict`
  before ZIP creation and after fresh ZIP extraction.
- Create the ZIP with macOS resource metadata preserved.
- Current official PySide6 6.11.1 arm64 wheels contain essential binaries with
  a macOS 15 deployment target. Do not claim Ventura/macOS 13 compatibility.

## Windows runtime

- Required validated combination: **official CPython 3.12.10 x64 from
  `actions/setup-python` + PySide6 6.11.1**.
- Never use the rejected custom/source-built Windows Python 3.12.13 runtime.
- Use `.github/workflows/build-windows.yml`; do not reproduce the accepted CI
  steps manually.
- Pass the complete clean Quick Extract MIDI lifecycle within the strict
  30-second gate before analyzer/Bungee/package work.
- Preserve native inbound drop zones, native Browse ownership/cancel behavior
  and hidden consoles for every helper subprocess.
- Keep `Stem Slicer 1.9B.exe` and `_internal` together.
- The Generate History dialog must be parented to the native top-level window,
  not to the embedded `QGraphicsProxyWidget`.
- Generated-card removal must remain queued until the Qt `clicked` signal has
  returned; repeated pending removal requests must remain idempotent.

## Product invariants

- Preserve the accepted Space and NoSpace extraction paths and their retained
  truth corpora.
- Preserve Quick Extract incremental card rendering, MIDI/audio parallel work,
  per-card audio/MIDI dragging and DRAG ALL ordering.
- Preserve the accepted FFmpeg, OpenKeyScan, DeepRhythm, Bungee and Basic Pitch
  engines.
- Preserve Generate's SQLite incremental cache. Unchanged libraries must not be
  fully rescanned when the cache is valid.
- Preserve separation between classifier training truth and the user's scanned
  generation library.
- Preserve MERT-v1-95M + 64 DSP features (832 values) and the 14-class trained
  head unless a replacement is explicitly evaluated and accepted.
- Preserve Generate card add/remove/keep, synchronized preview, solo preview,
  target BPM/key, octave, volume, alternate key, MIDI handles, Previous Seed,
  Generate, Drag All and persistent history.
- Diagnostics must never persist raw PCM or decoded audio arrays.
- Do not redesign the accepted 1.9B interface without an explicit request.

## Cache invariants

- macOS runtime data version is `1.9`, even though the displayed app version is
  `1.9B`.
- The active Generate library cache therefore lives under the 1.9 cache tree.
- Do not delete or rename the active 1.9 cache during ordinary cleanup; doing so
  forces a full user-library rescan.

## Mandatory release gates

1. Record the exact clean Git revision.
2. Verify Python, architecture and PySide6 in the new build environment.
3. Verify external payload hashes and the offline MERT payload.
4. Run the complete source test suite.
5. On Windows, pass the strict clean MIDI lifecycle before expensive work.
6. Package from clean PyInstaller state.
7. Audit the assembled application and verify its embedded runtime.
8. Run platform-specific engine, UI, MIDI and Generate regressions.
9. Create, integrity-test and freshly extract the final ZIP.
10. Smoke-test the exact extracted payload and record SHA-256 and byte size.

Any failed gate makes the artifact unsuitable for beta distribution.
