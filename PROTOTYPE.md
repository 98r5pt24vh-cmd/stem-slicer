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

## Libraries without Top-1/Top-2 key analysis

The accepted 1.9B cache contains 9,193 rows for `+NRGY ALL LAYERS`, all with a
filename key but without the precomputed confidence inventory that exists for
`+NRGY ALL LAYERS 2`.  The old reserve search explored impossible confidence
limits and became combinatorial at this size.

The prototype starts the search at the provable minimum reserve count.  A
library without Top-1/Top-2 data can therefore generate from its filename keys
immediately.  This fallback does not invent an alternate key or claim measured
confidence; such rows remain explicitly `unavailable`.
