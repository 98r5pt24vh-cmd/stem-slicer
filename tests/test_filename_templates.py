import unittest

from filename_templates import TOKENS, parse_loop_filename, render_name


class FilenameTemplateTests(unittest.TestCase):
    def test_default_order(self):
        self.assertEqual(TOKENS, ("KEY", "LOOP NAME", "BPM", "PROD NAME"))

    def test_parse_and_replace_existing_key(self):
        parts = parse_loop_filename("L CALLMEUR3 137 Am +NRGY.mp3")
        self.assertEqual(parts["KEY"], "Am")
        self.assertEqual(parts["LOOP NAME"], "CALLMEUR3")
        self.assertEqual(parts["BPM"], "137")
        self.assertEqual(parts["PROD NAME"], "+NRGY")
        self.assertEqual(
            render_name(parts, TOKENS, "A#m", 1),
            "A#m CALLMEUR3 137 +NRGY_L1.mp3",
        )

    def test_parse_compact_lowercase_bpm_suffix(self):
        parts = parse_loop_filename("fleon + rafe - average 130bpm.mp3")
        self.assertEqual(parts["BPM"], "130")
        self.assertEqual(parts["LOOP NAME"], "fleon + rafe - average")
        self.assertEqual(parts["PROD NAME"], "")

    def test_parse_spaced_bpm_suffix_without_rendering_it_as_producer(self):
        parts = parse_loop_filename("L Timer 145 BPM +NRGY.mp3")
        self.assertEqual(parts["BPM"], "145")
        self.assertEqual(parts["LOOP NAME"], "Timer")
        self.assertEqual(parts["PROD NAME"], "+NRGY")


if __name__ == "__main__":
    unittest.main()
