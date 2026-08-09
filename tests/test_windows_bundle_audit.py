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

    def make_valid_bundle(self, bundle, *, include_mert=True):
        self.make_file(bundle, "Stem Slicer 1.9B.exe")
        engine = "_internal/openkeyscan-analyzer"
        self.make_file(bundle, f"{engine}/openkeyscan-analyzer.exe")
        self.make_file(bundle, f"{engine}/_internal/checkpoints/openkeyscan3.pt")
        self.make_file(
            bundle, f"{engine}/_internal/checkpoints/deeprhythm-0.7.pth"
        )
        self.make_file(bundle, f"{engine}/_internal/torch/lib/torch_cpu.dll")
        self.make_file(bundle, "_internal/torch/lib/torch_cpu.dll")
        self.make_file(
            bundle, "_internal/basic_pitch/saved_models/icassp_2022/nmp.onnx"
        )
        if include_mert:
            self.make_file(
                bundle,
                "_internal/models/huggingface/models--m-a-p--MERT-v1-95M/"
                "snapshots/12af15fef9d0ac838c3f475bfbbf26d2060dd4f5/"
                "pytorch_model.bin",
            )

    def test_accepts_isolated_analysis_and_parent_mert_runtimes(self):
        with tempfile.TemporaryDirectory() as bundle:
            self.make_valid_bundle(bundle)
            result = audit_bundle(bundle)

            self.assertEqual(len(result["models"]), 4)
            self.assertEqual(len(result["openkey_models"]), 1)
            self.assertEqual(len(result["deeprhythm_models"]), 1)
            self.assertEqual(len(result["basic_pitch_models"]), 1)
            self.assertEqual(len(result["mert_models"]), 1)
            self.assertEqual(len(result["torch_cpu"]), 2)

    def test_rejects_a_third_torch_duplicate(self):
        with tempfile.TemporaryDirectory() as bundle:
            self.make_valid_bundle(bundle)
            self.make_file(bundle, "_internal/duplicate/torch_cpu.dll")
            with self.assertRaisesRegex(RuntimeError, "parent MERT Torch runtime"):
                audit_bundle(bundle)

    def test_rejects_missing_mert_model(self):
        with tempfile.TemporaryDirectory() as bundle:
            self.make_valid_bundle(bundle, include_mert=False)
            with self.assertRaisesRegex(RuntimeError, "mert_models, found 0"):
                audit_bundle(bundle)

    def test_rejects_extensionless_openkeyscan_ffmpeg(self):
        with tempfile.TemporaryDirectory() as bundle:
            self.make_valid_bundle(bundle)
            self.make_file(
                bundle, "_internal/openkeyscan-analyzer/_internal/ffmpeg"
            )
            with self.assertRaisesRegex(RuntimeError, "extensionless FFmpeg"):
                audit_bundle(bundle)

    def test_rejects_macos_binary_in_windows_bundle(self):
        with tempfile.TemporaryDirectory() as bundle:
            self.make_valid_bundle(bundle)
            self.make_file(bundle, "_internal/libforeign.dylib")
            with self.assertRaisesRegex(RuntimeError, "non-Windows binaries"):
                audit_bundle(bundle)


if __name__ == "__main__":
    unittest.main()
