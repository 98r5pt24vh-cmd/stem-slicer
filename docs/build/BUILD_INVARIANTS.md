# Build Invariants — Do Not Regress

These are release-blocking requirements. Verify them from the packaged
artifact after every build. A dependency file or build-environment printout is
not proof of the runtime shipped to testers.

## Clean-build rule

- Start from the exact current platform source snapshot.
- Use a newly created build environment.
- Do not reuse `.venv`, `.venv-build`, `build`, `dist`, `release`, PyInstaller
  caches, extracted applications or files copied from an older handoff.
- Record the exact source revision, Python version, architecture, PySide6
  version, artifact checksum and validation results.
- Follow `CLEAN_REBUILD_RUNBOOK.md`; if any gate fails, do not upload.

## macOS runtime

- Required exact accepted combination:
  **CPython 3.12.13 arm64 + PySide6 6.11.1**.
- Do not replace either version merely because a newer version exists.
- Never copy the obsolete PySide6 6.9.3 environment, `.spec`, dependency set or
  application bundle from macOS 1.8B.
- PySide6 6.11.1 contains Qt's `QTBUG-145793` CoreAudio correction and prevents
  Stem Slicer from changing the shared physical audio-device sample rate.
- Verify `arm64`, Python `3.12.13` and
  `libpyside6.abi3.6.11.dylib` inside the final `.app`.
- Keep OpenKeyScan, Numba and all mutable caches outside the bundle.
- Run `codesign --verify --deep --strict` on the final app and again after
  extracting the distributable ZIP.
- Create the ZIP with macOS resource metadata preserved and test its integrity.

## Windows runtime

- Required exact accepted combination:
  **official CPython 3.12.10 x64 from `actions/setup-python` + PySide6 6.11.1**.
- Do not use a custom/source-built CPython 3.12.13 Windows runtime. That
  rejected runtime reproduced the beta failure where Quick Extract MIDI stayed
  pending.
- Use the accepted Windows workflow and source revision as the reconstruction
  baseline. Do not rebuild from an old Windows bundle or source snapshot.
- Before analyzer/Bungee/package work, run the complete clean Quick Extract
  MIDI lifecycle with a strict 30-second timeout and `--require-ready`.
- The MIDI gate passes only when the real window loads the ONNX engine, creates
  a non-empty `.mid`, attaches it to the matching card and makes the MIDI handle
  draggable.
- After packaging, the frozen runtime smoke must report exactly Python
  `3.12.10`, architecture `64bit/x64`, PySide6 `6.11.1` and app `1.8.2B`.
- Preserve inbound drag-and-drop for Source Folder, Quick Extract, Quick Scan
  and Quick Convert.
- Preserve the stable native Browse-dialog owner and cancel behavior.
- Every FFmpeg, analyzer, Bungee and helper subprocess must run without a
  visible console window.
- Test Quick Extract Optional Target in the packaged build.
- Keep the executable and `_internal` together.

## Product invariants

- Preserve incremental Quick Extract card rendering.
- Preserve MIDI/card parallel scheduling and the pending-result handoff.
- Preserve per-card audio and MIDI drag handles.
- Preserve DRAG ALL as one ordered multi-file audio drag.
- Preserve the accepted extraction, key, BPM, conversion and MIDI engines.
- Do not redesign the accepted interface without an explicit request.
- Diagnostics must never persist raw PCM or decoded audio arrays.

## Mandatory release gates

1. Confirm the exact platform source.
2. Create a clean runtime and verify Python, architecture and PySide6.
3. Run the full source test suite.
4. On Windows, pass the clean complete MIDI lifecycle before heavy build work.
5. Package with a clean PyInstaller run.
6. Verify the runtime inside the packaged application.
7. Run platform-specific packaged smokes and audits.
8. Verify macOS signature or Windows GUI/hidden-console behavior.
9. Test the final ZIP's integrity and the application extracted from it.
10. Record SHA-256, size, source revision and all gate results.

Any failure makes the artifact unsuitable for beta distribution.
