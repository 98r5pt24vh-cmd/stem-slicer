# Stem Slicer

Private canonical source repository for Stem Slicer.

The current release line is **Stem Slicer 1.9B**.  Its macOS runtime is pinned
to CPython 3.12.13 arm64 and PySide6 6.11.1.  Read
`docs/build/BUILD_INVARIANTS.md` and
`docs/build/CLEAN_REBUILD_RUNBOOK.md` before every build or port.

## Repository policy

- Source, tests, build scripts, small assets and dependency manifests belong
  in Git.
- Virtual environments, application bundles, generated outputs, user caches,
  scanned libraries and raw training audio never belong in Git.
- The large MERT and validated OpenKeyScan/FFmpeg payloads remain local
  external payloads. Their exact trees are verified by
  `scripts/verify_external_payloads.py` before a release build.
- The MERT checkpoint bundled in the current beta is CC BY-NC 4.0.  This
  release line is therefore non-commercial until the model is replaced or an
  appropriate commercial permission is obtained.

## Release identity

- Product name: `Stem Slicer 1.9B`
- Source version: `1.9.0-beta.1`
- macOS artifact: `Stem-Slicer-1.9B-macOS.zip`

