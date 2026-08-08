import json
from pathlib import Path
import tempfile
import unittest

from key_confidence import (
    KEY_STATUS_CONFLICT,
    KEY_STATUS_SAFE,
    KEY_STATUS_UNCERTAIN,
    KeyConfidenceIndex,
)


class KeyConfidenceIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.library = self.root / "library"
        self.library.mkdir()
        self.inventory = self.root / "inventory.json"
        self.results = self.root / "results.json"

    def tearDown(self):
        self.temp.cleanup()

    def _write(self, *, margin=0.22, top1="Am", top2=None):
        self.inventory.write_text(
            json.dumps(
                {
                    "layers_root": str(self.library),
                    "entries": [
                        {
                            "source_loop_id": "chance 140 +nrgy",
                            "layer_source_stems": ["Em CHANCE 140 +NRGY"],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        self.results.write_text(
            json.dumps(
                {
                    "scanner_id": "test-key-engine",
                    "results": [
                        {
                            "source_loop_id": "chance 140 +nrgy",
                            "status": "success",
                            "top1_key": top1,
                            "top1_probability": 0.61,
                            "top1_top2_margin": margin,
                            **(
                                {"top2_key": top2, "top2_probability": 0.19}
                                if top2 is not None
                                else {}
                            ),
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

    def _index(self):
        return KeyConfidenceIndex.from_files(
            library_root=self.library,
            inventory_path=self.inventory,
            results_path=self.results,
            threshold=0.22,
        )

    def test_chance_is_conflict_before_rename_and_safe_after_rename(self):
        self._write(margin=0.2549372613430023)
        index = self._index()
        before = index.match(
            "em chance 140 +nrgy",
            filename_key="E",
            filename_mode="minor",
        )
        after = index.match(
            "am chance 140 +nrgy",
            filename_key="A",
            filename_mode="minor",
        )
        self.assertEqual(before.status, KEY_STATUS_CONFLICT)
        self.assertEqual(after.status, KEY_STATUS_SAFE)
        self.assertEqual(after.scanned_key, "A")

    def test_threshold_is_inclusive_at_point_22(self):
        self._write(margin=0.22)
        safe = self._index().match(
            "am chance 140 +nrgy",
            filename_key="A",
            filename_mode="minor",
        )
        self.assertEqual(safe.status, KEY_STATUS_SAFE)

        self._write(margin=0.219999)
        uncertain = self._index().match(
            "am chance 140 +nrgy",
            filename_key="A",
            filename_mode="minor",
        )
        self.assertEqual(uncertain.status, KEY_STATUS_UNCERTAIN)

    def test_relative_major_filename_matches_minor_family_analysis(self):
        self._write(margin=0.25, top1="Am")
        match = self._index().match(
            "chance 140 +nrgy",
            filename_key="C",
            filename_mode="major",
        )
        self.assertIsNotNone(match)
        self.assertEqual(match.status, KEY_STATUS_SAFE)
        self.assertEqual((match.scanned_key, match.scanned_mode), ("A", "minor"))

    def test_known_producer_suffix_may_be_absent_from_truth_source_id(self):
        self._write(margin=0.25, top1="Am")
        match = self._index().match(
            "chance 140",
            filename_key="A",
            filename_mode="minor",
        )
        self.assertIsNotNone(match)
        self.assertEqual(match.status, KEY_STATUS_SAFE)

    def test_manifest_for_another_library_is_disabled(self):
        self._write()
        other = self.root / "other"
        other.mkdir()
        index = KeyConfidenceIndex.from_files(
            library_root=other,
            inventory_path=self.inventory,
            results_path=self.results,
        )
        self.assertFalse(index.enabled)
        self.assertIsNone(
            index.match(
                "am chance 140 +nrgy",
                filename_key="A",
                filename_mode="minor",
            )
        )

    def test_top_two_key_and_scores_are_preserved_when_available(self):
        self._write(margin=0.42, top1="Am", top2="Dm")
        match = self._index().match(
            "chance 140 +nrgy",
            filename_key="A",
            filename_mode="minor",
        )
        self.assertIsNotNone(match)
        self.assertEqual(
            (match.alternate_scanned_key, match.alternate_scanned_mode),
            ("D", "minor"),
        )
        self.assertAlmostEqual(match.top1_probability, 0.61)
        self.assertAlmostEqual(match.top2_probability, 0.19)


if __name__ == "__main__":
    unittest.main()
