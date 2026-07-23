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

    def test_accepts_one_isolated_analysis_engine_and_one_midi_model(self):
        with tempfile.TemporaryDirectory() as bundle:
            self.make_file(bundle, "Stem Slicer 1.5S Beta.exe")
            engine = "_internal/openkeyscan-analyzer"
            self.make_file(bundle, f"{engine}/openkeyscan-analyzer.exe")
            self.make_file(bundle, f"{engine}/_internal/checkpoints/openkeyscan3.pt")
            self.make_file(bundle, f"{engine}/_internal/checkpoints/deeprhythm-0.7.pth")
            self.make_file(bundle, f"{engine}/_internal/torch/lib/torch_cpu.dll")
            self.make_file(bundle, "_internal/basic_pitch/saved_models/icassp_2022/nmp.onnx")

            result = audit_bundle(bundle)

            self.assertEqual(len(result["models"]), 3)
            self.assertEqual(len(result["openkey_models"]), 1)
            self.assertEqual(len(result["deeprhythm_models"]), 1)
            self.assertEqual(len(result["basic_pitch_models"]), 1)
            self.assertEqual(len(result["torch_cpu"]), 1)

    def test_rejects_parent_bundle_torch_duplicate(self):
        with tempfile.TemporaryDirectory() as bundle:
            engine = "_internal/openkeyscan-analyzer"
            self.make_file(bundle, f"{engine}/openkeyscan-analyzer.exe")
            self.make_file(bundle, f"{engine}/_internal/checkpoints/openkeyscan3.pt")
            self.make_file(bundle, f"{engine}/_internal/checkpoints/deeprhythm-0.7.pth")
            self.make_file(bundle, f"{engine}/_internal/torch/lib/torch_cpu.dll")
            self.make_file(bundle, "_internal/basic_pitch/saved_models/icassp_2022/nmp.onnx")
            self.make_file(bundle, "_internal/torch/lib/torch_cpu.dll")

            with self.assertRaisesRegex(RuntimeError, "found 2"):
                audit_bundle(bundle)

    def test_rejects_missing_basic_pitch_model(self):
        with tempfile.TemporaryDirectory() as bundle:
            engine = "_internal/openkeyscan-analyzer"
            self.make_file(bundle, f"{engine}/openkeyscan-analyzer.exe")
            self.make_file(bundle, f"{engine}/_internal/checkpoints/openkeyscan3.pt")
            self.make_file(bundle, f"{engine}/_internal/checkpoints/deeprhythm-0.7.pth")
            self.make_file(bundle, f"{engine}/_internal/torch/lib/torch_cpu.dll")

            with self.assertRaisesRegex(RuntimeError, "Basic Pitch model, found 0"):
                audit_bundle(bundle)

    def test_rejects_extensionless_openkeyscan_ffmpeg(self):
        with tempfile.TemporaryDirectory() as bundle:
            engine = "_internal/openkeyscan-analyzer"
            self.make_file(bundle, f"{engine}/openkeyscan-analyzer.exe")
            self.make_file(bundle, f"{engine}/_internal/checkpoints/openkeyscan3.pt")
            self.make_file(bundle, f"{engine}/_internal/checkpoints/deeprhythm-0.7.pth")
            self.make_file(bundle, f"{engine}/_internal/torch/lib/torch_cpu.dll")
            self.make_file(bundle, f"{engine}/_internal/ffmpeg")
            self.make_file(bundle, "_internal/basic_pitch/saved_models/icassp_2022/nmp.onnx")

            with self.assertRaisesRegex(RuntimeError, "extensionless FFmpeg"):
                audit_bundle(bundle)


if __name__ == "__main__":
    unittest.main()
