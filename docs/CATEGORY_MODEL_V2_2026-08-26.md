# Category model v2 — 2026-08-26

## Outcome

The accepted category head is `layer-roles-v2-6e24b7ca1a587bb2`.
It keeps the audited v1 MERT mean plus DSP representation and adds MERT
population standard deviation only where grouped validation confirmed a gain.
No Essentia feature or classifier is used.

The packaged artifact is `models/layer_roles_v2.joblib`:

- SHA-256: `e6681999c9385d5ba052f23ed98b6bcf67d8138f4b2489871857cc75cf28ff15`
- feature extractor: `mert-dsp:c0af6eae387f84d1a5dbebb2f7162f15f2ff261a11f7a8b43c3867f88dff6b2d`
- feature layout: MERT mean 768 + MERT population std 768 + DSP 64
- total dimension: 1,600

The historical v1 artifact and feature rows remain available for audit and
rollback. New scans and future bundles select v2.

## Validation protocol

The scored truth set contains 267 gold layers from 84 source-loop groups.
Another 323 Vocal Chop rows are training-only auxiliary data. Splits use
four-fold `StratifiedGroupKFold`, grouped by source loop so layers from one loop
cannot cross train/test boundaries.

Model and threshold selection used seeds 17, 29 and 43. Threshold confirmation
used seeds 59, 71 and 83. The final seeds 97, 109 and 127 were evaluated once
after the decision was frozen.

| Metric | v1 baseline | v2 classwise | Delta |
| --- | ---: | ---: | ---: |
| Macro-F1 | 0.5897 | 0.6298 | +0.0402 |
| Accuracy | 0.6579 | 0.6816 | +0.0237 |

The temporal score is selected only for Bells, Counter, Pluck, Strings and
Texture. All other score columns come from the historical mean-feature head,
then the combined scores are renormalized.

Final per-class F1 changes versus v1:

| Category | Delta |
| --- | ---: |
| Bells | +0.1700 |
| Pad | +0.1042 |
| Counter | +0.0785 |
| Pluck | +0.0754 |
| Texture | +0.0753 |
| Strings | +0.0440 |
| Vocal Chop | +0.0159 |
| Lead | -0.0037 |

Arp, Bass, Chords, Guitar Chords, Keys and Rhythmic Pluck remain unchanged on
the final protocol. The Pad gain is an ensemble-competition effect: Pad still
uses the stable head, but selected competing class scores are better separated.

## Runtime and cache compatibility

The worker computes mean and population standard deviation in one MERT forward
pass. For an audio hash that already has a v1 feature row, it reuses the audited
DSP64 tail instead of recomputing it. The v1 vector itself is never modified.

The v1 and v2 feature extractor identifiers are independent SQLite keys, so the
active cache can hold both versions without collision. Long 15-second MERT
windows exceed an Apple MPS convolution limit on some files; exact backfills use
CPU for those files rather than changing the validated window representation.

## Verification evidence

- Real-audio worker mean/std parity with the research representation: maximum
  absolute error `5.96e-08`.
- Real-audio classification smoke: expected Bass prediction, followed by a v2
  cache hit.
- Focused unit tests cover the portable ensemble, feature identity, mean/std
  batching, prefill and macOS/Windows bundle declarations.
- The accepted 1.9B application was not rebuilt for this prototype change.

## Active Generate library migration

The active `+NRGY ALL LAYERS` inventory was migrated in place after a separate
SQLite backup. Independent post-migration checks report:

- 8,091 inventory rows and 8,091 rows on the v2 classifier identifier;
- `PRAGMA integrity_check = ok` for both library and feature databases;
- 8,056 unique v2 audio-hash feature rows at dimension 1,600;
- all 8,270 historical v1 feature rows retained at dimension 832;
- 370 changed predicted labels and 7,721 unchanged labels versus v1;
- zero changes to scanned key, alternate key, key-confidence status or key
  analyzer identifier.

Category counts are an operational distribution audit, not an accuracy metric:

| Category | v1 | v2 | Delta |
| --- | ---: | ---: | ---: |
| Arp | 295 | 308 | +13 |
| Bass | 886 | 890 | +4 |
| Bells | 160 | 138 | -22 |
| Chords | 1,211 | 1,225 | +14 |
| Counter | 1,088 | 1,064 | -24 |
| Guitar Chords | 258 | 254 | -4 |
| Keys | 123 | 131 | +8 |
| Lead | 2,419 | 2,466 | +47 |
| Pad | 381 | 384 | +3 |
| Pluck | 412 | 381 | -31 |
| Rhythmic Pluck | 227 | 213 | -14 |
| Strings | 170 | 170 | 0 |
| Texture | 191 | 173 | -18 |
| Vocal Chop | 270 | 294 | +24 |
