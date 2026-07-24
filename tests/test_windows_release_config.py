import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WindowsReleaseConfigTests(unittest.TestCase):
    def _read(self, relative_path):
        return (ROOT / relative_path).read_text(encoding="utf-8")

    def test_parent_application_is_a_non_elevated_gui_executable(self):
        spec = self._read("StemSlicerWindows.spec")
        self.assertIn('name="Stem Slicer 1.8.2B"', spec)
        self.assertIn("console=False", spec)
        self.assertIn("uac_admin=False", spec)
        self.assertIn('("bin/bungee.exe", "bin")', spec)
        self.assertIn('("assets/key-and-bpm-engine-warmup.wav", "assets")', spec)

    def test_all_external_process_launchers_hide_windows_consoles(self):
        for relative_path in ("audio_convert.py", "engine.py", "key_detection.py"):
            with self.subTest(path=relative_path):
                source = self._read(relative_path)
                self.assertIn("STARTF_USESHOWWINDOW", source)
                self.assertIn("SW_HIDE", source)
                self.assertIn("CREATE_NO_WINDOW", source)

    def test_workflow_builds_the_pinned_custom_engines_and_runs_release_gates(self):
        workflow = self._read(".github/workflows/build-windows.yml")
        self.assertIn("Build Stem Slicer 1.8.2B for Windows", workflow)
        self.assertIn("Build official CPython 3.12.13 x64", workflow)
        self.assertIn("3bb231a6a5dc02b95658877318bf61501a7209e9", workflow)
        self.assertIn('Set-Content -Path "PCbuild/msbuild.rsp" -Value "/p:PlatformToolset=v143"', workflow)
        self.assertIn('PCbuild/build.bat" -e -p x64', workflow)
        self.assertIn("PySide6==6.11.1", self._read("requirements.txt"))
        self.assertIn("746833f68a574d997ec50443e7cfd2d37b026302", workflow)
        self.assertIn("-DBUNGEE_VERSION=2.4.24", workflow)
        self.assertIn("-DBUNGEE_BUILD_SHARED_LIBRARY=OFF", workflow)
        self.assertIn("git apply ../patches/bungee-waveformatextensible.patch", workflow)
        self.assertIn("./bin/bungee.exe --help", workflow)
        self.assertIn("msys-2\\.0", workflow)
        self.assertIn("scripts/smoke_windows_bundle.py", workflow)
        self.assertIn("scripts/audit_windows_bundle.py", workflow)
        self.assertIn("Stem-Slicer-1.8.2B-Windows", workflow)

    def test_bungee_patch_supports_ffmpeg_extensible_float_wav(self):
        patch_source = self._read("patches/bungee-waveformatextensible.patch")
        self.assertIn("sampleFormat == 0xfffe", patch_source)
        self.assertIn("sampleFormat = read<uint16_t>(&wavHeader[44])", patch_source)
        self.assertIn("read<uint16_t>(&wavHeader[38]) == bitsPerSample", patch_source)
        self.assertIn("0x00100000", patch_source)
        self.assertIn("0xaa000080", patch_source)
        self.assertIn("0x719b3800", patch_source)

    def test_custom_analyzer_contains_the_validated_loop_bpm_mode(self):
        analyzer = self._read("analyzer/openkeyscan_analyzer_server.py")
        loop_bpm = self._read("analyzer/loop_bpm.py")
        self.assertIn("bpm_mode == 'quick_scan_loop'", analyzer)
        self.assertIn("analyze_loop_bpm", analyzer)
        self.assertIn("def analyze_loop_bpm", loop_bpm)


if __name__ == "__main__":
    unittest.main()
