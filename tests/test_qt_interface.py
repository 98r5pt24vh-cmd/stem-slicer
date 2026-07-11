import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app import MainWindow
from filename_templates import TOKENS
from widgets import TokenStrip


APP = QApplication.instance() or QApplication([])


class QtInterfaceTests(unittest.TestCase):
    def test_default_and_key_only_states(self):
        window = MainWindow()
        self.assertTrue(window.slicer_module.isChecked())
        self.assertFalse(window.key_module.isChecked())
        self.assertFalse(window.token_strip.isEnabled())
        self.assertEqual(window.token_strip.tokens, list(TOKENS))
        window.key_module.setChecked(True)
        self.assertTrue(window.token_strip.isEnabled())
        self.assertIn("A#m CALLMEUR3 137 +NRGY", window.preview.text())
        window.slicer_module.setChecked(False)
        self.assertTrue(window.destination_box.isVisibleTo(window))
        self.assertEqual(window.start_button.text(), "ANALYZE + ORGANIZE LOOPS")
        window.close()

    def test_each_edge_chip_can_cross_the_full_strip(self):
        strip = TokenStrip(TOKENS)
        strip.resize(700, 66)
        strip.setEnabled(True)
        strip.show()
        APP.processEvents()

        first = strip.chipRects()[0].center()
        last = strip.chipRects()[-1].center()
        QTest.mousePress(strip, Qt.LeftButton, Qt.NoModifier, QPoint(int(first.x()), int(first.y())))
        QTest.mouseMove(strip, QPoint(int(last.x() + 80), int(last.y())), 20)
        QTest.mouseRelease(strip, Qt.LeftButton, Qt.NoModifier, QPoint(int(last.x() + 80), int(last.y())))
        self.assertEqual(strip.tokens[-1], "KEY")

        last = strip.chipRects()[-1].center()
        first = strip.chipRects()[0].center()
        QTest.mousePress(strip, Qt.LeftButton, Qt.NoModifier, QPoint(int(last.x()), int(last.y())))
        QTest.mouseMove(strip, QPoint(max(2, int(first.x() - 80)), int(first.y())), 20)
        QTest.mouseRelease(strip, Qt.LeftButton, Qt.NoModifier, QPoint(max(2, int(first.x() - 80)), int(first.y())))
        self.assertEqual(strip.tokens[0], "KEY")
        strip.close()


if __name__ == "__main__":
    unittest.main()
