import os
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime

from storage import StorageManager, format_decimal_size, safe_name


class MemorySettings:
    def __init__(self):
        self.values = {}

    def value(self, key, default="", type=None):
        return self.values.get(key, default)

    def setValue(self, key, value):
        self.values[key] = value


class StorageTests(unittest.TestCase):
    def test_folder_collisions_use_minute_then_seconds(self):
        with tempfile.TemporaryDirectory() as root:
            settings = MemorySettings()
            settings.setValue("storage/root", root)
            storage = StorageManager(settings, now=lambda: datetime(2026, 7, 12, 18, 42, 37))
            first = storage.unique_session_folder("extractions", "Untitled Folder")
            second = storage.unique_session_folder("extractions", "Untitled Folder")
            third = storage.unique_session_folder("extractions", "Untitled Folder")
            fourth = storage.unique_session_folder("extractions", "Untitled Folder")
            self.assertTrue(first.endswith("Untitled Folder"))
            self.assertTrue(second.endswith("Untitled Folder — 26-07-12 18-42"))
            self.assertTrue(third.endswith("Untitled Folder — 26-07-12 18-42-37"))
            self.assertTrue(fourth.endswith("Untitled Folder — 26-07-12 18-42-37 (2)"))

    def test_file_collisions_increment_numbers(self):
        with tempfile.TemporaryDirectory() as root:
            original = os.path.join(root, "Loop.mp3")
            second = os.path.join(root, "Loop (2).mp3")
            open(original, "wb").close()
            open(second, "wb").close()
            self.assertEqual(StorageManager.unique_file(original), os.path.join(root, "Loop (3).mp3"))

    def test_categories_and_decimal_units(self):
        settings = MemorySettings()
        settings.setValue("storage/root", "/tmp/Stem Slicer Test")
        storage = StorageManager(settings)
        self.assertTrue(storage.category_path("extractions").endswith("Extractions"))
        self.assertTrue(storage.category_path("analyzed").endswith("Analyzed Loops"))
        self.assertTrue(storage.category_path("quick").endswith("Quick Extract"))
        self.assertEqual(format_decimal_size(3_200_000), "3,2 Mo")
        self.assertEqual(safe_name('Bad/Pack:*?'), "Bad-Pack---")

    def test_nested_default_result_cannot_become_workspace_root(self):
        default = StorageManager.default_root()
        nested = os.path.join(default, "Extractions", "New Folder With Items")
        settings = MemorySettings()
        settings.setValue("storage/root", nested)
        storage = StorageManager(settings)

        self.assertEqual(storage.root, default)
        self.assertEqual(
            storage.category_path("analyzed"),
            os.path.join(default, "Analyzed Loops"),
        )

        storage.set_root(os.path.join(default, "Quick Extract"))
        self.assertEqual(settings.values["storage/root"], default)

    def test_quick_extract_history_and_trash_boundary(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            settings = MemorySettings(); settings.setValue("storage/root", root); storage = StorageManager(settings)
            extract = os.path.join(storage.category_path("quick"), "Loop A"); os.makedirs(extract)
            with open(os.path.join(extract, "Loop A_L1.mp3"), "wb") as stream: stream.write(b"1234")
            history = storage.list_quick_extracts()
            self.assertEqual(history[0]["layers"], 1); self.assertEqual(history[0]["size"], 4)
            with patch("storage.QFile.moveToTrash", return_value=True) as move:
                self.assertTrue(storage.move_quick_extract_to_trash(extract))
                move.assert_called_once_with(os.path.realpath(extract))
                self.assertFalse(storage.move_quick_extract_to_trash(outside))


if __name__ == "__main__":
    unittest.main()
