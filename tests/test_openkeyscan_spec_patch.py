import unittest

from scripts.patch_openkeyscan_spec import (
    HIDDEN_IMPORTS_LINE,
    UNIX_FFMPEG_LINE,
    WINDOWS_FFMPEG_LINE,
    patch_spec_source,
)


class OpenKeyScanSpecPatchTests(unittest.TestCase):
    def test_limits_ffmpeg_to_the_native_platform(self):
        source = """from pathlib import Path
if ffmpeg_windows.exists():
    datas.append((str(ffmpeg_windows), '.'))
if ffmpeg_unix.exists():
    datas.append((str(ffmpeg_unix), '.'))
hiddenimports = [
"""

        patched = patch_spec_source(source)

        self.assertIn(WINDOWS_FFMPEG_LINE, patched)
        self.assertIn(UNIX_FFMPEG_LINE, patched)
        self.assertIn(HIDDEN_IMPORTS_LINE, patched)
        self.assertEqual(patched, patch_spec_source(patched))


if __name__ == "__main__":
    unittest.main()
