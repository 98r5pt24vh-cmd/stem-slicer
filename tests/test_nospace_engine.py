import unittest
from unittest.mock import patch

import numpy as np

import engine
from nospace_engine import (
    Candidate,
    accepted_gap_contrast,
    auto_select,
    nospace_candidate_to_grid,
    shortlist_candidates,
)


def candidate(
    *,
    start=24,
    duration=8,
    count=4,
    comb=2.0,
    boundary_median=2.0,
    boundary_floor=1.5,
    peak_fraction=1.0,
    containment=0.5,
    closure=0.5,
    occupancy=1.0,
):
    return Candidate(
        start=start,
        duration=duration,
        count=count,
        end=start + duration * count,
        score=12.5,
        comb_contrast=comb,
        boundary_median=boundary_median,
        boundary_floor=boundary_floor,
        peak_fraction=peak_fraction,
        containment_median=containment,
        containment_floor=containment,
        closure_similarity=closure,
        occupancy_median=occupancy,
        tail_bars=0,
    )


def accepted_grid(gap_db=0.0):
    energies = []
    for _ in range(3):
        energies.extend([0.0] * 4)
        energies.extend([-gap_db] * 4)
    grid = {
        "score": 20.0,
        "confidence_margin": 2.0,
        "first_start": 0,
        "layer_bars": 4,
        "space_bars": 4,
        "stride_bars": 8,
        "slots": [0, 8, 16],
        "active_slots": [0, 8, 16],
        "silent_slots": [],
        "duration_by_slot": {0: 4, 8: 4, 16: 4},
        "sequence_decoder": True,
    }
    return grid, energies


def analysis(energies):
    return {
        "energies": energies,
        "waveform_mono": np.zeros(4096, dtype=np.float32),
        "waveform_sample_rate": 22050,
        "vrai_zero": 0.0,
    }


class NoSpacePureEngineTests(unittest.TestCase):
    def test_adapter_builds_canonical_zero_space_grid(self):
        source = candidate(start=16, duration=8, count=3)
        grid = nospace_candidate_to_grid(source, 1.25)
        self.assertEqual(grid["first_start"], 16)
        self.assertEqual(grid["layer_bars"], 8)
        self.assertEqual(grid["space_bars"], 0)
        self.assertEqual(grid["stride_bars"], 8)
        self.assertEqual(grid["slots"], [16, 24, 32])
        self.assertEqual(grid["active_slots"], grid["slots"])
        self.assertEqual(grid["silent_slots"], [])
        self.assertEqual(
            grid["duration_by_slot"],
            {16: 8, 24: 8, 32: 8},
        )
        self.assertFalse(grid["sequence_decoder"])

    def test_gate_preserves_all_frozen_A_pillars(self):
        decision, reasons = auto_select(None, None, candidate())
        self.assertEqual((decision, reasons), (
            "nospace",
            ["nospace_model_gate_passed"],
        ))
        for field, value in (
            ("comb", 1.74),
            ("boundary_median", 1.74),
            ("boundary_floor", 1.24),
            ("peak_fraction", 0.79),
            ("containment", 0.24),
            ("closure", 0.24),
            ("occupancy", 0.69),
        ):
            kwargs = {field: value}
            decision, reasons = auto_select(None, None, candidate(**kwargs))
            self.assertEqual(decision, "accepted", field)
            self.assertTrue(reasons[0].startswith("nospace_pillar_failed:"))

    def test_gap_contrast_is_none_for_contiguous_slots(self):
        grid = nospace_candidate_to_grid(candidate(), 0.0)
        self.assertIsNone(accepted_gap_contrast(grid, [0.0] * 80))

    def test_three_layer_candidate_generation_is_explicit_only(self):
        novelty = np.linspace(-2.0, 3.0, 41)
        default = shortlist_candidates(novelty, 40)
        shadow = shortlist_candidates(novelty, 40, minimum_layers=3)
        self.assertTrue(all(item[3] >= 4 for item in default))
        self.assertTrue(any(item[3] == 3 for item in shadow))
        with self.assertRaises(ValueError):
            shortlist_candidates(novelty, 40, minimum_layers=2)


