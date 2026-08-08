import unittest
from unittest.mock import patch

import key_detection
from key_detection import format_camelot


class KeyDetectionFormattingTests(unittest.TestCase):
    def test_windows_analyzer_process_is_hidden(self):
        class StartupInfo:
            def __init__(self):
                self.dwFlags = 0
                self.wShowWindow = None

        with (
            patch.object(key_detection.sys, "platform", "win32"),
            patch.object(key_detection.subprocess, "STARTUPINFO", StartupInfo, create=True),
            patch.object(key_detection.subprocess, "STARTF_USESHOWWINDOW", 1, create=True),
            patch.object(key_detection.subprocess, "SW_HIDE", 0, create=True),
            patch.object(key_detection.subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True),
        ):
            options = key_detection.hidden_process_options()
        self.assertEqual(options["creationflags"], 0x08000000)
        self.assertEqual(options["startupinfo"].dwFlags, 1)
        self.assertEqual(options["startupinfo"].wShowWindow, 0)

    def test_detected_and_relative_modes_with_both_notations(self):
        self.assertEqual(format_camelot("3A", "detected", "sharps"), "A#m")
        self.assertEqual(format_camelot("3A", "detected", "flats"), "Bbm")
        self.assertEqual(format_camelot("3A", "relative_major", "sharps"), "C#")
        self.assertEqual(format_camelot("3A", "relative_major", "flats"), "Db")
        self.assertEqual(format_camelot("3B", "relative_minor", "sharps"), "A#m")
        self.assertEqual(format_camelot("3B", "relative_minor", "flats"), "Bbm")


if __name__ == "__main__":
    unittest.main()
