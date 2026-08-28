from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import engine_bridge as bridge
from generation_policy import GenerationRequest, LayerCandidate, select_generation


class CollaboratorGenerationTests(unittest.TestCase):
    def candidate(self, category: str, producer: str | None, index: int) -> LayerCandidate:
        credits = f"+NRGY {producer}" if producer else "+NRGY"
        return LayerCandidate(
            identity=f"{category}-{producer or 'solo'}-{index}",
            path=Path(f"Fm TEST 140 {credits}_L{index}.mp3"),
            source_loop_id=f"loop-{category}-{producer or 'solo'}-{index}",
            source_bpm=140,
            source_key="F",
            source_mode="minor",
            manual_label=category,
        )

    def test_allowed_pool_keeps_solo_material(self) -> None:
        records = [
            {"filename": "Fm SOLO 140 +NRGY_L1.mp3"},
            {"filename": "Fm DUO 140 +NRGY FROFFSY_L1.mp3"},
            {"filename": "Fm OTHER 140 +NRGY SHARKBOY_L1.mp3"},
        ]

        filtered = bridge._filter_records_by_allowed_producers(
            records,
            allowed_producers=["+NRGY", "FROFFSY"],
        )

        self.assertEqual(
            [record["filename"] for record in filtered],
            [record["filename"] for record in records[:2]],
        )

    def test_required_share_is_enforced_without_dropping_solo_candidates(self) -> None:
        categories = ("Bass", "Chords", "Lead", "Counter", "Pluck")
        candidates = tuple(
            self.candidate(category, producer, index)
            for index, category in enumerate(categories, start=1)
            for producer in (None, "FROFFSY")
        )
        request = GenerationRequest(
            categories=categories,
            target_bpm=140,
            target_key="F minor",
            seed=17,
        )
        specs = bridge._collaborator_pool_specs(
            candidates,
            allowed_credit_counts=[1, 2],
            required_producers=["FROFFSY"],
            locked_identities=request.locked_identities_by_slot,
            seed=request.seed,
        )
        _, group, pool, required, _ = specs[0]

        plan = bridge._select_constrained_collaborator_plan(
            pool,
            request,
            target_external_keys=group,
            required_keys=required,
            required_contribution_percent=50,
            select_generation=select_generation,
        )
        present, required_layer_count = bridge._selection_collaborator_state(
            plan,
            required,
        )

        self.assertEqual(present, {"froffsy"})
        self.assertEqual(required_layer_count, 3)
        self.assertEqual(len(plan.selections), 5)


if __name__ == "__main__":
    unittest.main()
