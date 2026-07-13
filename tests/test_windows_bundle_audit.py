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

    def test_accepts_one_isolated_key_engine(self):
        with tempfile.TemporaryDirectory() as bundle:
            self.make_file(bundle, "Stem Slicer 1.4.1 M.exe")
            engine = "_internal/openkeyscan-analyzer"
            self.make_file(bundle, f"{engine}/openkeyscan-analyzer.exe")
            self.make_file(bundle, f"{engine}/_internal/checkpoints/openkeyscan3.pt")
            self.make_file(bundle, f"{engine}/_internal/torch/lib/torch_cpu.dll")

            result = audit_bundle(bundle)

            self.assertEqual(len(result["models"]), 1)
            self.assertEqual(len(result["torch_cpu"]), 1)

    def test_rejects_parent_bundle_torch_duplicate(self):
        with tempfile.TemporaryDirectory() as bundle:
            engine = "_internal/openkeyscan-analyzer"
            self.make_file(bundle, f"{engine}/openkeyscan-analyzer.exe")
            self.make_file(bundle, f"{engine}/_internal/checkpoints/openkeyscan3.pt")
            self.make_file(bundle, f"{engine}/_internal/torch/lib/torch_cpu.dll")
            self.make_file(bundle, "_internal/torch/lib/torch_cpu.dll")

            with self.assertRaisesRegex(RuntimeError, "found 2"):
                audit_bundle(bundle)


if __name__ == "__main__":
    unittest.main()
