# Stem Slicer evolving prototype

This worktree is the single evolving development prototype after the accepted
1.9B release.  It starts from Git revision
`078939bdca901edcecfaf34f8eea4924a02f1416` on branch
`codex/generate-scan-prototype`.

## Isolation

Launch with `Launch Stem Slicer Prototype.command`.  The launcher uses runtime
namespace `prototype-generate`, including:

- `~/Library/Caches/Stem Slicer/prototype-generate`;
- `~/Library/Logs/Stem Slicer/prototype-generate`.

It does not use the accepted Generate cache under
`~/Library/Caches/Stem Slicer/1.9`.

## Current scan experiment

The first accepted prototype change computes the exact existing DSP64 vectors
with up to four ordered worker threads.  On the fixed 48-layer cold benchmark:

- 1.9B path: 93.954 seconds;
- parallel-DSP prototype: 81.028 seconds;
- improvement: 13.76 percent;
- predictions, scores and audio hashes: identical for all 48 rows;
- unchanged rescan: 0.016 seconds for all 48 rows.

No application bundle or release ZIP has been rebuilt.
