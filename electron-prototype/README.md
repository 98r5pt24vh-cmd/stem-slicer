# Stem Slicer Electron prototype

This is the evolving, non-packaged Electron interface. It does not replace the
accepted 1.9B release and does not produce an application bundle.

## Runtime isolation

- Electron state: `~/Library/Caches/Stem Slicer/electron-prototype`.
- Accepted catalogue: `~/Library/Caches/Stem Slicer/1.9`, opened read-only.
- Renderer: React 19, TypeScript, Vite and local shadcn/ui components.
- Desktop boundary: a sandboxed preload exposes a narrow, typed IPC API.

The current Electron service reads `generate/library.sqlite3` with
`DatabaseSync(..., { readOnly: true })`. No scan or migration writes to the
accepted cache.

## Development launch

Double-click `Launch Stem Slicer Electron Prototype.command` in the parent
folder, or run `pnpm dev` with the bundled Codex Node runtime on `PATH`.

## Interface palette

- Playback and primary action: `#73BD00`.
- Active navigation and musical landmarks: `#E1D500`.
- Attention and pending states: `#EBBC00`.
- Errors and destructive actions only: `#E63900`.

The image direction is interpreted as high-energy signal color over a nearly
black audio workspace. Statuses always include text or an icon in addition to
color.

## Current migration boundary

The shell, navigation, interaction state, catalogue inspection and file
dialogs are TypeScript-owned. FFmpeg and Bungee remain external binaries. MERT
and key analysis remain behind a temporary Python adapter boundary until an
ONNX/TypeScript port has demonstrated equal outputs on the retained truth
corpora.

## Deferred generated-loop naming contract

The generic History label `Generated combination` is temporary. A later
Generate pass must assign a real loop name and display/export it using the
project convention `L <loop name> <BPM> <producer names>`.

Producer attribution must be derived from the source metadata of every layer
actually used in the generated stack. When layers from several producers are
combined, every distinct contributing producer belongs in the generated loop
name. The exact loop-name generation strategy remains to be specified before
implementation.
