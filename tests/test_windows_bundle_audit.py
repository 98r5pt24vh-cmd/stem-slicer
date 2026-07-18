import os
import tempfile
import unittest

from scripts.audit_windows_bundle import audit_bundle


class WindowsBundleAuditTests(unittest.TestCase):
    def make_file(self, root, relative, contents=b"test"):
        path = os.path.join(root, *relative.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as output:
            output.write(contents)
        return path

    def make_valid_bundle(self, bundle, *, include_basic_pitch=True, include_bpm_warmup=True):
        self.make_file(bundle, "Stem Slicer 1.6B.exe")
        engine = "_internal/openkeyscan-analyzer"
        self.make_file(bundle, f"{engine}/openkeyscan-analyzer.exe")
        self.make_file(bundle, f"{engine}/_internal/checkpoints/openkeyscan3.pt")
        self.make_file(bundle, f"{engine}/_internal/checkpoints/deeprhythm-0.7.pth")
        self.make_file(bundle, f"{engine}/_internal/torch/lib/torch_cpu.dll")
        self.make_file(bundle, "_internal/bin/bungee.exe")
        self.make_file(bundle, "_internal/ffmpeg.exe")
        if include_bpm_warmup:
            self.make_file(bundle, "_internal/assets/key-and-bpm-engine-warmup.wav")
        if include_basic_pitch:
            self.make_file(bundle, "_internal/basic_pitch/saved_models/icassp_2022/nmp.onnx")

    def test_accepts_one_isolated_key_engine_and_one_midi_model(self):
        with tempfile.TemporaryDirectory() as bundle:
            self.make_valid_bundle(bundle)

            result = audit_bundle(bundle)

            self.assertEqual(len(result["models"]), 3)
            self.assertEqual(len(result["openkey_models"]), 1)
            self.assertEqual(len(result["deeprhythm_models"]), 1)
            self.assertEqual(len(result["basic_pitch_models"]), 1)
            self.assertEqual(len(result["torch_cpu"]), 1)
            self.assertEqual(len(result["bungee"]), 1)
            self.assertEqual(len(result["ffmpeg"]), 1)

    def test_rejects_parent_bundle_torch_duplicate(self):
        with tempfile.TemporaryDirectory() as bundle:
            self.make_valid_bundle(bundle)
            self.make_file(bundle, "_internal/torch/lib/torch_cpu.dll")

            with self.assertRaisesRegex(RuntimeError, "found 2"):
                audit_bundle(bundle)

    def test_rejects_missing_basic_pitch_model(self):
        with tempfile.TemporaryDirectory() as bundle:
            self.make_valid_bundle(bundle, include_basic_pitch=False)

            with self.assertRaisesRegex(RuntimeError, "Basic Pitch model, found 0"):
                audit_bundle(bundle)

    def test_rejects_extensionless_openkeyscan_ffmpeg(self):
        with tempfile.TemporaryDirectory() as bundle:
            self.make_valid_bundle(bundle)
            engine = "_internal/openkeyscan-analyzer"
            self.make_file(bundle, f"{engine}/_internal/ffmpeg")

            with self.assertRaisesRegex(RuntimeError, "extensionless FFmpeg"):
                audit_bundle(bundle)

    def test_rejects_duplicate_bungee(self):
        with tempfile.TemporaryDirectory() as bundle:
            self.make_valid_bundle(bundle)
            self.make_file(bundle, "_internal/other/bungee.exe")

            with self.assertRaisesRegex(RuntimeError, "Bungee executable"):
                audit_bundle(bundle)

    def test_rejects_missing_bpm_warmup(self):
        with tempfile.TemporaryDirectory() as bundle:
            self.make_valid_bundle(bundle, include_bpm_warmup=False)

            with self.assertRaisesRegex(RuntimeError, "warm-up audio"):
                audit_bundle(bundle)


if __name__ == "__main__":
    unittest.main()
