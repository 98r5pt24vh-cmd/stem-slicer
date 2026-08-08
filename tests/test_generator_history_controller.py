import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("STEM_SLICER_DISABLE_ENGINE_AUTOSTART", "1")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

import generator_controller


APP = QApplication.instance() or QApplication([])


class _Window(QObject):
    scanRequested = Signal(str)
    generateRequested = Signal(dict)
    generateAgainRequested = Signal(dict)
    previewSeedRequested = Signal()
    lockChanged = Signal(int, str, bool)
    openOutputRequested = Signal()
    manageRequested = Signal()

    def __init__(self):
        super().__init__()
        self.summary = None
        self.preview_available = None

    def set_generation_history_summary(self, count, total_bytes, layers):
        self.summary = (count, total_bytes, layers)

    def set_preview_seed_available(self, available):
        self.preview_available = bool(available)

    def set_generation_busy(self, *_args):
        pass


class _Classifier:
    def __init__(self, **_kwargs):
        pass

    def stop(self):
        pass


def _generation(root: Path, name: str, stems: int) -> Path:
    folder = root / name
    folder.mkdir(parents=True)
    (folder / "00_Generated_Loop_Master.mp3").write_bytes(b"master")
    names = []
    for index in range(stems):
        filename = f"{index + 1:02d}_Layer.mp3"
        (folder / filename).write_bytes(b"stem")
        names.append(filename)
    (folder / "generation.json").write_text(
        json.dumps({"outputs": {"stems": names}}), encoding="utf-8"
    )
    return folder


