from dataclasses import replace
from pathlib import Path
import unittest

from generation_policy import (
    GenerationPolicyError,
    GenerationRequest,
    LayerCandidate,
    SelectionError,
    parse_exact_key,
    plan_with_alternate_key,
    plan_with_manual_pitch,
    plan_with_normalization,
    plan_with_source_key_rank,
    select_generation,
    shortest_semitone_shift,
)
from layer_library import LayerRecord


def candidate(
    identity,
    category,
    *,
    loop=None,
    bpm=140,
    key="A minor",
    manual=True,
    confidence=0.95,
    key_sensitive=True,
    key_margin=0.9,
    key_status="safe",
    key_analyzer_id=None,
):
    return LayerCandidate(
        identity=identity,
        path=Path(f"/library/{identity}.wav"),
        source_loop_id=loop or identity,
        source_bpm=bpm,
        source_key=key,
        bars=8,
        manual_label=category if manual else None,
        predicted_label=None if manual else category,
        prediction_confidence=None if manual else confidence,
        key_sensitive=key_sensitive,
        scanned_key=key,
        scanned_mode=None,
        key_confidence_margin=key_margin,
        key_confidence_status=key_status,
        key_analyzer_id=key_analyzer_id,
    )


class ExactTargetTests(unittest.TestCase):
    def test_manual_editor_metadata_overrides_scanned_values(self):
        source = LayerCandidate.from_record(
            {
                "path": "/library/edited.wav",
                "sha256": "edited",
                "source_loop_id": "edited-loop",
                "bpm": 140,
                "manual_bpm": 155,
                "key": "A",
                "mode": "minor",
                "scanned_key": "A",
                "scanned_mode": "minor",
                "manual_key": "C#",
                "manual_mode": "minor",
                "manual_label": "Lead",
                "timeline_offset_beats": 1.25,
                "trim_start_beats": 0.5,
                "trim_end_beats": 0.25,
                "duration_seconds": 12.0,
            }
        )
        self.assertEqual(source.source_bpm, 155)
        self.assertEqual(source.source_signature().canonical, "C# minor")
        self.assertEqual(source.key_confidence_status, "safe")
        self.assertEqual(source.timeline_offset_beats, 1.25)
        self.assertEqual(source.trim_start_beats, 0.5)
        self.assertEqual(source.trim_end_beats, 0.25)

    def test_target_requires_exact_tonic_and_mode(self):
        with self.assertRaises(GenerationPolicyError):
            GenerationRequest(("Bass",), 140, "")
        with self.assertRaises(GenerationPolicyError):
            GenerationRequest(("Bass",), 140, "C major / A minor")
        with self.assertRaises(GenerationPolicyError):
            GenerationRequest(("Bass",), 140, "A")

    def test_compact_minor_key_is_exact(self):
        self.assertEqual(parse_exact_key("F#m").canonical, "F# minor")

    def test_key_parser_tolerates_ui_whitespace_and_invisible_unicode(self):
        self.assertEqual(parse_exact_key("\u200bF\u00a0minor\ufeff").canonical, "F minor")

    def test_key_parser_accepts_flat_and_unicode_accidental_variants(self):
        self.assertEqual(parse_exact_key("G♭ minor").canonical, "F# minor")
        self.assertEqual(parse_exact_key("G♭️ minor").canonical, "F# minor")
        self.assertEqual(parse_exact_key("Gᵇ minor").canonical, "F# minor")
        self.assertEqual(parse_exact_key("F＃ minor").canonical, "F# minor")

    def test_relative_major_and_minor_share_one_family(self):
        source = parse_exact_key("A minor")
        target = parse_exact_key("C major")
        self.assertEqual(shortest_semitone_shift(source, target), 0)

        plan = select_generation(
            [candidate("minor-lead", "Lead", key="A minor")],
            GenerationRequest(("Lead",), 140, "C major"),
        )
        self.assertEqual(plan.target_key, "C major")
        self.assertEqual(plan.selections[0].semitones, 0)

    def test_minor_source_transposes_into_a_major_target_family(self):
        plan = select_generation(
            [candidate("minor-lead", "Lead", key="A minor")],
            GenerationRequest(("Lead",), 140, "D major"),
        )
        # D major and B minor share a family; A minor moves up to B minor.
        self.assertEqual(plan.selections[0].semitones, 2)

    def test_major_source_transposes_into_a_minor_target_family(self):
        plan = select_generation(
            [candidate("major-lead", "Lead", key="C major")],
            GenerationRequest(("Lead",), 140, "E minor"),
        )
        # C major/A minor moves down five semitones to G major/E minor.
        self.assertEqual(plan.selections[0].semitones, -5)

    def test_alternate_key_changes_only_the_selected_source_key_transform(self):
        source = candidate("alt-lead", "Lead", key="A minor")
        source = LayerCandidate(
            **{
                **source.__dict__,
                "alternate_scanned_key": "D",
                "alternate_scanned_mode": "minor",
                "key_top2_probability": 0.21,
            }
        )
        plan = select_generation(
            [source],
            GenerationRequest(("Lead",), 140, "E minor", seed=91),
        )
        alternate = plan_with_alternate_key(
            plan,
            slot_index=0,
            identity="alt-lead",
        )
        before = plan.selections[0]
        after = alternate.selections[0]
        self.assertEqual(alternate.request, plan.request)
        self.assertEqual(after.candidate.identity, before.candidate.identity)
        self.assertEqual(after.speed_ratio, before.speed_ratio)
        self.assertEqual(after.selection_score, before.selection_score)
        self.assertEqual(after.source_key_rank, 2)
        self.assertEqual(after.semitones, 2)
        self.assertEqual(after.candidate.scanned_key, "A minor")
        restored = plan_with_source_key_rank(
            alternate,
            slot_index=0,
            identity="alt-lead",
            source_key_rank=1,
        )
        self.assertEqual(restored.selections[0].source_key_rank, 1)
        self.assertEqual(restored.selections[0].semitones, -5)
        self.assertEqual(restored.selections[0].candidate, before.candidate)

    def test_card_pitch_and_normalization_are_independent_of_key_rank(self):
        source = replace(
            candidate("adjusted-lead", "Lead", key="A minor"),
            alternate_scanned_key="D",
            alternate_scanned_mode="minor",
        )
        plan = select_generation(
            [source],
            GenerationRequest(("Lead",), 140, "E minor", seed=92),
        )
        pitched = plan_with_manual_pitch(
            plan,
            # The visible recipe slot may have shifted since this immutable
            # generation plan was rendered; identity remains authoritative.
            slot_index=4,
            identity="adjusted-lead",
            semitones=12,
        )
        self.assertEqual(pitched.selections[0].manual_pitch_semitones, 12)
        self.assertEqual(pitched.selections[0].semitones, 7)
        alternate = plan_with_alternate_key(
            pitched,
            slot_index=0,
            identity="adjusted-lead",
        )
        self.assertEqual(alternate.selections[0].manual_pitch_semitones, 12)
        self.assertEqual(alternate.selections[0].semitones, 14)
        normalized = plan_with_normalization(
            alternate,
            slot_index=0,
            identity="adjusted-lead",
            enabled=True,
        )
        self.assertTrue(normalized.selections[0].normalization_enabled)
        restored = plan_with_manual_pitch(
            normalized,
            slot_index=0,
            identity="adjusted-lead",
            semitones=0,
        )
        self.assertEqual(restored.selections[0].semitones, 2)
        self.assertTrue(restored.selections[0].normalization_enabled)


