import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WindowsReleaseConfigTests(unittest.TestCase):
    def _read(self, relative_path):
        return (ROOT / relative_path).read_text(encoding="utf-8")

    def test_parent_application_is_a_non_elevated_gui_executable(self):
        spec = self._read("StemSlicerWindows.spec")
        self.assertIn('name="Stem Slicer 1.9B"', spec)
        self.assertIn("console=False", spec)
        self.assertIn("uac_admin=False", spec)
        self.assertIn('("bin/bungee.exe", "bin")', spec)
        self.assertIn('("assets/key-and-bpm-engine-warmup.wav", "assets")', spec)

    def test_generate_model_payload_is_bundled_for_offline_scans(self):
        spec = self._read("StemSlicerWindows.spec")
        self.assertIn('("models/layer_roles_v1.joblib", "models")', spec)
        self.assertIn("models/huggingface/models--m-a-p--MERT-v1-95M", spec)
        self.assertIn('"mert_worker"', spec)
        self.assertIn('"torch"', spec)
        self.assertIn('"transformers"', spec)
        self.assertNotIn('\n        "torch",\n', spec.split("excludes=[", 1)[1])

    def test_all_external_process_launchers_hide_windows_consoles(self):
        for relative_path in (
            "analyzer/loop_bpm.py",
            "audio_convert.py",
            "engine.py",
            "key_detection.py",
            "layer_library.py",
            "mert_client.py",
        ):
            with self.subTest(path=relative_path):
                source = self._read(relative_path)
                self.assertIn("STARTF_USESHOWWINDOW", source)
                self.assertIn("SW_HIDE", source)
                self.assertIn("CREATE_NO_WINDOW", source)

    def test_first_windows_midi_conversion_skips_numba_jit_compilation(self):
        source = self._read("midi_conversion.py")
        self.assertIn('if sys.platform == "win32":', source)
        self.assertIn('os.environ.setdefault("NUMBA_DISABLE_JIT", "1")', source)

    def test_workflow_uses_exact_runtime_and_release_gates(self):
        workflow = self._read(".github/workflows/build-windows.yml")
        self.assertIn("Build Stem Slicer 1.9B for Windows", workflow)
        self.assertIn("Set up official CPython 3.12.10 x64", workflow)
        self.assertIn("uses: actions/setup-python@v6", workflow)
        self.assertIn('python-version: "3.12.10"', workflow)
        self.assertIn("assert sys.version_info[:3] == (3, 12, 10)", workflow)
        self.assertNotIn("cpython-source", workflow)
        self.assertNotIn("PCbuild/build.bat", workflow)
        self.assertIn("PySide6==6.11.1", self._read("requirements.txt"))
        self.assertIn("746833f68a574d997ec50443e7cfd2d37b026302", workflow)
        self.assertIn("-DBUNGEE_VERSION=2.4.24", workflow)
        self.assertIn("-DBUNGEE_BUILD_SHARED_LIBRARY=OFF", workflow)
        self.assertIn("git apply ../patches/bungee-waveformatextensible.patch", workflow)
        self.assertIn("scripts/diagnose_midi_startup.py", workflow)
        self.assertIn("--mode quick-extract-midi", workflow)
        self.assertIn("--timeout 30", workflow)
        self.assertIn("--require-ready", workflow)
        self.assertIn("scripts/fetch_mert_payload.py", workflow)
        self.assertIn("scripts/smoke_windows_bundle.py", workflow)
        self.assertIn("scripts/audit_windows_bundle.py", workflow)
        self.assertIn("Stem-Slicer-1.9B-Windows.zip", workflow)
        self.assertIn("validation-output/Stem Slicer 1.9B", workflow)

    def test_mert_fetch_is_revision_and_hash_pinned(self):
        source = self._read("scripts/fetch_mert_payload.py")
        self.assertIn(
            'REVISION = "12af15fef9d0ac838c3f475bfbbf26d2060dd4f5"',
            source,
        )
        self.assertIn(
            '"pytorch_model.bin": "a2b8b747f72c06e0595aeae41ae5473f4364938c6b39b2c58be38c48e6bd3fcd"',
            source,
        )
        self.assertIn(
            '"sha256": "1fa9897e43c5e57241bc5a3687d621516b69c503a515d663a1d4deef061a764b"',
            source,
        )

    def test_bungee_patch_supports_ffmpeg_extensible_float_wav(self):
        patch_source = self._read("patches/bungee-waveformatextensible.patch")
        self.assertIn("sampleFormat == 0xfffe", patch_source)
        self.assertIn("sampleFormat = read<uint16_t>(&wavHeader[44])", patch_source)
        self.assertIn("read<uint16_t>(&wavHeader[38]) == bitsPerSample", patch_source)
        self.assertIn("0x00100000", patch_source)
        self.assertIn("0xaa000080", patch_source)
        self.assertIn("0x719b3800", patch_source)

    def test_custom_analyzer_contains_validated_loop_bpm_mode(self):
        analyzer = self._read("analyzer/openkeyscan_analyzer_server.py")
        loop_bpm = self._read("analyzer/loop_bpm.py")
        self.assertIn("bpm_mode == 'quick_scan_loop'", analyzer)
        self.assertIn("analyze_loop_bpm", analyzer)
        self.assertIn("def analyze_loop_bpm", loop_bpm)


if __name__ == "__main__":
    unittest.main()