class NoSpaceProductSelectionTests(unittest.TestCase):
    def test_high_gap_short_circuit_never_calls_nospace(self):
        accepted, energies = accepted_grid(gap_db=12.0)

        def forbidden(*args, **kwargs):
            raise AssertionError("No Space inference must be skipped.")

        selected, details = engine.select_structural_grid_with_nospace(
            accepted,
            analysis(energies),
            2.0,
            infer_nospace=forbidden,
        )
        self.assertIs(selected, accepted)
        self.assertEqual(details["selected_engine"], "accepted")
        self.assertTrue(details["short_circuit"])
        self.assertEqual(
            details["decision_reasons"],
            ["accepted_spaces_have_quiet_contrast"],
        )

    def test_low_gap_uses_raw_candidate_for_gate_and_final_for_export(self):
        accepted, energies = accepted_grid(gap_db=3.0)
        raw = candidate(start=24, count=4)
        final = candidate(
            start=16,
            count=5,
            comb=0.0,
            boundary_median=0.0,
            boundary_floor=0.0,
            peak_fraction=0.0,
            containment=0.0,
            closure=0.0,
            occupancy=0.0,
        )

        def infer(*args, **kwargs):
            return final, 0.75, {
                "model_best_before_recall_adjustment": raw.__dict__,
            }

        selected, details = engine.select_structural_grid_with_nospace(
            accepted,
            analysis(energies),
            2.0,
            infer_nospace=infer,
        )
        self.assertEqual(details["selected_engine"], "nospace")
        self.assertEqual(selected["first_start"], 16)
        self.assertEqual(selected["slots"], [16, 24, 32, 40, 48])
        self.assertIn(
            "recall_span_extended_before_model_start",
            details["decision_reasons"],
        )

    def test_failed_pillar_returns_exact_accepted_grid(self):
        accepted, energies = accepted_grid(gap_db=3.0)
        invalid = candidate(comb=1.0)

        def infer(*args, **kwargs):
            return invalid, 0.0, {
                "model_best_before_recall_adjustment": invalid.__dict__,
            }

        selected, details = engine.select_structural_grid_with_nospace(
            accepted,
            analysis(energies),
            2.0,
            infer_nospace=infer,
        )
        self.assertIs(selected, accepted)
        self.assertEqual(details["selected_engine"], "accepted")

    def test_valid_nospace_can_recover_when_accepted_is_absent(self):
        valid = candidate()

        def infer(*args, **kwargs):
            return valid, 1.0, {
                "model_best_before_recall_adjustment": valid.__dict__,
            }

        selected, details = engine.select_structural_grid_with_nospace(
            None,
            analysis([0.0] * 80),
            2.0,
            infer_nospace=infer,
        )
        self.assertEqual(details["selected_engine"], "nospace")
        self.assertEqual(selected["space_bars"], 0)

    def test_three_layer_candidate_cannot_cross_product_boundary(self):
        accepted, energies = accepted_grid(gap_db=3.0)
        for raw, final in (
            (candidate(count=3), candidate(count=4)),
            (candidate(count=4), candidate(count=3)),
        ):
            with self.subTest(raw_count=raw.count, final_count=final.count):
                def infer(*args, **kwargs):
                    return final, 1.0, {
                        "model_best_before_recall_adjustment": raw.__dict__,
                    }

                selected, details = (
                    engine.select_structural_grid_with_nospace(
                        accepted,
                        analysis(energies),
                        2.0,
                        infer_nospace=infer,
                    )
                )
                self.assertIs(selected, accepted)
                self.assertEqual(details["selected_engine"], "accepted")
                self.assertEqual(
                    details["decision_reasons"],
                    ["nospace_product_minimum_layers_not_met"],
                )

    def test_gap_contrast_exception_is_contained_by_product_fallback(self):
        accepted, energies = accepted_grid(gap_db=3.0)
        with patch.object(
            engine,
            "accepted_gap_contrast",
            side_effect=RuntimeError("synthetic contrast failure"),
        ):
            selected, details = engine.select_structural_grid_with_nospace(
                accepted,
                analysis(energies),
                2.0,
            )
        self.assertIs(selected, accepted)
        self.assertEqual(details["selected_engine"], "accepted")
        self.assertEqual(
            details["nospace_error"]["type"],
            "RuntimeError",
        )

    def test_nospace_exception_falls_back_to_accepted_or_none(self):
        accepted, energies = accepted_grid(gap_db=3.0)

        def broken(*args, **kwargs):
            raise RuntimeError("synthetic failure")

        for fallback in (accepted, None):
            selected, details = engine.select_structural_grid_with_nospace(
                fallback,
                analysis(energies),
                2.0,
                infer_nospace=broken,
            )
            self.assertIs(selected, fallback)
            self.assertEqual(
                details["selected_engine"],
                "accepted" if fallback is not None else "none",
            )
            self.assertEqual(
                details["nospace_error"]["type"],
                "RuntimeError",
            )

    def test_export_remaining_ratio_boundary_is_unchanged(self):
        self.assertTrue(engine.can_export_full_layer(10.0, 8.0, 15.92))
        self.assertFalse(engine.can_export_full_layer(10.0, 8.0, 15.919))


if __name__ == "__main__":
    unittest.main()
