# Clean Electron rebuild

## Local validation

1. Record `git status --short --branch` and `git rev-parse HEAD`.
2. Start from a clean checkout or worktree.
3. Run `pnpm install --frozen-lockfile` in `electron-app`.
4. Create a new runtime with `pnpm run runtime:setup`.
5. Fetch the pinned MERT tree with `python scripts/fetch_mert_payload.py` when
   it is absent.
6. Verify it with
   `python scripts/verify_external_payloads.py --root . --profile electron`.
7. Preflight every staged engine resource with `pnpm run engine:check`.
8. Run `pnpm run validate` in `electron-app`.
9. Launch the Electron app and confirm that its engine reports this worktree as
   `sourceRoot`.

If an ignored runtime, payload or dependency directory already exists, verify
or move it to the Trash and recreate it. Do not merge it into a fresh build.

## Windows package

Use `.github/workflows/build-electron-windows-alpha.yml` from the recorded
clean revision. The workflow owns runtime creation, validation, the strict
MIDI gate, pinned native payloads, curated staging, ZIP extraction and the
exact extracted-application smoke.
