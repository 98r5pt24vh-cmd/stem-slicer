import unittest

from midi_conversion import bpm_from_filename, clean_note_events


class MidiConversionTests(unittest.TestCase):
    def test_bpm_is_read_from_layer_filename(self):
        self.assertEqual(bpm_from_filename("L MOTOMOTO 145 RP_L4.mp3"), 145)

    def test_ambiguous_bpm_is_rejected(self):
        with self.assertRaises(ValueError):
            bpm_from_filename("Loop 120 remix 140_L1.mp3")

    def test_clean_lab_v1_quantizes_and_merges_fragments(self):
        events = [
            (0.012, 0.105, 60, 0.50, None),
            (0.109, 0.200, 60, 0.70, None),
            (0.141, 0.250, 64, 0.60, None),
        ]
        cleaned = clean_note_events(events, 120)
        self.assertEqual(len(cleaned), 2)
        self.assertEqual(cleaned[0][0], 0.0)
        self.assertEqual(cleaned[0][2], 60)
        self.assertEqual(cleaned[1][2], 64)


if __name__ == "__main__":
    unittest.main()
