import os
import sys
from pathlib import Path
import tempfile
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("STEM_SLICER_DISABLE_ENGINE_AUTOSTART", "1")

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent
sys.path.insert(1, str(SOURCE))

from PySide6.QtWidgets import QApplication

from generator_ui import (
    AddRecipeCard,
    GenerateMidiDragHandle,
    GeneratePage,
    PrototypeGenerateCard,
)


APP = QApplication.instance() or QApplication([])


class _ImmediateSignal:
    def __init__(self, callback):
        self._callback = callback

    def emit(self, paths):
        self._callback(tuple(paths))


class _FakeMixDevice:
    def __init__(self, paths):
        self._paths = tuple(paths)
        self._active = set()
        self.position = 0.42

    def allPaths(self):
        return self._paths

    def activePaths(self):
        return tuple(path for path in self._paths if path in self._active)

    def setActive(self, path, active):
        if path not in self._paths:
            return False
        if active:
            self._active.add(path)
        else:
            self._active.discard(path)
        return True


class _FakeSynchronizedPlayer:
    def __init__(self, paths, callback):
        self._device = _FakeMixDevice(paths)
        self.activePathsChanged = _ImmediateSignal(callback)
        self._playing = False

    def playAll(self):
        self._device._active = set(self._device.allPaths())
        self._playing = True
        self.activePathsChanged.emit(self._device.activePaths())
        return True

    def stopAll(self):
        self._device._active.clear()
        self._device.position = 0.0
        self._playing = False
        self.activePathsChanged.emit(())

    def stop(self, *, reset=False):
        if reset:
            self.stopAll()
        else:
            self._playing = False

    def isPlaying(self):
        return self._playing

    def _start(self):
        self._playing = True


