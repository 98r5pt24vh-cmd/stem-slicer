import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("STEM_SLICER_DISABLE_ENGINE_AUTOSTART", "1")

from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QApplication, QLabel

from functional_core import FileDragHandle, LayerPlayButton
from generation_history_ui import (
    GenerateHistoryManagerDialog,
    GenerateHistoryStore,
    generate_history_stats,
)


APP = QApplication.instance() or QApplication([])


def _make_generation(
    root: Path,
    name: str,
    *,
    stems: tuple[str, ...],
    manifest: bool = True,
) -> Path:
    generation = root / name
    generation.mkdir(parents=True)
    (generation / "00_Generated_Loop_Master.mp3").write_bytes(b"master")
    for index, stem in enumerate(stems, start=1):
        (generation / f"{index:02d}_{stem}.mp3").write_bytes(stem.encode())
    if manifest:
        (generation / "generation.json").write_text(
            json.dumps(
                {
                    "outputs": {
                        "master": "00_Generated_Loop_Master.mp3",
                        "stems": [
                            f"{index:02d}_{stem}.mp3"
                            for index, stem in enumerate(stems, start=1)
                        ],
                    }
                }
            ),
            encoding="utf-8",
        )
    return generation


class GenerateHistoryStoreTests(unittest.TestCase):
    def test_history_reads_manifest_and_falls_back_to_audio_names(self):
        with tempfile.TemporaryDirectory() as workspace:
            root = Path(workspace, "Generated Loops")
            first = _make_generation(root, "First", stems=("Bass", "Lead"))
            second = _make_generation(
                root,
                "Second",
                stems=("Chords", "Counter", "Pad"),
                manifest=False,
            )
            os.utime(first, (10, 10))
            os.utime(second, (20, 20))

            entries = GenerateHistoryStore(root).list_generations()

            self.assertEqual([entry.name for entry in entries], ["Second", "First"])
            self.assertEqual([entry.layers for entry in entries], [3, 2])
            self.assertEqual(
                entries[0].master_path,
                (second / "00_Generated_Loop_Master.mp3").resolve(),
            )
            self.assertEqual(
                entries[1].master_path,
                (first / "00_Generated_Loop_Master.mp3").resolve(),
            )
            count, total_bytes, layers = generate_history_stats(root)
            self.assertEqual((count, layers), (2, 5))
            self.assertEqual(total_bytes, sum(entry.size for entry in entries))

    def test_trash_rejects_root_nested_and_outside_paths(self):
        with tempfile.TemporaryDirectory() as workspace, tempfile.TemporaryDirectory() as outside:
            root = Path(workspace, "Generated Loops")
            generation = _make_generation(root, "Safe", stems=("Bass",))
            nested = generation / "Nested"
            nested.mkdir()
            store = GenerateHistoryStore(root)

            with patch("generation_history_ui.QFile.moveToTrash", return_value=True) as move:
                self.assertFalse(store.move_to_trash(root))
                self.assertFalse(store.move_to_trash(nested))
                self.assertFalse(store.move_to_trash(outside))
                self.assertTrue(store.move_to_trash(generation))
                move.assert_called_once_with(str(generation.resolve()))

    def test_master_manifest_cannot_escape_generation_directory(self):
        with tempfile.TemporaryDirectory() as workspace:
            root = Path(workspace, "Generated Loops")
            generation = root / "Unsafe"
            generation.mkdir(parents=True)
            outside = root / "outside.mp3"
            outside.write_bytes(b"outside")
            (generation / "generation.json").write_text(
                json.dumps({"outputs": {"master": "../outside.mp3", "stems": []}}),
                encoding="utf-8",
            )

            entry = GenerateHistoryStore(root).list_generations()[0]

            self.assertIsNone(entry.master_path)


class GenerateHistoryManagerDialogTests(unittest.TestCase):
    def test_dialog_mirrors_quick_extract_history_content(self):
        with tempfile.TemporaryDirectory() as workspace:
            root = Path(workspace, "Generated Loops")
            _make_generation(root, "Generated_Loop_seed-42", stems=("Bass", "Lead"))
            dialog = GenerateHistoryManagerDialog(root)
            APP.processEvents()
            try:
                self.assertGreaterEqual(dialog.minimumWidth(), 760)
                self.assertGreaterEqual(dialog.minimumHeight(), 520)
                self.assertIn("1 generation", dialog.summary.text())
                self.assertIn("2 layers", dialog.summary.text())
                texts = [item.text() for item in dialog.findChildren(QLabel)]
                self.assertIn("GENERATE HISTORY", texts)
                self.assertIn("Generated_Loop_seed-42", texts)
                self.assertEqual(dialog.property("role"), "managerDialog")
                play_buttons = dialog.findChildren(LayerPlayButton)
                drag_handles = dialog.findChildren(FileDragHandle)
                self.assertEqual(len(play_buttons), 1)
                self.assertEqual(len(drag_handles), 1)
                master = root / "Generated_Loop_seed-42" / "00_Generated_Loop_Master.mp3"
                self.assertTrue(play_buttons[0].isEnabled())
                self.assertEqual(Path(drag_handles[0].path), master.resolve())
            finally:
                dialog.close()
                APP.processEvents()

    def test_manager_play_button_toggles_the_full_loop(self):
        class FakePlayer:
            def __init__(self):
                self.state = QMediaPlayer.PlaybackState.StoppedState
                self.source = None
                self.stopped = False

            def playbackState(self):
                return self.state

            def setSource(self, source):
                self.source = source

            def play(self):
                self.state = QMediaPlayer.PlaybackState.PlayingState

            def pause(self):
                self.state = QMediaPlayer.PlaybackState.PausedState

            def stop(self):
                self.stopped = True
                self.state = QMediaPlayer.PlaybackState.StoppedState

        with tempfile.TemporaryDirectory() as workspace:
            root = Path(workspace, "Generated Loops")
            generation = _make_generation(root, "Playable", stems=("Bass",))
            master = str((generation / "00_Generated_Loop_Master.mp3").resolve())
            dialog = GenerateHistoryManagerDialog(root)
            fake = FakePlayer()
            dialog._player = fake
            try:
                dialog._play_path(master)
                self.assertEqual(
                    fake.state,
                    QMediaPlayer.PlaybackState.PlayingState,
                )
                self.assertEqual(
                    os.path.normcase(str(Path(fake.source.toLocalFile()).resolve())),
                    os.path.normcase(str(Path(master).resolve())),
                )

                dialog._play_path(master)
                self.assertEqual(
                    fake.state,
                    QMediaPlayer.PlaybackState.PausedState,
                )
            finally:
                dialog.close()
                APP.processEvents()
                self.assertTrue(fake.stopped)

    def test_move_all_requires_confirmation(self):
        with tempfile.TemporaryDirectory() as workspace:
            root = Path(workspace, "Generated Loops")
            _make_generation(root, "One", stems=("Bass",))
            _make_generation(root, "Two", stems=("Lead",))
            dialog = GenerateHistoryManagerDialog(root)
            try:
                with patch.object(
                    dialog.history, "move_to_trash", return_value=True
                ) as move:
                    dialog._move_all()
                    self.assertTrue(dialog.confirm_all)
                    self.assertIn("CONFIRM", dialog.trash_all.text())
                    move.assert_not_called()

                    dialog._move_all()
                    self.assertEqual(move.call_count, 2)
            finally:
                dialog.close()


if __name__ == "__main__":
    unittest.main()
