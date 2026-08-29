# Slicer Electron clean development line

This worktree contains the current Electron application and the headless audio
engine it actually runs. It does not depend on another source checkout and it
does not contain the retired PySide interface.

## Isolation and retained user data

- Electron development state remains under
  `~/Library/Caches/Stem Slicer/electron-prototype` so existing Cloud sessions
  and downloaded audio remain available.
- The accepted user library cache remains under
  `~/Library/Caches/Stem Slicer/1.9` and must not be deleted.
- Dependencies live in `electron-app/node_modules` and
  `electron-app/.runtime/python`; both are ignored by Git and must be
  recreated from their lockfiles/manifests.
- The offline MERT payload is fetched by the pinned hash-verifying script and
  is never copied from an old application bundle.

## Validation boundary

`pnpm run validate` checks TypeScript, ESLint, Electron unit tests, all
headless engine tests and the persistent bridge tests using the workspace's
own Python runtime. Windows packaging stages only the files listed in the
engine manifest and rejects any retired UI module in the final bundle.
