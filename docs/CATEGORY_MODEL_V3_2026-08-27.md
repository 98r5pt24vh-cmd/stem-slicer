# Category model V3 — accepted application integration

Date: 2026-08-27

## Current artifact

- Runtime artifact: `models/layer_roles_v3.joblib`
- Sidecar: `models/layer_roles_v3.json`
- Version: `layer-roles-v3-036e20769bad10c3`
- SHA-256: `9e4367fb64f9e221de098f7ae5389d894c99fca49b353a3aaa32fa44cc3f984c`
- Status: `accepted_current`

This is the simple V3 accepted by the user for application use. The rejected
weak-attribute experiment is not part of this artifact.

## Training truth and taxonomy

- 849 reviewed gold layers from 641 source-loop groups.
- 323 auxiliary Vocal Chop examples used for training only.
- 14 classes: Arp, Bass, Bells, Chords, Counter, Guitar Chords, Keys, Lead,
  Pad, Piano, Pluck, Strings, Texture and Vocal Chop.
- Piano was added and Rhythmic Pluck was merged into Pluck.
- Perc Drums remains outside the melodic category model.

## Leakage-safe validation

Every fold isolates complete source-loop groups. Auxiliary examples are never
scored.

- Full reviewed corpus, final grouped seeds: macro-F1 `0.6072`, accuracy
  `0.6141`.
- Actively sampled 444-file difficult subset: macro-F1 `0.3751`, accuracy
  `0.5135`.
- Deployed V2 on that same difficult subset: macro-F1 `0.1951`, accuracy
  `0.3041`.

The difficult-subset figure is intentionally not a production-prevalence
estimate. It measures cases selected around known category boundaries.

## Runtime and cache compatibility

V3 keeps the V2 feature-extractor identity:

`mert-dsp:c0af6eae387f84d1a5dbebb2f7162f15f2ff261a11f7a8b43c3867f88dff6b2d`

Its input remains MERT mean, MERT population standard deviation and DSP64,
totalling 1,600 float features. Existing cached V2 feature vectors can
therefore be reused. Only category-head inference must be replayed when the
classifier identifier changes.

## Next planned iteration

The 558-file difficult review batch on the user's Desktop is intended for a
future V4. It is not included in V3 training or validation.