class CardsAsSlotsUITests(unittest.TestCase):
    def setUp(self):
        self.page = GeneratePage()
        self.page.resize(1024, 590)
        self.page.show()
        APP.processEvents()

    def tearDown(self):
        self.page.close()
        APP.processEvents()

    def test_default_recipe_is_expressed_as_four_cards(self):
        self.assertEqual(
            [selector.currentText() for selector in self.page._slot_combos],
            ["Bass", "Chords", "Lead", "Counter"],
        )
        self.assertEqual(self.page.layers_grid.count(), 5)
        self.assertEqual(self.page.all_layers_transport.text(), "SYNC PLAY")
        self.assertEqual(
            (self.page.drag_all.width(), self.page.drag_all.height()),
            (78, 22),
        )
        self.assertEqual(self.page.generation_footer.height(), 32)
        self.assertEqual(
            self.page.layers_label.text(),
            "SELECT YOUR LAYER TYPES, THEN GENERATE YOUR LOOP",
        )
        self.assertEqual(
            self.page.generate_description.text(),
            "Generate a new loop from your layer library.",
        )
        self.assertIn("font-size:10px", self.page.generate_description.styleSheet())

    def test_plus_adds_a_card_and_remove_is_immediate(self):
        self.page._add_slot("Texture")
        APP.processEvents()
        self.assertEqual(len(self.page._slot_widgets), 5)
        self.page._card_remove_requested(4)
        APP.processEvents()
        self.assertEqual(len(self.page._slot_widgets), 4)

    def test_card_category_is_the_generation_recipe(self):
        self.page._card_category_changed(1, "Pad")
        request = self.page.generation_request()
        self.assertEqual(request["categories"], ["Bass", "Pad", "Lead", "Counter"])

    def test_generated_cards_expose_category_and_remove_controls(self):
        midi_batches = []
        self.page.midiBatchRequested.connect(midi_batches.append)
        stems = []
        for index, category in enumerate(("Bass", "Chords", "Lead", "Counter")):
            stems.append(
                {
                    "path": f"/tmp/cards-slot-{index}.mp3",
                    "display_name": category.upper(),
                    "category": category,
                    "slot_index": index,
                    "identity": f"identity-{index}",
                    "alternate_key": "C minor",
                    "key": "A minor",
                    "bpm": 140,
                    "peaks": (0.2, 0.4),
                }
            )
        self.page.set_generation_results(
            {"path": "/tmp/cards-master.mp3"}, stems
        )
        APP.processEvents()
        self.assertEqual(len(self.page._stem_cards), 4)
        self.assertTrue(
            all(isinstance(card, PrototypeGenerateCard) for card in self.page._stem_cards)
        )
        first = self.page._stem_cards[0]
        self.assertEqual(first.category_selector.currentText(), "Bass")
        self.assertFalse(hasattr(first, "sync_button"))
        self.assertTrue(first.remove_button.isEnabled())
        self.assertIsInstance(first.midi_handle, GenerateMidiDragHandle)
        self.assertEqual(
            (first.midi_handle.width(), first.midi_handle.height()),
            (28, 20),
        )
        self.assertEqual(first.midi_handle.state, "processing")
        self.assertEqual(len(midi_batches), 1)
        self.assertEqual(len(midi_batches[0]), 4)

        self.page.set_layer_midi_path(
            "/tmp/cards-slot-0.mp3", "/tmp/cards-slot-0.mid"
        )
        self.assertEqual(first.midi_handle.state, "ready")
        self.assertEqual(first.midi_handle.path, "/tmp/cards-slot-0.mid")

        # The selector remains left-aligned while both drag handles are
        # anchored to the right, matching the empty recipe card structure.
        APP.processEvents()
        self.assertLess(first.category_selector.x(), first.width() // 2)
        self.assertGreater(first.midi_handle.x(), first.width() // 2)

    def test_generated_recipe_edits_keep_exactly_one_plus_card(self):
        stems = []
        for index, category in enumerate(("Bass", "Chords", "Lead", "Counter")):
            stems.append(
                {
                    "path": f"/tmp/plus-card-{index}.mp3",
                    "display_name": category.upper(),
                    "category": category,
                    "slot_index": index,
                    "identity": f"plus-identity-{index}",
                    "alternate_key": "C minor",
                    "key": "A minor",
                    "bpm": 140,
                    "peaks": (0.2, 0.4),
                }
            )
        self.page.set_generation_results(
            {"path": "/tmp/plus-master.mp3"}, stems
        )
        self.page._add_slot("Texture")
        self.page._card_remove_requested(4)
        APP.processEvents()
        visible_plus_cards = [
            card
            for card in self.page.findChildren(AddRecipeCard)
            if card.isVisible()
        ]
        self.assertEqual(len(visible_plus_cards), 1)

    def test_library_summary_is_compact_and_has_no_duplicate_total(self):
        counts = {
            "Bass": 432,
            "Chords": 538,
            "Counter": 500,
            "Keys": 84,
            "Lead": 1158,
            "Pad": 197,
            "Pluck": 193,
            "Rhythmic Pluck": 105,
            "Vocal Chop": 103,
            "Bells": 80,
            "Strings": 98,
            "Texture": 73,
            "Guitar Chords": 138,
            "Arp": 130,
        }
        # The third summary argument is the manual-review count.  Actual key
        # uncertainty is delivered separately by the controller status.
        with tempfile.TemporaryDirectory(prefix="stem-slicer-library-") as library:
            self.assertTrue(self.page.restore_library_path(library))
            self.page.set_library_summary(3889, counts, 0)
            expected_folder = Path(library).name
        self.page.set_scan_busy(
            False,
            100,
            "3889 layers loaded from SQLite cache · "
            "3216 safe / 673 uncertain · scan only for new or changed files",
        )
        APP.processEvents()

        self.assertEqual(self.page.library_total_value.text(), "3889 LOADED")
        self.assertFalse(self.page.library_safe_badge.isVisible())
        self.assertEqual(
            self.page.library_review_badge.text(), "673 UNCERTAIN"
        )
        self.assertEqual(
            self.page.scan_status.toolTip(),
            f"{expected_folder} · LIBRARY READY",
        )
        self.assertFalse(self.page.library_total_unit.isVisible())
        self.assertEqual(
            {label.y() for label in self.page.library_category_tokens},
            {2},
        )

    def test_sync_mode_pauses_layers_without_leaving_shared_clock(self):
        stems = []
        for index, category in enumerate(("Bass", "Chords", "Lead", "Counter")):
            stems.append(
                {
                    "path": f"/tmp/sync-card-{index}.mp3",
                    "display_name": category.upper(),
                    "category": category,
                    "slot_index": index,
                    "identity": f"sync-identity-{index}",
                    "alternate_key": "C minor",
                    "key": "A minor",
                    "bpm": 140,
                    "peaks": (0.2, 0.4),
                }
            )
        self.page.set_generation_results(
            {"path": "/tmp/sync-master.mp3"}, stems
        )
        paths = [card.path for card in self.page._stem_cards]
        fake_player = _FakeSynchronizedPlayer(
            paths, self.page._active_layer_paths_changed
        )
        self.page._layer_player = fake_player

        self.page._toggle_all_layers()
        self.assertTrue(self.page._sync_mode)
        self.assertEqual(set(fake_player._device.activePaths()), set(paths))
        self.assertEqual(self.page.all_layers_transport.text(), "SYNC STOP")
        self.assertTrue(
            all(card.play.property("state") == "playing" for card in self.page._stem_cards)
        )

        for path in paths:
            self.page._play_path(path)
        self.assertEqual(fake_player._device.activePaths(), ())
        self.assertTrue(fake_player.isPlaying())
        self.assertEqual(fake_player._device.position, 0.42)
        self.assertTrue(
            all(card.isEnabled() for card in self.page._stem_cards)
        )
        self.assertTrue(
            all(card.play.property("state") == "stopped" for card in self.page._stem_cards)
        )

        self.page._play_path(paths[1])
        self.assertEqual(fake_player._device.activePaths(), (paths[1],))
        self.assertEqual(fake_player._device.position, 0.42)
        self.assertEqual(
            self.page._stem_cards[1].play.property("state"), "playing"
        )

        self.page._toggle_all_layers()
        self.assertFalse(self.page._sync_mode)
        self.assertEqual(fake_player._device.activePaths(), ())
        self.assertEqual(self.page.all_layers_transport.text(), "SYNC PLAY")


if __name__ == "__main__":
    unittest.main()
