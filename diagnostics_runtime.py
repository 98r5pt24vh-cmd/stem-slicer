"""Fault-tolerant runtime diagnostics for Stem Slicer.

This module is intentionally independent from the UI and audio pipeline.  It
uses only the Python standard library until :meth:`start_ui_watchdog` is
called, so it can be imported before PySide6, OpenKeyScan, Numba or ONNX.

Every public entry point is best-effort: diagnostics must never be allowed to
prevent the application from starting, processing audio, or shutting down.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import datetime, timezone
import faulthandler
import json
import os
from pathlib import Path
import platform
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid
from typing import Any, Iterable


_DIAGNOSTICS: "RuntimeDiagnostics | None" = None
_DIAGNOSTICS_LOCK = threading.RLock()
_MAX_VALUE_CHARS = 16_384
_MAX_PROCESS_OUTPUT_CHARS = 32_768


def _safe_component(value: str) -> str:
    cleaned = "".join(character for character in str(value) if character.isalnum() or character in " ._-")
    return cleaned.strip(" .") or "Stem Slicer"


def _platform_roots(app_name: str, version: str) -> dict[str, Path]:
    app = _safe_component(app_name)
    release = _safe_component(version)
    home = Path.home()
    if sys.platform == "darwin":
        cache = home / "Library" / "Caches" / app / release
        logs = home / "Library" / "Logs" / app / release
        state = home / "Library" / "Application Support" / app / "Diagnostics" / release
    elif os.name == "nt":
        local = Path(os.environ.get("LOCALAPPDATA") or (home / "AppData" / "Local"))
        cache = local / app / "Cache" / release
        logs = local / app / "Logs" / release
        state = local / app / "Diagnostics" / release
    else:
        cache_base = Path(os.environ.get("XDG_CACHE_HOME") or (home / ".cache"))
        state_base = Path(os.environ.get("XDG_STATE_HOME") or (home / ".local" / "state"))
        cache = cache_base / app / release
        logs = state_base / app / release / "logs"
        state = state_base / app / release / "diagnostics"
    return {"cache_root": cache, "log_root": logs, "state_root": state}


def _ensure_directory(path: Path, fallback_name: str) -> Path:
    try:
        path.mkdir(parents=True, exist_ok=True)
        return path
    except Exception:
        fallback = Path(tempfile.gettempdir()) / "stem-slicer-runtime" / fallback_name
        try:
            fallback.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        return fallback


def configure_runtime_environment(app_name: str = "Stem Slicer", version: str = "1.8.2B") -> dict:
    """Redirect mutable caches to user-writable locations outside the bundle.

    The returned mapping contains string paths and the environment variables
    that were applied.  Failures fall back to the operating-system temporary
    directory instead of escaping to the caller.
    """

    try:
        roots = _platform_roots(app_name, version)
        cache_root = _ensure_directory(roots["cache_root"], "cache")
        log_root = _ensure_directory(roots["log_root"], "logs")
        state_root = _ensure_directory(roots["state_root"], "state")
        directories = {
            "numba": cache_root / "numba",
            "matplotlib": cache_root / "matplotlib",
            "torch": cache_root / "torch",
            "huggingface": cache_root / "huggingface",
            "joblib": cache_root / "joblib-temp",
            "pycache": cache_root / "pycache",
            "openkeyscan": cache_root / "openkeyscan",
            "runtime_temp": cache_root / "temp",
        }
        for name, path in tuple(directories.items()):
            directories[name] = _ensure_directory(path, name)

        applied = {
            "STEM_SLICER_CACHE_DIR": str(cache_root),
            "STEM_SLICER_LOG_DIR": str(log_root),
            "STEM_SLICER_STATE_DIR": str(state_root),
            "STEM_SLICER_RUNTIME_TEMP": str(directories["runtime_temp"]),
            "OPENKEYSCAN_CACHE_DIR": str(directories["openkeyscan"]),
            "NUMBA_CACHE_DIR": str(directories["numba"]),
            "MPLCONFIGDIR": str(directories["matplotlib"]),
            "TORCH_HOME": str(directories["torch"]),
            "HF_HOME": str(directories["huggingface"]),
            "JOBLIB_TEMP_FOLDER": str(directories["joblib"]),
            "PYTHONPYCACHEPREFIX": str(directories["pycache"]),
            "XDG_CACHE_HOME": str(cache_root),
        }
        for key, value in applied.items():
            os.environ[key] = value
        try:
            sys.pycache_prefix = str(directories["pycache"])
        except Exception:
            pass
        return {
            "app_name": app_name,
            "version": version,
            "cache_root": str(cache_root),
            "log_root": str(log_root),
            "state_root": str(state_root),
            "runtime_temp": str(directories["runtime_temp"]),
            "environment": applied,
        }
    except Exception:
        fallback = Path(tempfile.gettempdir()) / "stem-slicer-runtime"
        cache_root = fallback / "cache"
        log_root = fallback / "logs"
        state_root = fallback / "state"
        directories = {
            "numba": cache_root / "numba",
            "matplotlib": cache_root / "matplotlib",
            "torch": cache_root / "torch",
            "huggingface": cache_root / "huggingface",
            "joblib": cache_root / "joblib-temp",
            "pycache": cache_root / "pycache",
            "openkeyscan": cache_root / "openkeyscan",
            "runtime_temp": cache_root / "temp",
        }
        for path in (cache_root, log_root, state_root, *directories.values()):
            try:
                path.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
        applied = {
            "STEM_SLICER_CACHE_DIR": str(cache_root),
            "STEM_SLICER_LOG_DIR": str(log_root),
            "STEM_SLICER_STATE_DIR": str(state_root),
            "STEM_SLICER_RUNTIME_TEMP": str(directories["runtime_temp"]),
            "OPENKEYSCAN_CACHE_DIR": str(directories["openkeyscan"]),
            "NUMBA_CACHE_DIR": str(directories["numba"]),
            "MPLCONFIGDIR": str(directories["matplotlib"]),
            "TORCH_HOME": str(directories["torch"]),
            "HF_HOME": str(directories["huggingface"]),
            "JOBLIB_TEMP_FOLDER": str(directories["joblib"]),
            "PYTHONPYCACHEPREFIX": str(directories["pycache"]),
            "XDG_CACHE_HOME": str(cache_root),
        }
        for key, value in applied.items():
            os.environ[key] = value
        try:
            sys.pycache_prefix = str(directories["pycache"])
        except Exception:
            pass
        return {
            "app_name": app_name,
            "version": version,
            "cache_root": str(cache_root),
            "log_root": str(log_root),
            "state_root": str(state_root),
            "runtime_temp": str(directories["runtime_temp"]),
            "environment": applied,
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _safe_json_value(value: Any, depth: int = 0) -> Any:
    if depth > 5:
        return "<maximum depth>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        if len(value) > _MAX_VALUE_CHARS:
            return value[-_MAX_VALUE_CHARS:] + " <truncated>"
        return value
    if isinstance(value, BaseException):
        return f"{type(value).__name__}: {value}"
    if isinstance(value, dict):
        return {
            str(key)[:256]: _safe_json_value(item, depth + 1)
            for key, item in list(value.items())[:256]
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_safe_json_value(item, depth + 1) for item in list(value)[:256]]
    try:
        return str(value)[:_MAX_VALUE_CHARS]
    except Exception:
        return f"<{type(value).__name__}>"


class _RotatingLineFile:
    def __init__(self, path: Path, max_bytes: int, backups: int):
        self.path = path
        self.max_bytes = max(64_000, int(max_bytes))
        self.backups = max(1, int(backups))
        self.handle = None
        self.size = 0

    def _open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a", encoding="utf-8", buffering=1)
        try:
            self.size = self.path.stat().st_size
        except OSError:
            self.size = 0

    def _rotate(self) -> None:
        if self.handle is not None:
            try:
                self.handle.close()
            except Exception:
                pass
            self.handle = None
        try:
            oldest = Path(f"{self.path}.{self.backups}")
            if oldest.exists():
                oldest.unlink()
            for index in range(self.backups - 1, 0, -1):
                source = Path(f"{self.path}.{index}")
                if source.exists():
                    os.replace(source, Path(f"{self.path}.{index + 1}"))
            if self.path.exists():
                os.replace(self.path, Path(f"{self.path}.1"))
        except Exception:
            pass
        self._open()

    def write(self, line: str) -> None:
        encoded_size = len(line.encode("utf-8", errors="replace"))
        if self.handle is None:
            self._open()
        if self.size and self.size + encoded_size > self.max_bytes:
            self._rotate()
        self.handle.write(line)
        self.handle.flush()
        self.size += encoded_size

    def close(self) -> None:
        if self.handle is not None:
            try:
                self.handle.flush()
                self.handle.close()
            except Exception:
                pass
            self.handle = None


class _AsyncLogWriter:
    _STOP = object()

    def __init__(self, root: Path, max_bytes: int, backups: int):
        self.root = root
        self.queue: queue.Queue = queue.Queue(maxsize=8192)
        self.dropped = 0
        self.thread = threading.Thread(target=self._run, name="StemSlicerDiagnosticsWriter", daemon=True)
        self.json_file = _RotatingLineFile(root / "runtime.jsonl", max_bytes, backups)
        self.text_file = _RotatingLineFile(root / "runtime.log", max_bytes, backups)
        self.thread.start()

    @staticmethod
    def _text_line(record: dict) -> str:
        core = {"timestamp", "level", "event", "session_id", "pid", "thread", "thread_id", "monotonic_ms"}
        details = {key: value for key, value in record.items() if key not in core}
        suffix = ""
        if details:
            try:
                suffix = " " + json.dumps(details, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            except Exception:
                suffix = " <unserializable fields>"
        return (
            f"{record.get('timestamp', '')} {record.get('level', 'INFO'):<8} "
            f"{record.get('event', 'event')} session={record.get('session_id', '')} "
            f"thread={record.get('thread', '')}{suffix}\n"
        )

    def _run(self) -> None:
        try:
            while True:
                item = self.queue.get()
                if item is self._STOP:
                    break
                if isinstance(item, tuple) and item and item[0] == "barrier":
                    item[1].set()
                    continue
                record = item
                try:
                    json_line = json.dumps(record, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
                    self.json_file.write(json_line)
                    self.text_file.write(self._text_line(record))
                except Exception:
                    continue
        except Exception:
            pass
        finally:
            self.json_file.close()
            self.text_file.close()

    def submit(self, record: dict) -> None:
        try:
            if self.dropped:
                record = dict(record)
                record["dropped_records_before_this"] = self.dropped
                self.dropped = 0
            self.queue.put_nowait(record)
        except Exception:
            self.dropped += 1

    def flush(self, timeout: float = 1.0) -> None:
        if not self.thread.is_alive():
            return
        barrier = threading.Event()
        try:
            self.queue.put(("barrier", barrier), timeout=max(0.01, timeout))
            barrier.wait(timeout=max(0.01, timeout))
        except Exception:
            pass

    def close(self) -> None:
        if not self.thread.is_alive():
            return
        try:
            self.queue.put(self._STOP, timeout=0.5)
            self.thread.join(timeout=2.0)
        except Exception:
            pass


class _OperationContext(AbstractContextManager):
    def __init__(self, diagnostics: "RuntimeDiagnostics", name: str, fields: dict):
        self.diagnostics = diagnostics
        self.name = name
        self.fields = fields
        self.operation_id = uuid.uuid4().hex
        self.started = 0.0

    def __enter__(self):
        self.started = time.perf_counter()
        self.diagnostics.event(
            "operation.started",
            operation=self.name,
            operation_id=self.operation_id,
            **self.fields,
        )
        return self

    def event(self, name: str, **fields) -> None:
        self.diagnostics.event(
            name,
            operation=self.name,
            operation_id=self.operation_id,
            **fields,
        )

    def __exit__(self, exc_type, exc, tb):
        duration = max(0.0, time.perf_counter() - self.started)
        if exc is None:
            self.diagnostics.event(
                "operation.finished",
                operation=self.name,
                operation_id=self.operation_id,
                status="success",
                duration_seconds=round(duration, 6),
                **self.fields,
            )
        else:
            self.diagnostics.exception(
                f"operation:{self.name}",
                exc,
                operation=self.name,
                operation_id=self.operation_id,
                duration_seconds=round(duration, 6),
                **self.fields,
            )
            self.diagnostics.event(
                "operation.finished",
                operation=self.name,
                operation_id=self.operation_id,
                status="error",
                duration_seconds=round(duration, 6),
                **self.fields,
            )
        return False


class RuntimeDiagnostics:
    """Persistent logs, exception hooks, platform reports and UI watchdog."""

    def __init__(
        self,
        app_name: str = "Stem Slicer",
        version: str = "1.8.2B",
        *,
        environment: dict | None = None,
        log_root: str | os.PathLike[str] | None = None,
        max_log_bytes: int = 5_000_000,
        backup_count: int = 4,
    ):
        self.app_name = app_name
        self.version = version
        self.environment = environment or configure_runtime_environment(app_name, version)
        self._custom_log_root = log_root is not None
        requested_log_root = Path(log_root) if log_root else Path(self.environment.get("log_root", ""))
        self.log_root = _ensure_directory(requested_log_root, "logs")
        requested_state = Path(self.environment.get("state_root", self.log_root / "state"))
        self.state_root = _ensure_directory(requested_state, "state")
        self.session_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self.started_monotonic = time.monotonic()
        self.started_timestamp = time.time()
        self.started_utc = _utc_now()
        self._closed = False
        self._writer = _AsyncLogWriter(self.log_root, max_log_bytes, backup_count)
        self._fault_file = None
        self._fault_path = self.log_root / f"stacks-{self.session_id}.log"
        self._ui_timer = None
        self._ui_watchdog_thread = None
        self._watchdog_stop = threading.Event()
        self._heartbeat_lock = threading.Lock()
        self._last_ui_heartbeat = time.monotonic()
        self._ui_timeout = 10.0
        self._freeze_started = None
        self._last_freeze_dump = 0.0
        self._old_sys_hook = sys.excepthook
        self._old_thread_hook = getattr(threading, "excepthook", None)
        self._old_unraisable_hook = getattr(sys, "unraisablehook", None)
        self._sys_hook_ref = None
        self._thread_hook_ref = None
        self._unraisable_hook_ref = None
        self._platform_report_thread = None

        self._enable_fault_handler()
        self._install_exception_hooks()
        self.event(
            "session.started",
            executable=sys.executable,
            frozen=bool(getattr(sys, "frozen", False)),
            python=platform.python_version(),
            platform=platform.platform(),
            architecture=platform.machine(),
            log_root=str(self.log_root),
        )
        # Native crash/hang reports are collected independently of any
        # application-maintained "active session" marker.  Such markers are
        # deliberately not used: a diagnostic facility must not infer a crash
        # merely because a marker could not be cleaned up.
        if not self._custom_log_root:
            self._platform_report_thread = threading.Thread(
                target=self.collect_platform_reports,
                kwargs={"since": self.started_timestamp - 7 * 86_400},
                name="StemSlicerNativeReportCollector",
                daemon=True,
            )
            self._platform_report_thread.start()

    def _base_record(self, name: str, level: str, fields: dict) -> dict:
        thread = threading.current_thread()
        record = {
            "timestamp": _utc_now(),
            "monotonic_ms": round((time.monotonic() - self.started_monotonic) * 1000, 3),
            "level": str(level).upper(),
            "event": str(name),
            "session_id": self.session_id,
            "app": self.app_name,
            "version": self.version,
            "pid": os.getpid(),
            "thread": thread.name,
            "thread_id": threading.get_ident(),
        }
        for key, value in fields.items():
            record[str(key)] = _safe_json_value(value)
        return record

    def event(self, name: str, **fields) -> None:
        """Record one structured event; all failures are deliberately ignored."""
        try:
            if self._closed:
                return
            level = str(fields.pop("level", "INFO"))
            self._writer.submit(self._base_record(name, level, fields))
        except Exception:
            pass

    def exception(self, context: str, exc: BaseException, **fields) -> None:
        try:
            stack = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            self.event(
                "exception",
                level="ERROR",
                context=context,
                exception_type=type(exc).__name__,
                exception_message=str(exc),
                traceback=stack,
                **fields,
            )
            self._dump_python_stacks(f"exception:{context}")
            self._writer.flush(0.75)
        except Exception:
            pass

    def operation(self, name: str, **fields) -> _OperationContext:
        return _OperationContext(self, name, fields)

    def record_subprocess(
        self,
        command: Iterable[Any] | str,
        duration: float,
        returncode: int | None,
        stdout: Any = None,
        stderr: Any = None,
        **fields,
    ) -> None:
        try:
            command_value = command if isinstance(command, str) else list(command)
            # stdout may be raw PCM produced through an FFmpeg pipe. Never
            # serialize binary audio into diagnostics: JSON escaping expands
            # it dramatically and can starve the Qt event loop. Keep only its
            # byte count; stderr remains available for actionable errors.
            stdout_bytes = len(stdout) if isinstance(stdout, (bytes, bytearray, memoryview)) else None
            stdout_text = None if stdout_bytes is not None else _safe_json_value(stdout)
            if isinstance(stderr, (bytes, bytearray, memoryview)):
                stderr_text = bytes(stderr).decode("utf-8", errors="replace")
            else:
                stderr_text = _safe_json_value(stderr)
            if isinstance(stdout_text, str):
                stdout_text = stdout_text[-_MAX_PROCESS_OUTPUT_CHARS:]
            if isinstance(stderr_text, str):
                stderr_text = stderr_text[-_MAX_PROCESS_OUTPUT_CHARS:]
            self.event(
                "subprocess.finished",
                level="INFO" if returncode in (0, None) else "ERROR",
                command=command_value,
                duration_seconds=round(max(0.0, float(duration)), 6),
                returncode=returncode,
                stdout_tail=stdout_text,
                stdout_bytes=stdout_bytes,
                stderr_tail=stderr_text,
                **fields,
            )
        except Exception:
            pass

    def _enable_fault_handler(self) -> None:
        try:
            self._fault_file = self._fault_path.open("a", encoding="utf-8", buffering=1)
            faulthandler.enable(file=self._fault_file, all_threads=True)
        except Exception:
            self._fault_file = None

    def _dump_python_stacks(self, reason: str) -> None:
        try:
            if self._fault_file is None:
                return
            self._fault_file.write(f"\n===== {_utc_now()} {reason} =====\n")
            self._fault_file.flush()
            faulthandler.dump_traceback(file=self._fault_file, all_threads=True)
            self._fault_file.flush()
        except Exception:
            pass

    def _install_exception_hooks(self) -> None:
        def sys_hook(exc_type, exc, tb):
            try:
                self.exception("sys.excepthook", exc)
            except Exception:
                pass
            try:
                if self._old_sys_hook:
                    self._old_sys_hook(exc_type, exc, tb)
            except Exception:
                pass

        def thread_hook(args):
            try:
                self.exception(
                    "threading.excepthook",
                    args.exc_value,
                    crashed_thread=getattr(args.thread, "name", ""),
                )
            except Exception:
                pass
            try:
                if self._old_thread_hook:
                    self._old_thread_hook(args)
            except Exception:
                pass

        def unraisable_hook(args):
            try:
                exc = args.exc_value or RuntimeError(str(args.err_msg or "Unraisable exception"))
                self.exception("sys.unraisablehook", exc, object=repr(args.object))
            except Exception:
                pass
            try:
                if self._old_unraisable_hook:
                    self._old_unraisable_hook(args)
            except Exception:
                pass

        self._sys_hook_ref = sys_hook
        self._thread_hook_ref = thread_hook
        self._unraisable_hook_ref = unraisable_hook
        try:
            sys.excepthook = sys_hook
        except Exception:
            pass
        try:
            threading.excepthook = thread_hook
        except Exception:
            pass
        try:
            sys.unraisablehook = unraisable_hook
        except Exception:
            pass

    def start_ui_watchdog(self, qt_parent=None, timeout_seconds: float = 10) -> bool:
        """Watch the Qt event loop and dump all Python stacks on a UI stall."""
        try:
            if self._closed:
                return False
            from PySide6.QtCore import QCoreApplication, QTimer

            application = QCoreApplication.instance()
            if application is None:
                self.event("ui_watchdog.unavailable", level="WARNING", reason="No QCoreApplication instance")
                return False
            self._ui_timeout = max(2.0, float(timeout_seconds))
            with self._heartbeat_lock:
                self._last_ui_heartbeat = time.monotonic()
                self._freeze_started = None
            parent = qt_parent or application
            if self._ui_timer is None:
                self._ui_timer = QTimer(parent)
                self._ui_timer.timeout.connect(self._ui_heartbeat)
            interval_ms = max(250, min(1000, int(self._ui_timeout * 1000 / 4)))
            self._ui_timer.start(interval_ms)
            self._arm_fault_timeout()
            if self._ui_watchdog_thread is None or not self._ui_watchdog_thread.is_alive():
                self._watchdog_stop.clear()
                self._ui_watchdog_thread = threading.Thread(
                    target=self._watchdog_loop,
                    name="StemSlicerUIWatchdog",
                    daemon=True,
                )
                self._ui_watchdog_thread.start()
            try:
                application.aboutToQuit.connect(self.shutdown)
            except Exception:
                pass
            self.event("ui_watchdog.started", timeout_seconds=self._ui_timeout, heartbeat_interval_ms=interval_ms)
            return True
        except Exception as exc:
            self.event("ui_watchdog.unavailable", level="WARNING", reason=str(exc))
            return False

    def _arm_fault_timeout(self) -> None:
        try:
            if self._fault_file is None:
                return
            faulthandler.cancel_dump_traceback_later()
            faulthandler.dump_traceback_later(
                self._ui_timeout,
                repeat=False,
                file=self._fault_file,
                exit=False,
            )
        except Exception:
            pass

    def _ui_heartbeat(self) -> None:
        try:
            now = time.monotonic()
            recovered = None
            with self._heartbeat_lock:
                self._last_ui_heartbeat = now
                if self._freeze_started is not None:
                    recovered = max(0.0, now - self._freeze_started)
                    self._freeze_started = None
                    self._last_freeze_dump = 0.0
            if recovered is not None:
                self.event("ui.freeze.recovered", level="WARNING", duration_seconds=round(recovered, 3))
            self._arm_fault_timeout()
        except Exception:
            pass

    def _watchdog_loop(self) -> None:
        while not self._watchdog_stop.wait(0.5):
            try:
                now = time.monotonic()
                should_dump = False
                first_detection = False
                with self._heartbeat_lock:
                    elapsed = now - self._last_ui_heartbeat
                    if elapsed >= self._ui_timeout:
                        if self._freeze_started is None:
                            self._freeze_started = self._last_ui_heartbeat
                            first_detection = True
                            should_dump = True
                        elif now - self._last_freeze_dump >= max(30.0, self._ui_timeout * 3):
                            should_dump = True
                        if should_dump:
                            self._last_freeze_dump = now
                if should_dump:
                    event_name = "ui.freeze.detected" if first_detection else "ui.freeze.still_blocked"
                    self.event(event_name, level="ERROR", unresponsive_seconds=round(elapsed, 3))
                    self._dump_python_stacks(event_name)
                    self._writer.flush(0.5)
            except Exception:
                continue

    def _report_tokens(self) -> tuple[str, ...]:
        values = {
            self.app_name,
            self.app_name.replace(" ", ""),
            "StemSlicer16B",
            "StemSlicer17B",
            "StemSlicer18B",
            "com.antiworld.stemslicer",
            Path(sys.executable).stem,
        }
        return tuple("".join(char.lower() for char in value if char.isalnum()) for value in values if value)

    def _matches_report(self, path: Path, tokens: tuple[str, ...]) -> bool:
        normalized = "".join(char.lower() for char in str(path) if char.isalnum())
        if any(token and token in normalized for token in tokens):
            return True
        if path.suffix.lower() == ".dmp":
            return False
        try:
            with path.open("rb") as handle:
                content = handle.read(262_144).decode("utf-8", errors="ignore")
            normalized_content = "".join(char.lower() for char in content if char.isalnum())
            return any(token and token in normalized_content for token in tokens)
        except Exception:
            return False

    def _platform_report_candidates(self) -> Iterable[Path]:
        if sys.platform == "darwin":
            roots = [Path.home() / "Library" / "Logs" / "DiagnosticReports"]
            extensions = {".ips", ".crash", ".hang", ".spin"}
        elif os.name == "nt":
            local = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
            roots = [
                local / "CrashDumps",
                local / "Microsoft" / "Windows" / "WER" / "ReportArchive",
                local / "Microsoft" / "Windows" / "WER" / "ReportQueue",
            ]
            extensions = {".dmp", ".wer", ".xml", ".txt", ".log"}
        else:
            return []
        candidates = []
        for root in roots:
            try:
                if not root.is_dir():
                    continue
                visited = 0
                for directory, _subdirs, files in os.walk(root):
                    for filename in files:
                        path = Path(directory) / filename
                        if path.suffix.lower() in extensions:
                            candidates.append(path)
                        visited += 1
                        if visited >= 2000:
                            break
                    if visited >= 2000:
                        break
            except Exception:
                continue
        return candidates

    def _collect_windows_event_log(self, destination: Path) -> str | None:
        if os.name != "nt":
            return None
        try:
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            completed = subprocess.run(
                ["wevtutil", "qe", "Application", "/c:100", "/rd:true", "/f:text"],
                check=False,
                capture_output=True,
                text=True,
                timeout=8,
                creationflags=creationflags,
            )
            output = completed.stdout or ""
            blocks = output.split("\n\n")
            tokens = self._report_tokens()
            matches = []
            for block in blocks:
                normalized = "".join(char.lower() for char in block if char.isalnum())
                if any(token and token in normalized for token in tokens):
                    matches.append(block.strip())
            if not matches:
                return None
            path = destination / "windows-application-events.txt"
            path.write_text("\n\n".join(matches)[-_MAX_VALUE_CHARS * 8 :], encoding="utf-8")
            return str(path)
        except Exception:
            return None

    def collect_platform_reports(
        self,
        since: float | datetime | str | None = None,
        *,
        max_files: int = 8,
        max_total_bytes: int = 100_000_000,
    ) -> list[str]:
        """Copy matching macOS DiagnosticReports or Windows WER artefacts."""
        copied = []
        try:
            if isinstance(since, datetime):
                since_timestamp = since.timestamp()
            elif isinstance(since, str):
                since_timestamp = datetime.fromisoformat(since.replace("Z", "+00:00")).timestamp()
            elif since is None:
                since_timestamp = time.time() - 7 * 86_400
            else:
                since_timestamp = float(since)
            since_timestamp -= 120.0
            candidates = []
            tokens = self._report_tokens()
            recent_candidates = list(self._platform_report_candidates())
            recent_candidates.sort(
                key=lambda path: path.stat().st_mtime if path.exists() else 0,
                reverse=True,
            )
            # Bound startup work on machines with years of crash archives.
            for path in recent_candidates[:250]:
                try:
                    if path.stat().st_mtime < since_timestamp or not self._matches_report(path, tokens):
                        continue
                    candidates.append(path)
                except Exception:
                    continue
            candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
            destination = _ensure_directory(self.log_root / "platform-reports" / self.session_id, "platform-reports")
            total = 0
            manifest = []
            for source in candidates[: max(1, int(max_files))]:
                try:
                    size = source.stat().st_size
                    item = {"source": str(source), "bytes": size, "copied": False}
                    if size <= max_total_bytes - total:
                        target = destination / source.name
                        if target.exists():
                            target = destination / f"{source.stem}-{uuid.uuid4().hex[:6]}{source.suffix}"
                        shutil.copy2(source, target)
                        total += size
                        copied.append(str(target))
                        item.update({"copied": True, "destination": str(target)})
                    else:
                        item["reason"] = "diagnostic copy size limit"
                    manifest.append(item)
                except Exception as exc:
                    manifest.append({"source": str(source), "copied": False, "reason": str(exc)})
            event_log = self._collect_windows_event_log(destination)
            if event_log:
                copied.append(event_log)
                manifest.append({"source": "Windows Application event log", "copied": True, "destination": event_log})
            if manifest:
                manifest_path = destination / "manifest.json"
                manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
                copied.append(str(manifest_path))
            self.event(
                "platform_reports.collected",
                platform=sys.platform,
                matched=len(candidates),
                copied=len(copied),
                total_bytes=total,
                destination=str(destination),
            )
        except Exception as exc:
            self.event("platform_reports.failed", level="WARNING", reason=str(exc))
        return copied

    def shutdown(self) -> None:
        """Flush diagnostics and release watchdog resources, idempotently."""
        try:
            if self._closed:
                return
            self.event("session.shutdown", uptime_seconds=round(time.monotonic() - self.started_monotonic, 3))
            self._watchdog_stop.set()
            try:
                if self._ui_timer is not None:
                    self._ui_timer.stop()
            except Exception:
                pass
            try:
                faulthandler.cancel_dump_traceback_later()
            except Exception:
                pass
            if self._ui_watchdog_thread is not None and self._ui_watchdog_thread is not threading.current_thread():
                try:
                    self._ui_watchdog_thread.join(timeout=1.0)
                except Exception:
                    pass
            if self._platform_report_thread is not None and self._platform_report_thread is not threading.current_thread():
                try:
                    self._platform_report_thread.join(timeout=2.0)
                except Exception:
                    pass
            # Pick up reports generated during this exact run, including
            # reports written shortly before a graceful shutdown.
            if not self._custom_log_root:
                self.collect_platform_reports(since=self.started_timestamp)
            self._writer.flush(1.0)
            self._closed = True
            self._writer.close()
            try:
                if sys.excepthook is self._sys_hook_ref:
                    sys.excepthook = self._old_sys_hook
                if getattr(threading, "excepthook", None) is self._thread_hook_ref:
                    threading.excepthook = self._old_thread_hook
                if getattr(sys, "unraisablehook", None) is self._unraisable_hook_ref:
                    sys.unraisablehook = self._old_unraisable_hook
            except Exception:
                pass
            try:
                if self._fault_file is not None:
                    try:
                        faulthandler.disable()
                    except Exception:
                        pass
                    self._fault_file.flush()
                    self._fault_file.close()
                    self._fault_file = None
            except Exception:
                pass
        except Exception:
            pass


class _NoopRuntimeDiagnostics(RuntimeDiagnostics):
    """Null object returned before diagnostics are explicitly initialized.

    Engine modules can safely call ``get_diagnostics().event(...)`` when they
    are imported directly by tests or command-line helpers.  The null object
    performs no filesystem, environment, Qt, hook, or thread work.
    """

    def __init__(self):
        self.log_root = Path(tempfile.gettempdir()) / "stem-slicer-runtime" / "logs"

    def event(self, name: str, **fields) -> None:
        return None

    def exception(self, context: str, exc: BaseException, **fields) -> None:
        return None

    def operation(self, name: str, **fields) -> _OperationContext:
        return _OperationContext(self, name, fields)

    def record_subprocess(
        self,
        command: Iterable[Any] | str,
        duration: float,
        returncode: int | None,
        stdout: Any = None,
        stderr: Any = None,
        **fields,
    ) -> None:
        return None

    def start_ui_watchdog(self, qt_parent=None, timeout_seconds: float = 10) -> bool:
        return False

    def collect_platform_reports(
        self,
        since: float | datetime | str | None = None,
        *,
        max_files: int = 8,
        max_total_bytes: int = 100_000_000,
    ) -> list[str]:
        return []

    def shutdown(self) -> None:
        return None


_NOOP_DIAGNOSTICS: RuntimeDiagnostics = _NoopRuntimeDiagnostics()


def initialize_diagnostics(
    app_name: str = "Stem Slicer",
    version: str = "1.8.2B",
    *,
    environment: dict | None = None,
    log_root: str | os.PathLike[str] | None = None,
    max_log_bytes: int = 5_000_000,
    backup_count: int = 4,
) -> RuntimeDiagnostics:
    """Create the process-wide diagnostics singleton, or return the existing one."""
    global _DIAGNOSTICS
    with _DIAGNOSTICS_LOCK:
        if _DIAGNOSTICS is not None:
            return _DIAGNOSTICS
        try:
            _DIAGNOSTICS = RuntimeDiagnostics(
                app_name,
                version,
                environment=environment,
                log_root=log_root,
                max_log_bytes=max_log_bytes,
                backup_count=backup_count,
            )
        except Exception:
            # RuntimeDiagnostics is designed not to raise, but retain a final
            # temporary-directory fallback for import/startup safety.
            try:
                fallback_environment = configure_runtime_environment(app_name, version)
                fallback_root = Path(tempfile.gettempdir()) / "stem-slicer-runtime" / "logs"
                _DIAGNOSTICS = RuntimeDiagnostics(
                    app_name,
                    version,
                    environment=fallback_environment,
                    log_root=fallback_root,
                    max_log_bytes=max_log_bytes,
                    backup_count=backup_count,
                )
            except Exception:
                _DIAGNOSTICS = _NOOP_DIAGNOSTICS
        return _DIAGNOSTICS


def get_diagnostics() -> RuntimeDiagnostics:
    """Return the active diagnostics object, or a side-effect-free null one."""
    return _DIAGNOSTICS if _DIAGNOSTICS is not None else _NOOP_DIAGNOSTICS


__all__ = [
    "RuntimeDiagnostics",
    "configure_runtime_environment",
    "initialize_diagnostics",
    "get_diagnostics",
]
