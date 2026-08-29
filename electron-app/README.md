# Slicer Electron application

This directory owns the current Electron interface, desktop process, Cloud
integration and Python sidecar boundary.

## Runtime isolation

- Electron state remains at `~/Library/Caches/Stem Slicer/electron-prototype`
  for compatibility with existing Cloud sessions and downloaded audio.
- Local catalogue and Cloud state use Electron-owned paths. The accepted 1.9
  cache remains available for explicit migration and is never deleted.
- Renderer: React 19, TypeScript, Vite and local shadcn/ui components.
- Desktop boundary: a sandboxed preload exposes a narrow, typed IPC API.

The Python engine and Node services always resolve from this same repository.
Development must never fall back to another checkout.

## Development launch

Double-click `Launch Slicer Electron.command` in the parent folder, or run
`pnpm dev` with Node and pnpm on `PATH`.

## Interface palette

- Playback and primary action: `#73BD00`.
- Active navigation and musical landmarks: `#E1D500`.
- Attention and pending states: `#EBBC00`.
- Errors and destructive actions only: `#E63900`.

The image direction is interpreted as high-energy signal color over a nearly
black audio workspace. Statuses always include text or an icon in addition to
color.

## Runtime boundary

The shell, navigation, interaction state, catalogue, Cloud and file dialogs
are TypeScript-owned. FFmpeg, Bungee, Basic Pitch, MERT and key analysis run in
the headless Python sidecar. `pnpm run runtime:setup` creates the exact local
runtime; `pnpm run validate` uses that same runtime.

## Packaging boundary

The Windows workflow creates a fresh CPython 3.12.10 x64 runtime, runs the
complete validation roster and strict MIDI smoke, stages the curated engine
manifest, then tests the exact application extracted from the final ZIP.