class GeneratorHistoryControllerTests(unittest.TestCase):
    def _controller(self, root: Path):
        window = _Window()
        patches = (
            patch.object(generator_controller, "MertLayerClassifier", _Classifier),
            patch.object(generator_controller, "default_output_root", return_value=root),
        )
        patches[0].start()
        patches[1].start()
        self.addCleanup(patches[1].stop)
        self.addCleanup(patches[0].stop)
        controller = generator_controller.GeneratorController(window)
        self.addCleanup(controller.shutdown)
        return controller, window

    def test_persistent_inventory_and_decimal_summary(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary, "Generated Loops")
            _generation(root, "Older", 1)
            newest = _generation(root, "Newest", 2)
            os.utime(root / "Older", (10, 10))
            os.utime(newest, (20, 20))
            controller, window = self._controller(root)

            payload = controller.refresh_generation_history()

            self.assertEqual(payload["count"], 2)
            self.assertEqual(payload["layers"], 3)
            self.assertEqual(payload["entries"][0]["name"], "Newest")
            self.assertEqual(window.summary, (2, payload["total_bytes"], 3))
            self.assertEqual(
                controller.generation_history_summary()["total_size"],
                payload["total_size"],
            )

    def test_open_is_restricted_to_root_and_direct_generations(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary, "Generated Loops")
            generation = _generation(root, "Safe", 1)
            nested = generation / "nested"
            nested.mkdir()
            controller, _window = self._controller(root)

            with patch.object(generator_controller, "open_in_file_manager") as opened:
                self.assertTrue(controller.open_generation_output(""))
                self.assertTrue(controller.open_generation_output(str(generation)))
                self.assertFalse(controller.open_generation_output(str(nested)))

            self.assertEqual(opened.call_count, 2)

    def test_targeted_trash_prunes_only_matching_previous_seed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary, "Generated Loops")
            first = _generation(root, "First", 1)
            second = _generation(root, "Second", 1)
            controller, window = self._controller(root)
            controller._generation_history.extend(
                [
                    {"seed": 1, "output_directory": str(first)},
                    {"seed": 2, "output_directory": str(second)},
                ]
            )
            controller._history_index = 1
            controller.last_output = second

            with patch(
                "generation_history_ui.QFile.moveToTrash", return_value=True
            ) as move:
                self.assertTrue(controller.trash_generation_output(str(second)))

            move.assert_called_once_with(str(second.resolve()))
            self.assertEqual(
                [item["seed"] for item in controller._generation_history], [1]
            )
            self.assertIsNone(controller.last_output)
            self.assertFalse(window.preview_available)

    def test_trash_is_blocked_while_a_generation_is_active(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary, "Generated Loops")
            generation = _generation(root, "Safe", 1)
            controller, _window = self._controller(root)
            controller._render_thread = object()
            self.addCleanup(setattr, controller, "_render_thread", None)

            with patch.object(
                generator_controller.GenerateHistoryStore, "move_to_trash"
            ) as move:
                self.assertFalse(controller.trash_generation_output(str(generation)))
            move.assert_not_called()

    def test_kept_alternate_key_is_carried_into_generate_again(self):
        with tempfile.TemporaryDirectory() as temporary:
            controller, _window = self._controller(Path(temporary))
            controller._generation_history.append(
                {
                    "selection_identities": ("bass-id", "lead-id"),
                    "locked_slots": ((0, "bass-id"),),
                    "stems": (
                        {
                            "slot_index": 0,
                            "identity": "bass-id",
                            "locked": True,
                            "alternate_key_used": True,
                            "manual_pitch_semitones": 12,
                            "normalization_enabled": True,
                        },
                        {
                            "slot_index": 1,
                            "identity": "lead-id",
                            "locked": False,
                            "alternate_key_used": False,
                        },
                    ),
                }
            )
            controller._history_index = 0

            payload = controller._generation_payload(
                {
                    "categories": ("Bass", "Lead"),
                    "locked_slots": ((0, "bass-id"),),
                }
            )

            self.assertEqual(payload["alternate_key_slots"], ((0, "bass-id"),))
            self.assertEqual(
                payload["manual_pitch_slots"],
                ((0, "bass-id", 12),),
            )
            self.assertEqual(
                payload["normalization_slots"],
                ((0, "bass-id"),),
            )

    def test_restored_original_card_carries_no_optional_key_or_gain_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            controller, _window = self._controller(Path(temporary))
            controller._generation_history.append(
                {
                    "selection_identities": ("bass-id",),
                    "locked_slots": ((0, "bass-id"),),
                    "stems": (
                        {
                            "slot_index": 0,
                            "identity": "bass-id",
                            "locked": True,
                            "alternate_key_used": False,
                            "manual_pitch_semitones": 0,
                            "normalization_enabled": False,
                        },
                    ),
                }
            )
            controller._history_index = 0
            payload = controller._generation_payload(
                {
                    "categories": ("Bass",),
                    "locked_slots": ((0, "bass-id"),),
                }
            )
            self.assertEqual(payload["alternate_key_slots"], ())
            self.assertEqual(payload["manual_pitch_slots"], ())
            self.assertEqual(payload["normalization_slots"], ())

    def test_adjustments_follow_kept_identity_after_recipe_reindex(self):
        with tempfile.TemporaryDirectory() as temporary:
            controller, _window = self._controller(Path(temporary))
            controller._generation_history.append(
                {
                    "selection_identities": ("lead-id",),
                    "locked_slots": ((2, "lead-id"),),
                    "stems": (
                        {
                            "slot_index": 2,
                            "identity": "lead-id",
                            "locked": True,
                            "alternate_key_used": True,
                            "manual_pitch_semitones": -12,
                            "normalization_enabled": True,
                        },
                    ),
                }
            )
            controller._history_index = 0
            payload = controller._generation_payload(
                {
                    "categories": ("Bass", "Lead"),
                    "locked_slots": ((1, "lead-id"),),
                }
            )
            self.assertEqual(payload["alternate_key_slots"], ((1, "lead-id"),))
            self.assertEqual(
                payload["manual_pitch_slots"],
                ((1, "lead-id", -12),),
            )
            self.assertEqual(
                payload["normalization_slots"],
                ((1, "lead-id"),),
            )


if __name__ == "__main__":
    unittest.main()
