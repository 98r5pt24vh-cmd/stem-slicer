# Stem Slicer 1.9B — Beta 1

## Generate

- Integrates the validated cards-as-slots Generate interface.
- Adds synchronized multi-layer playback with per-layer participation.
- Keeps individual layer playback available from each card.
- Supports per-layer alternate key, octave and volume controls.
- Generates draggable MIDI for each generated layer through the persistent
  Quick Extract MIDI engine.
- Keeps the hidden full loop plus ordered stems available through DRAG ALL.
- Preserves persistent Generate history and output management.

## Build

- Clean macOS runtime: CPython 3.12.13 arm64 and PySide6 6.11.1.
- Mutable caches remain outside the signed application bundle.
- Current embedded MERT checkpoint remains non-commercial under CC BY-NC 4.0.

