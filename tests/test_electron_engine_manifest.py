import ast
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "electron-app" / "python" / "engine-manifest.json"
BRIDGE_PATH = ROOT / "electron-app" / "python" / "engine_bridge.py"
LEGACY_UI_MODULES = {
    "app.py",
    "functional_core.py",
    "generate_midi_bridge.py",
    "generation_history_ui.py",
    "generator_controller.py",
    "generator_ui.py",
    "generator_ui_base.py",
    "stem_workflow.py",
    "storage.py",
    "synchronized_layer_player.py",
    "theme.py",
    "validated_ui.py",
    "widgets.py",
}


def local_imports(source: Path, local_roots: set[str]) -> set[str]:
    modules = set()
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name.split(".", 1)[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module.split(".", 1)[0]]
        else:
            continue
        modules.update(name for name in names if name in local_roots)
    return modules


class ElectronEngineManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        cls.common = set(cls.manifest["commonFiles"])

    def test_every_manifest_entry_exists(self):
        for relative in self.common:
            with self.subTest(path=relative):
                self.assertTrue((ROOT / relative).is_file())
        for relative in self.manifest["externalDirectories"]:
            with self.subTest(path=relative):
                self.assertTrue((ROOT / relative).is_dir())

    def test_manifest_excludes_legacy_ui_modules(self):
        self.assertTrue(self.common.isdisjoint(LEGACY_UI_MODULES))

    def test_macos_uses_runtime_ffmpeg_instead_of_an_untracked_vendor_binary(self):
        self.assertNotIn("vendor/ffmpeg-bin/ffmpeg", self.manifest["platformFiles"]["darwin"])
        requirements = (ROOT / "electron-app" / "python" / "requirements-runtime.txt").read_text(
            encoding="utf-8"
        )
        engine = (ROOT / "engine.py").read_text(encoding="utf-8")
        self.assertIn("imageio-ffmpeg==", requirements)
        self.assertIn("imageio_ffmpeg.get_ffmpeg_exe()", engine)

    def test_mert_defaults_never_fall_back_to_an_external_research_checkout(self):
        sources = [
            ROOT / "mert_client.py",
            ROOT / "mert_worker.py",
            ROOT / "tools" / "prefill_runtime_cache.py",
        ]
        combined = "\n".join(source.read_text(encoding="utf-8") for source in sources)
        self.assertNotIn("layer_role_benchmark_2026-07-30", combined)
        self.assertNotIn("Stem Slicer Generate Prototype", combined)
        self.assertIn('SOURCE_ROOT / "models" / "huggingface"', combined)

    def test_every_local_engine_import_is_packaged(self):
        root_modules = {path.stem for path in ROOT.glob("*.py")}
        packaged_modules = {Path(path).stem for path in self.common if "/" not in path and path.endswith(".py")}
        sources = [BRIDGE_PATH, *(ROOT / path for path in self.common if "/" not in path and path.endswith(".py"))]
        required = set()
        for source in sources:
            required.update(local_imports(source, root_modules))
        self.assertEqual(required - packaged_modules, set())

    def test_analyzer_runtime_imports_are_packaged(self):
        analyzer_files = {
            path.removeprefix("analyzer/")
            for path in self.common
            if path.startswith("analyzer/") and path.endswith(".py")
        }
        analyzer_modules = {Path(path).stem for path in analyzer_files}
        required = set()
        for relative in analyzer_files:
            required.update(local_imports(ROOT / "analyzer" / relative, analyzer_modules))
        packaged_names = {Path(path).stem for path in analyzer_files}
        self.assertEqual(required - packaged_names, set())

    def test_windows_workflow_uses_curated_staging_and_headless_midi_gate(self):
        workflow = (ROOT / ".github" / "workflows" / "build-electron-windows-alpha.yml").read_text(encoding="utf-8")
        self.assertIn("stage-engine-resources.mjs", workflow)
        self.assertIn("smoke-electron-midi.py", workflow)
        self.assertIn("pnpm run validate:source", workflow)
        self.assertIn("pnpm run engine:check", workflow)
        self.assertIn("Verify the self-contained Windows runtime", workflow)
        self.assertIn(".packaging/.runtime/python/python.exe", workflow)
        self.assertNotIn(".packaging/.runtime/python/Scripts/python.exe", workflow)
        self.assertIn("$ready.basePrefix", workflow)
        self.assertIn("The staged bridge still references the GitHub runner Python.", workflow)
        runtime_setup = (ROOT / "electron-app" / "scripts" / "setup-python-runtime.mjs").read_text(encoding="utf-8")
        self.assertIn("cpSync(path.resolve(identity.basePrefix), runtimeRoot", runtime_setup)
        self.assertIn("non-relocatable pyvenv.cfg", runtime_setup)
        self.assertIn("python-\\d+\\.\\d+\\.\\d+-amd64\\.exe", runtime_setup)
        self.assertIn("The CPython bootstrap installer must not be packaged.", workflow)
        self.assertNotIn("Get-ChildItem -Path . -Filter *.py", workflow)
        self.assertNotIn("PySide6==", workflow)
        self.assertNotIn("diagnose_midi_startup.py", workflow)
        self.assertNotIn("Build the validated OpenKeyScan analyzer", workflow)

        source_roster = workflow.index("pnpm run validate:source")
        midi_gate = workflow.index("smoke-electron-midi.py")
        bungee_build = workflow.index("- name: Build static Bungee")
        ffmpeg_fetch = workflow.index("- name: Download and verify pinned FFmpeg")
        mert_fetch = workflow.index("- name: Fetch and verify the pinned offline MERT payload")
        engine_inventory = workflow.index("pnpm run engine:check")
        packaging = workflow.index("- name: Assemble Electron sidecar resources")
        self.assertLess(mert_fetch, source_roster)
        self.assertLess(source_roster, midi_gate)
        self.assertLess(midi_gate, bungee_build)
        self.assertLess(bungee_build, engine_inventory)
        self.assertLess(ffmpeg_fetch, engine_inventory)
        self.assertLess(mert_fetch, engine_inventory)
        self.assertLess(engine_inventory, packaging)


if __name__ == "__main__":
    unittest.main()
