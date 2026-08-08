# Stem Slicer 1.8.1B — macOS audio-device hotfix

- Updated the packaged Qt/PySide runtime from PySide6 6.9.3 to 6.11.1.
- Includes Qt's CoreAudio fix for QTBUG-145793: Qt Multimedia no longer changes
  the physical audio device sample rate when Stem Slicer initializes playback.
- Keeps the validated Stem Slicer 1.8B interface, extraction engine, conversion
  engine, diagnostics, and cache redirection unchanged.

## Verified

- Python 3.12 arm64 build.
- PySide6 6.11.1 is embedded in the application bundle.
- 101 project tests pass.
- The packaged application starts successfully.
- The macOS bundle passes deep strict code-signature verification.
