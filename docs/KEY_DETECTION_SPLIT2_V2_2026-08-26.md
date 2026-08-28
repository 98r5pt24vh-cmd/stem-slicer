# Key detection split2 v2 — 2026-08-26

## Outcome

The accepted candidate keeps the OpenKeyScan checkpoint and changes inference
in two bounded ways:

1. infer the first and second temporal halves separately, then average their
   softmax probabilities;
2. score each of the 12 compatible key families by adding the minor class and
   its relative-major class.

The analyzer identity is `openkeyscan-split2-relative-family-v2`.

## Calibration and validation

The confidence margin is the score gap between the best and second-best
relative families. Its calibrated normal-pool threshold is
`0.13234874606132507` (displayed as `0.132`). This is a different score scale
from the historical `0.22` margin and therefore does not replace that value on
legacy cache records.

The new threshold was selected only on the 119-loop Liv development split:

- accepted: 111/119;
- correct among accepted: 100/111 = 90.09%;
- coverage: 93.28%.

It was then frozen and evaluated on independent data:

| Validation set | Accepted | Correct accepted | Precision | Coverage |
| --- | ---: | ---: | ---: | ---: |
| Liv holdout | 167/176 | 152/167 | 91.02% | 94.89% |
| Historical truth | 33/33 | 30/33 | 90.91% | 100.00% |
| Combined independent validation | 200/209 | 182/200 | 91.00% | 95.69% |

Unthresholded Liv Top-1 improved from 257/295 (87.12%) to 262/295
(88.81%). Liv Top-2 remained 283/295 (95.93%). On the historical 33-loop
truth set, Top-1 remained 30/33 and Top-2 remained 33/33.

## Runtime observation

On a deterministic 30-loop microprofile with two Torch threads, mean total
analysis time was 314.20 ms for the previous full-view inference and 314.05 ms
for split2. The split2 change therefore showed no measurable runtime penalty in
that sample because each model pass receives half as many temporal frames.

## Compatibility rule

- The active `+NRGY ALL LAYERS` catalogue contains only V2 records and uses
  only the V2 threshold.
- The legacy `0.22` branch remains a reader-only compatibility rule for an
  archived or foreign record that explicitly carries an older analyzer
  identity. It is not used by the active catalogue.
- Records produced by `openkeyscan-split2-relative-family-v2` use
  `0.13234874606132507`.
- Generate resolves the threshold from the analyzer identity before deciding
  whether a key-sensitive layer belongs to the normal pool or the uncertain
  reserve.

## Implemented surfaces

- the local OpenKeyScan analyzer returns Top-1, Top-2, the new margin, analyzer
  identity, calibrated threshold and safe/uncertain status;
- key-confidence cache hydration preserves analyzer-specific calibration;
- strict Generate selection uses the matching threshold scale;
- `tools/scan_key_confidence_v2.py` provides a resumable, isolated scanner with
  a two-thread default and does not mutate the active 1.9 cache.

## Full-library migration

The resumable scanner analyzed the 1,143 original loops that map to the 8,091
currently present layers in `+NRGY ALL LAYERS`:

- successful original-loop analyses: 1,143/1,143;
- analysis errors: 0;
- layers hydrated in the active catalogue: 8,091/8,091;
- V2 safe pool: 7,429 layers;
- V2 uncertain reserve: 508 layers;
- filename/analysis conflicts excluded from strict Generate: 154 layers.

This was a key-only migration. Existing MERT category predictions were
preserved and no layer extraction or category inference was rerun.

Before obsolete catalogue roots were removed, recoverable SQLite snapshots
were placed under
`/Users/nrgy/Documents/Codex Project/Stem Slicer Project/research/cache_archives/2026-08-26-key-v2-migration`.
The active database passed `PRAGMA integrity_check` after cleanup and contains
only the 8,091 current V2 rows.

## Scope and remaining evidence

These tests validate relative major/minor compatibility families, which is the
key representation used by Generate. They do not yet establish separate
major-versus-minor mode classification accuracy.
