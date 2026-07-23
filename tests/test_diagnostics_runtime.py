import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import diagnostics_runtime


class RuntimeDiagnosticsTests(unittest.TestCase):
    def _environment(self, root):
        root = Path(root)
        return {
            "app_name": "Stem Slicer",
            "version": "1.8B",
            "cache_root": str(root / "cache"),
            "log_root": str(root / "logs"),
            "state_root": str(root / "state"),
            "runtime_temp": str(root / "temp"),
            "environment": {},
        }

    def _diagnostics(self, root):
        environment = self._environment(root)
        # Avoid changing the process-wide faulthandler destination while the
        # test suite creates several short-lived diagnostics instances.
        with patch.object(diagnostics_runtime.RuntimeDiagnostics, "_enable_fault_handler"):
            instance = diagnostics_runtime.RuntimeDiagnostics(
                environment=environment,
                log_root=environment["log_root"],
            )
        self.addCleanup(instance.shutdown)
        return instance

    @staticmethod
    def _records(log_root):
        path = Path(log_root) / "runtime.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]

    def test_runtime_caches_and_engine_variables_are_outside_the_bundle(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = root / "Stem Slicer 1.8B.app" / "Contents" / "Resources"
            user_data = root / "User Data"
            roots = {
                "cache_root": user_data / "Caches" / "Stem Slicer" / "1.8B",
                "log_root": user_data / "Logs" / "Stem Slicer" / "1.8B",
                "state_root": user_data / "State" / "Stem Slicer" / "1.8B",
            }
            previous_pycache_prefix = getattr(diagnostics_runtime.sys, "pycache_prefix", None)
            try:
                with (
                    patch.object(diagnostics_runtime, "_platform_roots", return_value=roots),
                    patch.dict(diagnostics_runtime.os.environ, {}, clear=False),
                ):
                    result = diagnostics_runtime.configure_runtime_environment()
                    applied = result["environment"]
                    for name in (
                        "NUMBA_CACHE_DIR",
                        "OPENKEYSCAN_CACHE_DIR",
                        "PYTHONPYCACHEPREFIX",
                        "TORCH_HOME",
                        "MPLCONFIGDIR",
                        "JOBLIB_TEMP_FOLDER",
                    ):
                        self.assertEqual(diagnostics_runtime.os.environ[name], applied[name])
                        path = Path(applied[name]).resolve()
                        self.assertTrue(path.is_dir(), name)
                        self.assertTrue(path.is_relative_to(user_data.resolve()), name)
                        self.assertFalse(path.is_relative_to(bundle.resolve()), name)
                    self.assertEqual(
                        diagnostics_runtime.sys.pycache_prefix,
                        applied["PYTHONPYCACHEPREFIX"],
                    )
            finally:
                diagnostics_runtime.sys.pycache_prefix = previous_pycache_prefix

    def test_jsonl_and_text_logs_persist_events_and_operation_duration(self):
        with tempfile.TemporaryDirectory() as temporary:
            diagnostics = self._diagnostics(temporary)
            diagnostics.event("test.ready", file="Timer 55 BPM.mp3")
            with diagnostics.operation("quick_extract", file="Timer 55 BPM.mp3"):
                diagnostics.event("worker.stage", stage="decode")
            diagnostics.shutdown()

            records = self._records(diagnostics.log_root)
            events = [record["event"] for record in records]
            self.assertIn("session.started", events)
            self.assertIn("test.ready", events)
            self.assertIn("operation.started", events)
            self.assertIn("worker.stage", events)
            self.assertIn("operation.finished", events)
            finished = next(record for record in records if record["event"] == "operation.finished")
            self.assertEqual(finished["operation"], "quick_extract")
            self.assertEqual(finished["status"], "success")
            self.assertGreaterEqual(finished["duration_seconds"], 0)

            text = (diagnostics.log_root / "runtime.log").read_text(encoding="utf-8")
            self.assertIn("test.ready", text)
            self.assertIn("operation.finished", text)
            self.assertIn("Timer 55 BPM.mp3", text)

    def test_failed_subprocess_persists_return_code_and_stderr(self):
        with tempfile.TemporaryDirectory() as temporary:
            diagnostics = self._diagnostics(temporary)
            diagnostics.record_subprocess(
                ["ffmpeg", "-i", "Timer.mp3"],
                duration=0.375,
                returncode=69,
                stdout="partial output",
                stderr="Invalid data found when processing input",
                file="Timer.mp3",
            )
            diagnostics.shutdown()

            record = next(
                item for item in self._records(diagnostics.log_root)
                if item["event"] == "subprocess.finished"
            )
            self.assertEqual(record["level"], "ERROR")
            self.assertEqual(record["returncode"], 69)
            self.assertEqual(record["command"], ["ffmpeg", "-i", "Timer.mp3"])
            self.assertIn("Invalid data found", record["stderr_tail"])
            self.assertEqual(record["file"], "Timer.mp3")

    def test_binary_subprocess_stdout_is_never_written_to_logs(self):
        with tempfile.TemporaryDirectory() as temporary:
            diagnostics = self._diagnostics(temporary)
            pcm = b"\x00\xffRAW_PCM_MUST_NOT_APPEAR" * 4096
            diagnostics.record_subprocess(
                ["ffmpeg", "-f", "f32le", "-"],
                duration=0.125,
                returncode=0,
                stdout=pcm,
                stderr=b"",
            )
            diagnostics.shutdown()

            record = next(
                item for item in self._records(diagnostics.log_root)
                if item["event"] == "subprocess.finished"
            )
            self.assertIsNone(record["stdout_tail"])
            self.assertEqual(record["stdout_bytes"], len(pcm))
            log_text = (diagnostics.log_root / "runtime.log").read_text(encoding="utf-8")
            self.assertNotIn("RAW_PCM_MUST_NOT_APPEAR", log_text)

    def test_watchdog_can_emit_a_freeze_event_and_stack_report_quickly(self):
        with tempfile.TemporaryDirectory() as temporary:
            diagnostics = self._diagnostics(temporary)
            stack_path = diagnostics.log_root / "watchdog-stacks.log"
            diagnostics._fault_path = stack_path
            diagnostics._fault_file = stack_path.open("a", encoding="utf-8", buffering=1)
            diagnostics._ui_timeout = 0.05
            with diagnostics._heartbeat_lock:
                diagnostics._last_ui_heartbeat = time.monotonic() - 1.0
            diagnostics._watchdog_stop.clear()
            diagnostics._ui_watchdog_thread = threading.Thread(
                target=diagnostics._watchdog_loop,
                name="TestUIWatchdog",
                daemon=True,
            )
            diagnostics._ui_watchdog_thread.start()

            deadline = time.monotonic() + 2.0
            freeze = None
            while time.monotonic() < deadline:
                diagnostics._writer.flush(0.2)
                freeze = next(
                    (
                        item for item in self._records(diagnostics.log_root)
                        if item["event"] == "ui.freeze.detected"
                    ),
                    None,
                )
                if freeze is not None:
                    break
                time.sleep(0.05)

            self.assertIsNotNone(freeze, "watchdog did not report the simulated UI stall")
            self.assertEqual(freeze["level"], "ERROR")
            self.assertGreaterEqual(freeze["unresponsive_seconds"], 0.05)
            diagnostics.shutdown()
            self.assertIn("ui.freeze.detected", stack_path.read_text(encoding="utf-8"))

    def test_collects_macos_diagnostic_report_from_an_injected_home(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            report_root = home / "Library" / "Logs" / "DiagnosticReports"
            report_root.mkdir(parents=True)
            report = report_root / "StemSlicer18B-test.ips"
            report.write_text("Stem Slicer 1.8B simulated macOS report", encoding="utf-8")
            now = time.time()
            os.utime(report, (now, now))
            diagnostics = self._diagnostics(root / "runtime")

            with (
                patch.object(diagnostics_runtime.sys, "platform", "darwin"),
                patch.object(diagnostics_runtime.Path, "home", return_value=home),
                patch.object(diagnostics, "_collect_windows_event_log", return_value=None),
            ):
                copied = diagnostics.collect_platform_reports(since=now - 5)
            diagnostics.shutdown()

            copied_paths = [Path(path) for path in copied]
            copied_report = next(path for path in copied_paths if path.suffix == ".ips")
            self.assertEqual(copied_report.read_text(encoding="utf-8"), report.read_text(encoding="utf-8"))
            manifest = next(path for path in copied_paths if path.name == "manifest.json")
            manifest_items = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertTrue(any(item.get("source") == str(report) and item.get("copied") for item in manifest_items))

    def test_collects_windows_wer_and_application_event_log_from_injected_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = root / "ReportArchive" / "StemSlicer18B.wer"
            report.parent.mkdir(parents=True)
            report.write_text("AppName=Stem Slicer 1.8B", encoding="utf-8")
            now = time.time()
            os.utime(report, (now, now))
            diagnostics = self._diagnostics(root / "runtime")

            def fake_event_log(destination):
                event_log = destination / "windows-application-events.txt"
                event_log.write_text("Stem Slicer 1.8B application error", encoding="utf-8")
                return str(event_log)

            with (
                patch.object(diagnostics_runtime.sys, "platform", "win32"),
                patch.object(diagnostics, "_platform_report_candidates", return_value=[report]),
                patch.object(diagnostics, "_collect_windows_event_log", side_effect=fake_event_log),
            ):
                copied = diagnostics.collect_platform_reports(since=now - 5)
            diagnostics.shutdown()

            copied_paths = [Path(path) for path in copied]
            self.assertTrue(any(path.suffix == ".wer" for path in copied_paths))
            self.assertTrue(any(path.name == "windows-application-events.txt" for path in copied_paths))
            self.assertTrue(any(path.name == "manifest.json" for path in copied_paths))


if __name__ == "__main__":
    unittest.main()
