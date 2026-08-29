# Slicer Electron clean base

This repository is the clean Electron development line for Slicer. The
accepted PySide 1.9B release remains preserved in the separate canonical
repository; it is not copied, imported or packaged by this workspace.

Read `docs/build/ELECTRON_BUILD_INVARIANTS.md` and
`docs/build/CLEAN_ELECTRON_REBUILD.md` before every package or platform port.

## Repository policy

- Source, tests, build scripts, small assets and dependency manifests belong
  in Git.
- Virtual environments, application bundles, generated outputs, user caches,
  scanned libraries and raw training audio never belong in Git.
- The pinned MERT tree remains a local external payload and is verified with
  `scripts/verify_external_payloads.py --profile electron`.
- Electron engine resources are staged only from
  `electron-app/python/engine-manifest.json`.
- The application, Python tests and engine smokes use the same freshly created
  `electron-app/.runtime/python`.
- The MERT checkpoint bundled in the current beta is CC BY-NC 4.0.  This
  release line is therefore non-commercial until the model is replaced or an
  appropriate commercial permission is obtained.

## Development entry point

- Product name: `Slicer`
- UI: Electron, React and TypeScript
- Engine: headless Python 3.12 sidecar
- Local launch: `Launch Slicer Electron.command`
- Full validation: `pnpm run validate` from `electron-app`
