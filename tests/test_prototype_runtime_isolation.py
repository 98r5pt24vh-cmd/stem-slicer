import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PrototypeRuntimeIsolationTests(unittest.TestCase):
    def test_default_runtime_namespace_remains_accepted_19(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('"STEM_SLICER_RUNTIME_DATA_VERSION"', source)
        self.assertIn('"1.9"', source)

    def test_prototype_launcher_selects_separate_namespace(self):
        source = (
            ROOT / "scripts" / "run_generate_prototype.py"
        ).read_text(encoding="utf-8")
        self.assertIn('PROTOTYPE_RUNTIME_VERSION = "prototype-generate"', source)
        self.assertIn('environment["STEM_SLICER_RUNTIME_DATA_VERSION"]', source)


if __name__ == "__main__":
    unittest.main()
