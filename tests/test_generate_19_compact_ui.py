import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("STEM_SLICER_DISABLE_ENGINE_AUTOSTART", "1")

from PySide6.QtWidgets import QApplication

from generator_ui import GenerateCard, GeneratePage, RELATIVE_KEY_FAMILIES


APP = QApplication.instance() or QApplication([])


class Generate19CompactUITests(unittest.TestCase):
    def setUp(self):
        self.page = GeneratePage()
        self.page.resize(1050, 548)
        self.page.show()
        APP.processEvents()

    def tearDown(self):
        self.page.close()
        APP.processEvents()

    def test_relative_key_family_is_displayed_but_backend_receives_minor(self):
        self.page.target_key.setCurrentText("D major / B minor")
        request = self.page.generation_request()
        self.assertEqual(self.page.target_key.currentText(), "D major / B minor")
        self.assertEqual(request["target_key"], "B minor")
        self.assertEqual(len(RELATIVE_KEY_FAMILIES), 12)

    def test_card_recipe_has_no_seven_layer_limit(self):
        for _ in range(10):
            self.page._add_slot("Lead")
        APP.processEvents()
        self.assertEqual(len(self.page._slot_widgets), 14)
        self.assertGreater(
            self.page.layers_area.verticalScrollBar().maximum(), 0
        )

    def test_card_uses_validated_compact_octave_and_volume_controls(self):
        card = GenerateCard(
            {
                "path": "/tmp/compact-layer.mp3",
                "display_name": "LEAD",
                "category": "Lead",
                "slot_index": 0,
                "identity": "compact-layer",
                "alternate_key": "C minor",
                "key": "A minor",
                "bpm": 140,
                "peaks": (0.2, 0.4),
            }
        )
        self.addCleanup(card.close)
        self.assertEqual(card.height(), 78)
        self.assertEqual((card.octave_selector.width(), card.octave_selector.height()), (46, 18))
        self.assertEqual((card.volume_button.width(), card.volume_button.height()), (18, 18))
        self.assertTrue(card.normalization_button.isHidden())
        self.assertEqual(card.volume_button._popup.size().width(), 18)
        self.assertEqual(card.volume_button._popup.size().height(), 64)


if __name__ == "__main__":
    unittest.main()