class SelectionPolicyTests(unittest.TestCase):
    def test_manual_truth_overrides_prediction(self):
        manual_override = LayerCandidate(
            identity="override",
            path=Path("/library/override.wav"),
            source_loop_id="loop-a",
            source_bpm=140,
            source_key="A minor",
            manual_label="Pad",
            predicted_label="Lead",
            prediction_confidence=0.99,
        )
        plan = select_generation(
            [manual_override, candidate("actual-lead", "Lead")],
            GenerationRequest(("Lead",), 140, "A minor"),
        )
        self.assertEqual(plan.selections[0].candidate.identity, "actual-lead")
        self.assertEqual(plan.selections[0].label_source, "manual")

    def test_low_confidence_top_one_prediction_remains_eligible(self):
        request = GenerationRequest(("Lead",), 140, "A minor")
        plan = select_generation(
            [candidate("low-margin", "Lead", manual=False, confidence=0.01)],
            request,
        )
        self.assertEqual(plan.selections[0].candidate.identity, "low-margin")
        self.assertEqual(plan.selections[0].confidence, 0.01)

    def test_repeated_slots_use_distinct_layers_and_source_loops(self):
        plan = select_generation(
            [
                candidate("lead-a", "Lead", loop="loop-a"),
                candidate("lead-b", "Lead", loop="loop-b"),
            ],
            GenerationRequest(("Lead", "Lead"), 140, "A minor", seed=123),
        )
        self.assertEqual(
            {item.candidate.identity for item in plan.selections},
            {"lead-a", "lead-b"},
        )
        self.assertEqual(
            {item.candidate.source_loop_id for item in plan.selections},
            {"loop-a", "loop-b"},
        )
        self.assertFalse(any(item.reused_source_loop for item in plan.selections))

    def test_two_layers_from_same_source_are_allowed(self):
        plan = select_generation(
            [
                candidate("chords-a", "Chords", loop="loop-a", bpm=120),
                candidate("chords-b", "Chords", loop="loop-b", bpm=140),
                candidate("lead-b", "Lead", loop="loop-b", bpm=140),
            ],
            GenerationRequest(("Chords", "Lead"), 140, "A minor"),
        )
        self.assertEqual(plan.selections[1].candidate.identity, "lead-b")
        self.assertEqual(len({item.candidate.identity for item in plan.selections}), 2)

    def test_more_than_two_layers_from_one_source_is_rejected(self):
        with self.assertRaisesRegex(SelectionError, "more than 2"):
            select_generation(
            [
                    candidate("lead-1", "Lead", loop="one-loop"),
                    candidate("lead-2", "Lead", loop="one-loop"),
                    candidate("lead-3", "Lead", loop="one-loop"),
            ],
                GenerationRequest(("Lead", "Lead", "Lead"), 140, "A minor"),
            )

    def test_source_loop_reuse_is_allowed_only_under_shortage(self):
        plan = select_generation(
            [
                candidate("lead-a", "Lead", loop="only-loop"),
                candidate("lead-b", "Lead", loop="only-loop"),
            ],
            GenerationRequest(("Lead", "Lead"), 140, "A minor"),
        )
        self.assertEqual(len(plan.selections), 2)
        self.assertTrue(all(item.reused_source_loop for item in plan.selections))

    def test_same_file_is_never_used_twice(self):
        with self.assertRaises(SelectionError):
            select_generation(
                [candidate("only-lead", "Lead", loop="only-loop")],
                GenerationRequest(("Lead", "Lead"), 140, "A minor"),
            )

    def test_transform_distance_has_zero_ranking_influence(self):
        layers = [
            candidate("far", "Bass", bpm=70, key="D minor"),
            candidate("close", "Bass", bpm=140, key="A minor"),
        ]
        counts = {"far": 0, "close": 0}
        for seed in range(256):
            plan = select_generation(
                layers,
                GenerationRequest(("Bass",), 140, "A minor", seed=seed),
            )
            counts[plan.selections[0].candidate.identity] += 1
        self.assertGreater(counts["far"], 80)
        self.assertGreater(counts["close"], 80)

    def test_extreme_bpm_ratio_does_not_exclude_a_safe_layer(self):
        plan = select_generation(
            [candidate("very-far-bpm", "Bass", bpm=35)],
            GenerationRequest(("Bass",), 300, "A minor"),
        )
        self.assertEqual(
            plan.selections[0].candidate.identity,
            "very-far-bpm",
        )
        self.assertAlmostEqual(plan.selections[0].speed_ratio, 300 / 35)

    def test_selection_is_stable_for_seed_and_input_order(self):
        layers = [
            candidate("a", "Pluck", loop="loop-a"),
            candidate("b", "Pluck", loop="loop-b"),
            candidate("c", "Pluck", loop="loop-c"),
        ]
        request = GenerationRequest(("Pluck",), 140, "A minor", seed=42)
        first = select_generation(layers, request)
        second = select_generation(reversed(layers), request)
        self.assertEqual(
            first.selections[0].candidate.identity,
            second.selections[0].candidate.identity,
        )

    def test_excluding_previous_generation_changes_every_layer(self):
        layers = [
            candidate("bass-old", "Bass", loop="old-bass"),
            candidate("bass-new", "Bass", loop="new-bass"),
            candidate("lead-old", "Lead", loop="old-lead"),
            candidate("lead-new", "Lead", loop="new-lead"),
            candidate("pad-old", "Pad", loop="old-pad"),
            candidate("pad-new", "Pad", loop="new-pad"),
        ]
        first = select_generation(
            layers,
            GenerationRequest(("Bass", "Lead", "Pad"), 140, "A minor"),
        )
        previous_identities = frozenset(
            item.candidate.identity for item in first.selections
        )
        second = select_generation(
            layers,
            GenerationRequest(
                ("Bass", "Lead", "Pad"),
                140,
                "A minor",
                excluded_identities=previous_identities,
            ),
        )
        self.assertTrue(
            previous_identities.isdisjoint(
                item.candidate.identity for item in second.selections
            )
        )

    def test_locked_slots_survive_exclusion_with_duplicate_categories(self):
        layers = [
            candidate("lead-old-a", "Lead", loop="old-a"),
            candidate("lead-locked", "Lead", loop="old-b"),
            candidate("lead-new", "Lead", loop="new-lead"),
            candidate("pad-locked", "Pad", loop="old-pad"),
            candidate("pad-new", "Pad", loop="new-pad"),
        ]
        plan = select_generation(
            layers,
            GenerationRequest(
                ("Lead", "Lead", "Pad"),
                140,
                "A minor",
                seed=99,
                excluded_identities={
                    "lead-old-a",
                    "lead-locked",
                    "pad-locked",
                },
                locked_identities_by_slot=(
                    "lead-locked",
                    None,
                    "pad-locked",
                ),
            ),
        )

        self.assertEqual(plan.selections[0].candidate.identity, "lead-locked")
        self.assertEqual(plan.selections[1].candidate.identity, "lead-new")
        self.assertEqual(plan.selections[2].candidate.identity, "pad-locked")

    def test_locked_uncertain_layer_is_counted_as_reserve(self):
        plan = select_generation(
            [
                candidate(
                    "uncertain-lock",
                    "Lead",
                    key_margin=0.1,
                    key_status="uncertain",
                ),
                candidate("safe-pad", "Pad"),
            ],
            GenerationRequest(
                ("Lead", "Pad"),
                140,
                "A minor",
                locked_identities_by_slot=("uncertain-lock", None),
            ),
        )

        self.assertEqual(
            [selection.candidate.identity for selection in plan.selections],
            ["uncertain-lock", "safe-pad"],
        )

    def test_incompatible_locked_layer_is_rejected_in_its_slot(self):
        with self.assertRaisesRegex(
            SelectionError,
            r"Locked layer for slot 1: Pad.*incompatible",
        ) as raised:
            select_generation(
                [candidate("lead", "Lead")],
                GenerationRequest(
                    ("Pad",),
                    140,
                    "A minor",
                    locked_identities_by_slot=("lead",),
                ),
            )
        self.assertEqual(raised.exception.slot_index, 0)

    def test_conflicting_key_layer_cannot_be_forced_by_a_lock(self):
        with self.assertRaisesRegex(
            SelectionError,
            r"Locked layer for slot 1: Lead.*incompatible",
        ):
            select_generation(
                [
                    candidate(
                        "conflict",
                        "Lead",
                        key_margin=0.9,
                        key_status="conflict",
                    )
                ],
                GenerationRequest(
                    ("Lead",),
                    140,
                    "A minor",
                    locked_identities_by_slot=("conflict",),
                ),
            )

    def test_locked_layers_still_obey_the_source_loop_quota(self):
        with self.assertRaisesRegex(SelectionError, "more than 2"):
            select_generation(
                [
                    candidate("lead", "Lead", loop="same-loop"),
                    candidate("pad", "Pad", loop="same-loop"),
                    candidate("bass", "Bass", loop="same-loop"),
                ],
                GenerationRequest(
                    ("Lead", "Pad", "Bass"),
                    140,
                    "A minor",
                    locked_identities_by_slot=("lead", "pad", "bass"),
                ),
            )

    def test_same_identity_cannot_be_locked_into_two_slots(self):
        with self.assertRaisesRegex(
            GenerationPolicyError,
            "same layer identity",
        ):
            GenerationRequest(
                ("Lead", "Lead"),
                140,
                "A minor",
                locked_identities_by_slot=("lead", "lead"),
            )

    def test_safe_key_pool_is_used_before_uncertain_reserve(self):
        safe = candidate(
            "safe",
            "Lead",
            key_margin=0.22,
            key_status="safe",
        )
        uncertain = candidate(
            "uncertain",
            "Lead",
            key_margin=0.219,
            key_status="uncertain",
        )
        for seed in range(32):
            plan = select_generation(
                [safe, uncertain],
                GenerationRequest(("Lead",), 140, "A minor", seed=seed),
            )
            self.assertEqual(plan.selections[0].candidate.identity, "safe")

        fallback = select_generation(
            [safe, uncertain],
            GenerationRequest(
                ("Lead",),
                140,
                "A minor",
                excluded_identities={"safe"},
            ),
        )
        self.assertEqual(
            fallback.selections[0].candidate.identity,
            "uncertain",
        )

    def test_large_library_without_key_confidence_skips_impossible_limits(self):
        categories = ("Bass", "Chords", "Lead", "Pad")
        candidates = [
            candidate(
                f"{category.casefold()}-{index}",
                category,
                loop=f"{category.casefold()}-loop-{index}",
                key_margin=None,
                key_status="unavailable",
            )
            for category in categories
            for index in range(250)
        ]

        plan = select_generation(
            candidates,
            GenerationRequest(categories, 140, "A minor", seed=42),
        )

        self.assertEqual(
            tuple(selection.category for selection in plan.selections),
            categories,
        )
        self.assertTrue(
            all(
                selection.candidate.key_confidence_status == "unavailable"
                for selection in plan.selections
            )
        )

    def test_temporal_analyzer_safe_margin_uses_its_own_scale(self):
        temporal = candidate(
            "temporal-safe",
            "Lead",
            key_margin=0.14,
            key_status="safe",
            key_analyzer_id="openkeyscan-split2-relative-family-v2",
        )
        legacy = candidate(
            "legacy-reserve",
            "Lead",
            key_margin=0.14,
            key_status="safe",
        )
        for seed in range(8):
            plan = select_generation(
                [legacy, temporal],
                GenerationRequest(("Lead",), 140, "A minor", seed=seed),
            )
            self.assertEqual(plan.selections[0].candidate.identity, "temporal-safe")

    def test_recipe_with_only_uncertain_key_pools_is_still_deterministic(self):
        layers = [
            candidate("lead-reserve", "Lead", key_status="unavailable", key_margin=None),
            candidate("pad-reserve", "Pad", key_status="unavailable", key_margin=None),
        ]
        request = GenerationRequest(("Lead", "Pad"), 140, "A minor", seed=73)
        first = select_generation(layers, request)
        second = select_generation(reversed(layers), request)
        self.assertEqual(
            [item.candidate.identity for item in first.selections],
            ["lead-reserve", "pad-reserve"],
        )
        self.assertEqual(first, second)

    def test_strict_key_mode_abstains_instead_of_using_uncertain_reserve(self):
        with self.assertRaises(SelectionError):
            select_generation(
                [
                    candidate(
                        "uncertain",
                        "Lead",
                        key_status="uncertain",
                        key_margin=0.10,
                    )
                ],
                GenerationRequest(
                    ("Lead",),
                    140,
                    "A minor",
                    allow_uncertain_key_reserve=False,
                ),
            )

    def test_key_conflict_is_never_selected(self):
        with self.assertRaises(SelectionError):
            select_generation(
                [
                    candidate(
                        "conflict",
                        "Lead",
                        key_margin=0.9,
                        key_status="conflict",
                    )
                ],
                GenerationRequest(("Lead",), 140, "A minor"),
            )

    def test_excluding_singleton_category_reports_no_alternative(self):
        with self.assertRaisesRegex(
            SelectionError,
            r"No alternative layer for slot 1: Texture.*previous generation",
        ) as raised:
            select_generation(
                [candidate("only-texture", "Texture")],
                GenerationRequest(
                    ("Texture",),
                    140,
                    "A minor",
                    excluded_identities={"only-texture"},
                ),
            )
        self.assertEqual(raised.exception.slot_index, 0)
        self.assertEqual(raised.exception.category, "Texture")

    def test_repeated_slots_remain_distinct_after_exclusions(self):
        plan = select_generation(
            [
                candidate("lead-old-a", "Lead", loop="old-a"),
                candidate("lead-old-b", "Lead", loop="old-b"),
                candidate("lead-new-a", "Lead", loop="new-a"),
                candidate("lead-new-b", "Lead", loop="new-b"),
            ],
            GenerationRequest(
                ("Lead", "Lead"),
                140,
                "A minor",
                excluded_identities={"lead-old-a", "lead-old-b"},
            ),
        )
        self.assertEqual(
            {item.candidate.identity for item in plan.selections},
            {"lead-new-a", "lead-new-b"},
        )

    def test_keyless_layer_has_no_pitch_shift(self):
        plan = select_generation(
            [
                candidate(
                    "perc",
                    "Percussion",
                    key=None,
                    key_sensitive=False,
                )
            ],
            GenerationRequest(("Percussion",), 140, "F# minor"),
        )
        self.assertEqual(plan.selections[0].semitones, 0)

    def test_layer_record_adapter_derives_bars_and_key_sensitivity(self):
        record = {
            "path": "/library/percussion.wav",
            "sha256": "abc",
            "source_loop_id": "loop",
            "bpm": 120,
            "key": None,
            "mode": None,
            "duration_seconds": 16,
            "manual_label": "Percussion",
            "predicted_label": None,
            "prediction_confidence": None,
        }
        adapted = LayerCandidate.from_record(record)
        self.assertEqual(adapted.bars, 8)
        self.assertFalse(adapted.key_sensitive)

    def test_real_library_record_contract_is_accepted_directly(self):
        record = LayerRecord(
            path="/library/A minor 140 Layer 1.wav",
            relative_path="Loop/A minor 140 Layer 1.wav",
            filename="A minor 140 Layer 1.wav",
            source_loop_id="loop",
            layer_index=1,
            bpm=140,
            key="A",
            mode="minor",
            duration_seconds=8 * 240 / 140,
            byte_size=123,
            sha256="hash",
            mtime_ns=1,
            manual_label="Bass",
        )
        plan = select_generation(
            [record],
            GenerationRequest(("Bass",), 140, "C minor"),
        )
        self.assertEqual(plan.selections[0].candidate.identity, "hash")
        self.assertEqual(plan.selections[0].semitones, 3)


if __name__ == "__main__":
    unittest.main()
