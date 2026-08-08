# Stem Slicer 1.8.2B — Quick Extract workflow update

- Keeps incremental Quick Extract card rendering to protect interface
  responsiveness.
- Starts MIDI preparation as soon as extraction completes, in parallel with
  cooperative card rendering.
- Preserves early MIDI results until their matching cards have been created.
- Adds a DRAG ALL handle that exposes every extracted audio layer in one
  ordered multi-file drag.
- Retains the validated CPython 3.12 arm64 and PySide6 6.11.1 macOS runtime.
