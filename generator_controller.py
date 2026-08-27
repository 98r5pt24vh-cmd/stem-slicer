"""Controller wiring the Generate-only UI to the experimental engines."""

from __future__ import annotations

from collections import deque
import os
from pathlib import Path
import sys
from typing import Mapping

from PySide6.QtCore import QObject, QSettings, QThread, QTimer, Signal, Slot

from generation_policy import (
    GenerationRequest,
    LayerCandidate,
    SelectionError,
    plan_with_alternate_key,
    plan_with_manual_pitch,
    plan_with_normalization,
    plan_with_source_key_rank,
    selected_source_signature,
    select_generation,
)
from generation_renderer import (
    RenderRequest,
    render_generation,
    rerender_selected_layer,
)
from generation_history_ui import GenerateHistoryManagerDialog, GenerateHistoryStore
from key_confidence import DEFAULT_KEY_MARGIN_THRESHOLD, KeyConfidenceIndex
from layer_library import (
    CancelToken,
    LayerLibrary,
    ScanProgress,
    ScanResult,
    most_recent_cached_library_root,
)
from mert_client import MertLayerClassifier
from storage import format_decimal_size, open_in_file_manager


RUNTIME_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
PROJECT_ROOT = Path(__file__).resolve().parent.parent
# Training manifests are deliberately not runtime inputs.  A developer may
# opt into a temporary truth overlay for an isolated experiment, but a normal
# user-library scan must always exercise the classifier and persist its own
# results instead of importing labels from our training corpus.
DEVELOPMENT_TRUTH_ENV = "STEM_SLICER_GENERATE_DEV_TRUTH_CSV"
KEY_CONFIDENCE_ROOT = (
    PROJECT_ROOT / "research" / "all_layers_2_key_inventory_2026-08-01"
)
DEFAULT_KEY_CONFIDENCE_INVENTORY = (
    KEY_CONFIDENCE_ROOT / "original_loop_inventory.json"
)
DEFAULT_KEY_CONFIDENCE_RESULTS = (
    KEY_CONFIDENCE_ROOT / "key_confidence_results.json"
)


def default_cache_path() -> Path:
    configured = os.environ.get("STEM_SLICER_CACHE_DIR", "").strip()
    if configured:
        return Path(configured).expanduser() / "generate" / "library.sqlite3"
    return Path.home() / "Library" / "Caches" / "Stem Slicer" / "generate" / "library.sqlite3"


def development_truth_cache_path() -> Path:
    """Return an isolated cache used only by the explicit truth overlay."""

    configured = os.environ.get("STEM_SLICER_CACHE_DIR", "").strip()
    if configured:
        root = Path(configured).expanduser() / "generate"
    else:
        root = Path.home() / "Library" / "Caches" / "Stem Slicer" / "generate"
    return root / "library.development-truth.sqlite3"


def default_output_root() -> Path:
    return Path.home() / "Documents" / "Stem Slicer" / "Generated Loops"


def _selection_source_key_text(selection) -> str:
    """Format the currently active Top 1/Top 2 source key for one card."""

    if not selection.candidate.key_sensitive:
        values = (
            selection.candidate.scanned_key or selection.candidate.source_key,
            selection.candidate.scanned_mode or selection.candidate.source_mode,
        )
    else:
        signature = selected_source_signature(selection)
        values = (signature.tonic, signature.mode)
    return " ".join(str(value) for value in values if value)


def _locked_identities_by_slot(
    raw_value: object,
    slot_count: int,
) -> tuple[str | None, ...]:
    """Normalize the UI/controller lock payload to recipe-aligned identities."""

    locked: list[str | None] = [None] * slot_count
    if raw_value is None:
        return tuple(locked)
    if isinstance(raw_value, Mapping):
        items = raw_value.items()
    elif isinstance(raw_value, (list, tuple)):
        if len(raw_value) == slot_count and all(
            item is None or isinstance(item, str) for item in raw_value
        ):
            return tuple(
                str(item).strip() if item is not None else None
                for item in raw_value
            )
        items = raw_value
    else:
        raise ValueError("Locked slots must be a mapping or a sequence")

    for item in items:
        if isinstance(item, Mapping):
            slot_index = item.get("slot_index")
            identity = item.get("identity")
        else:
            try:
                slot_index, identity = item
            except (TypeError, ValueError) as error:
                raise ValueError(
                    "Each locked slot must contain a slot index and identity"
                ) from error
        index = int(slot_index)
        if not 0 <= index < slot_count:
            raise ValueError(f"Locked slot index is outside the recipe: {index}")
        normalized = str(identity or "").strip()
        if not normalized:
            raise ValueError(f"Locked slot {index + 1} has no layer identity")
        if locked[index] not in (None, normalized):
            raise ValueError(f"Locked slot {index + 1} has conflicting identities")
        locked[index] = normalized
    return tuple(locked)


class ScanWorker(QObject):
    progress = Signal(int, str)
    completed = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(
        self,
        library_root: Path,
        cache_path: Path,
        *,
        classifier: MertLayerClassifier | None,
        development_truth_path: Path | None,
        key_confidence_inventory_path: Path | None,
        key_confidence_results_path: Path | None,
    ) -> None:
        super().__init__()
        self.library_root = library_root
        self.cache_path = cache_path
        self.classifier = classifier
        self.development_truth_path = development_truth_path
        self.key_confidence_inventory_path = key_confidence_inventory_path
        self.key_confidence_results_path = key_confidence_results_path
        self.cancel_token = CancelToken()

    def cancel(self) -> None:
        self.cancel_token.cancel()

    @Slot()
    def run(self) -> None:
        try:
            key_confidence_index = KeyConfidenceIndex()
            if (
                self.key_confidence_inventory_path is not None
                and self.key_confidence_results_path is not None
            ):
                key_confidence_index = KeyConfidenceIndex.from_files(
                    library_root=self.library_root,
                    inventory_path=self.key_confidence_inventory_path,
                    results_path=self.key_confidence_results_path,
                    threshold=DEFAULT_KEY_MARGIN_THRESHOLD,
                )
            library = LayerLibrary(
                self.library_root,
                self.cache_path,
                classifier=self.classifier,
                truth_csv_path=self.development_truth_path,
                key_confidence_index=key_confidence_index,
            )

            def report(item: ScanProgress) -> None:
                percent = (
                    100
                    if item.total <= 0
                    else round(100 * item.completed / item.total)
                )
                phase = {
                    "inventory": "Inventorying library",
                    "metadata": "Reading metadata",
                    "classify": "Classifying unknown layer",
                    "complete": "Library ready",
                    "cancelled": "Scan cancelled",
                }.get(item.phase, item.phase.title())
                detail = (
                    f"{phase} · {item.relative_path}"
                    if item.relative_path
                    else phase
                )
                self.progress.emit(percent, detail)

            self.completed.emit(
                library.scan(progress=report, cancel=self.cancel_token)
            )
        except Exception as error:
            self.failed.emit(f"{type(error).__name__}: {error}")
        finally:
            self.finished.emit()


class RenderWorker(QObject):
    progress = Signal(int, str)
    completed = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(
        self,
        records: tuple,
        request_payload: Mapping[str, object],
        output_root: Path,
    ) -> None:
        super().__init__()
        self.records = records
        self.request_payload = dict(request_payload)
        self.output_root = output_root

    @Slot()
    def run(self) -> None:
        try:
            categories = tuple(
                str(item)
                for item in (
                    self.request_payload.get("categories")
                    or self.request_payload.get("slots")
                    or ()
                )
            )
            locked_identities = _locked_identities_by_slot(
                self.request_payload.get("locked_slots"),
                len(categories),
            )
            request = GenerationRequest(
                categories=categories,
                target_bpm=float(self.request_payload.get("target_bpm", 140)),
                target_key=str(
                    self.request_payload.get("target_key", "A minor")
                ),
                bars=int(self.request_payload.get("bars", 8)),
                seed=int(self.request_payload.get("seed", 0)),
                key_confidence_threshold=float(
                    self.request_payload.get(
                        "key_confidence_threshold",
                        DEFAULT_KEY_MARGIN_THRESHOLD,
                    )
                ),
                excluded_identities=frozenset(
                    str(identity)
                    for identity in self.request_payload.get(
                        "excluded_identities", ()
                    )
                ),
                locked_identities_by_slot=locked_identities,
            )
            candidates: list[LayerCandidate] = []
            skipped = 0
            for record in self.records:
                try:
                    candidates.append(LayerCandidate.from_record(record))
                except Exception:
                    skipped += 1
            if not candidates:
                raise SelectionError(
                    "No scanned layer has enough BPM/key metadata to generate."
                )

            self.progress.emit(5, "Selecting compatible layers")
            plan = select_generation(candidates, request)
            for slot_index, identity in self.request_payload.get(
                "alternate_key_slots", ()
            ):
                plan = plan_with_alternate_key(
                    plan,
                    slot_index=int(slot_index),
                    identity=str(identity),
                )
            for slot_index, identity, semitones in self.request_payload.get(
                "manual_pitch_slots", ()
            ):
                plan = plan_with_manual_pitch(
                    plan,
                    slot_index=int(slot_index),
                    identity=str(identity),
                    semitones=int(semitones),
                )
            for slot_index, identity in self.request_payload.get(
                "normalization_slots", ()
            ):
                plan = plan_with_normalization(
                    plan,
                    slot_index=int(slot_index),
                    identity=str(identity),
                    enabled=True,
                )

            def report(message: str, completed: int, total: int) -> None:
                portion = 0 if total <= 0 else completed / total
                self.progress.emit(
                    min(98, 10 + round(portion * 86)),
                    message,
                )

            render = render_generation(
                RenderRequest(
                    plan=plan,
                    output_root=self.output_root,
                    generation_name="Generated Loop",
                ),
                progress=report,
            )
            self.completed.emit(
                {
                    "render": render,
                    "plan": plan,
                    "skipped_metadata": skipped,
                    "selection_identities": tuple(
                        selection.candidate.identity
                        for selection in plan.selections
                    ),
                    "locked_slots": tuple(
                        (slot_index, identity)
                        for slot_index, identity in enumerate(
                            request.locked_identities_by_slot
                        )
                        if identity is not None
                    ),
                    "history_base_index": int(
                        self.request_payload.get("history_base_index", -1)
                    ),
                }
            )
        except Exception as error:
            self.failed.emit(f"{type(error).__name__}: {error}")
        finally:
            self.finished.emit()


class LayerTransformRenderWorker(QObject):
    progress = Signal(int, str)
    completed = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(
        self,
        render,
        plan,
        slot_index: int,
        identity: str,
        operation: str,
        value: object,
    ) -> None:
        super().__init__()
        self.render = render
        self.plan = plan
        self.slot_index = int(slot_index)
        self.identity = str(identity)
        self.operation = str(operation)
        self.value = value

    @Slot()
    def run(self) -> None:
        try:
            if self.operation == "key_rank":
                updated_plan = plan_with_source_key_rank(
                    self.plan,
                    slot_index=self.slot_index,
                    identity=self.identity,
                    source_key_rank=int(self.value),
                )
            elif self.operation == "manual_pitch":
                updated_plan = plan_with_manual_pitch(
                    self.plan,
                    slot_index=self.slot_index,
                    identity=self.identity,
                    semitones=int(self.value),
                )
            elif self.operation == "normalization":
                updated_plan = plan_with_normalization(
                    self.plan,
                    slot_index=self.slot_index,
                    identity=self.identity,
                    enabled=bool(self.value),
                )
            else:
                raise ValueError(f"Unsupported layer transform: {self.operation}")

            def report(message: str, completed: int, total: int) -> None:
                portion = 0 if total <= 0 else completed / total
                self.progress.emit(round(portion * 100), message)

            updated_render = rerender_selected_layer(
                RenderRequest(
                    plan=updated_plan,
                    output_root=self.render.output_directory.parent,
                    generation_name="Generated Loop",
                    sample_rate=self.render.timeline.sample_rate,
                    channels=(
                        int(self.render.stem_audio_pcm[0].shape[1])
                        if self.render.stem_audio_pcm
                        and self.render.stem_audio_pcm[0].ndim == 2
                        else 1
                    ),
                    gap_bars=self.render.timeline.gap_bars,
                ),
                self.render,
                slot_index=self.slot_index,
                identity=self.identity,
                progress=report,
            )
            self.completed.emit(
                {
                    "render": updated_render,
                    "plan": updated_plan,
                    "slot_index": self.slot_index,
                    "identity": self.identity,
                    "operation": self.operation,
                    "value": self.value,
                }
            )
        except Exception as error:
            self.failed.emit(f"{type(error).__name__}: {error}")
        finally:
            self.finished.emit()


class GeneratorController(QObject):
    """Own the long-lived model process and short-lived scan/render threads."""

    generationHistoryChanged = Signal(object)
    generationHistoryFailed = Signal(str)

    def __init__(self, window: QObject, *, dialog_parent: QObject | None = None) -> None:
        super().__init__(window)
        self.window = window
        # GeneratePage lives inside a QGraphicsProxyWidget.  Its ``window()``
        # is therefore the embedded StudioRoot canvas, not the native
        # QMainWindow.  Native modal dialogs parented to that proxy can leave
        # the Windows viewport partially black or clipped.  Keep the genuine
        # application window supplied by app.py, matching both Quick Tools
        # history managers.
        self.dialog_parent = dialog_parent
        self.scan_result: ScanResult | None = None
        self.last_output: Path | None = None
        self._scan_thread: QThread | None = None
        self._scan_worker: ScanWorker | None = None
        self._render_thread: QThread | None = None
        self._render_worker: RenderWorker | None = None
        self._layer_transform_target: tuple[int, str, str, object] | None = None
        self._shutting_down = False
        self._last_generation_identities: frozenset[str] = frozenset()
        self._generation_history: deque[dict[str, object]] = deque(maxlen=10)
        self._history_index = -1
        self.settings = QSettings("Antiworld", "Stem Slicer")
        self.classifier = MertLayerClassifier(
            python_executable=sys.executable,
            device=os.environ.get("STEM_SLICER_MERT_DEVICE", "cpu"),
        )

        window.scanRequested.connect(self.start_scan)
        window.generateRequested.connect(self.start_generation)
        window.generateAgainRequested.connect(self.start_generation)
        window.previewSeedRequested.connect(self.preview_previous_seed)
        lock_changed = getattr(window, "lockChanged", None)
        if lock_changed is not None:
            lock_changed.connect(self.update_lock_state)
        alternate_key_requested = getattr(window, "alternateKeyRequested", None)
        if alternate_key_requested is not None:
            alternate_key_requested.connect(self.start_alternate_key_render)
        octave_shift_requested = getattr(window, "octaveShiftRequested", None)
        if octave_shift_requested is not None:
            octave_shift_requested.connect(self.start_manual_pitch_render)
        normalization_requested = getattr(window, "normalizationRequested", None)
        if normalization_requested is not None:
            normalization_requested.connect(self.start_normalization_render)
        window.openOutputRequested.connect(self.open_output)
        manage_requested = getattr(window, "manageRequested", None)
        if manage_requested is not None:
            manage_requested.connect(self.show_generation_manager)
        QTimer.singleShot(0, self.restore_cached_library)
        QTimer.singleShot(0, self.refresh_generation_history)

    @Slot()
    def restore_cached_library(self) -> None:
        """Restore the last complete SQLite inventory without rescanning."""

        if (
            self._shutting_down
            or self.scan_result is not None
            or self._scan_thread is not None
            or not hasattr(self.window, "restore_library_path")
        ):
            return
        saved = self.settings.value(
            "generate/last_library_path", "", type=str
        )
        candidates: list[Path] = []
        if saved:
            candidates.append(Path(saved).expanduser())
        recent = most_recent_cached_library_root(default_cache_path())
        if recent is not None and all(
            recent.resolve(strict=False) != item.resolve(strict=False)
            for item in candidates
        ):
            candidates.append(recent)

        for candidate in candidates:
            try:
                key_confidence_index = KeyConfidenceIndex()
                inventory_path, results_path = self._key_confidence_paths()
                if inventory_path is not None and results_path is not None:
                    key_confidence_index = KeyConfidenceIndex.from_files(
                        library_root=candidate,
                        inventory_path=inventory_path,
                        results_path=results_path,
                        threshold=DEFAULT_KEY_MARGIN_THRESHOLD,
                    )
                library = LayerLibrary(
                    candidate,
                    default_cache_path(),
                    classifier=self.classifier,
                    key_confidence_index=key_confidence_index,
                )
                result = library.load_cached()
            except Exception:
                continue
            if not result.records:
                continue
            self.window.restore_library_path(result.library_root)
            if any(
                issue.code == "stale_classifier_cache"
                for issue in result.issues
            ):
                # The feature-extractor identity is stable between V2 and V3,
                # so this scan replays the lightweight head from cached
                # vectors instead of recomputing MERT for unchanged audio.
                self.window.set_scan_busy(
                    True,
                    0,
                    "Updating library categories to the current model…",
                )
                self.start_scan(result.library_root)
                return
            self._scan_completed(result)
            key_counts = result.key_confidence_counts
            safe = int(key_counts.get("safe", 0))
            uncertain = int(key_counts.get("uncertain", 0))
            self.window.set_scan_busy(
                False,
                100,
                (
                    f"{len(result.records)} layers loaded from SQLite cache"
                    f" · {safe} safe / {uncertain} uncertain"
                    " · scan only for new or changed files"
                ),
            )
            return

    def _development_truth_path(self) -> Path | None:
        """Return an explicitly requested development-only truth overlay.

        There is intentionally no project manifest fallback here.  In
        particular, ``research/.../manifest.csv`` belongs only to model
        training and must never label a user's scanned library implicitly.
        """

        explicit = os.environ.get(DEVELOPMENT_TRUTH_ENV, "").strip()
        if not explicit:
            return None
        candidate = Path(explicit).expanduser()
        return candidate.resolve() if candidate.is_file() else None

    def _key_confidence_paths(self) -> tuple[Path | None, Path | None]:
        inventory = Path(
            os.environ.get(
                "STEM_SLICER_KEY_CONFIDENCE_INVENTORY",
                str(DEFAULT_KEY_CONFIDENCE_INVENTORY),
            )
        ).expanduser()
        results = Path(
            os.environ.get(
                "STEM_SLICER_KEY_CONFIDENCE_RESULTS",
                str(DEFAULT_KEY_CONFIDENCE_RESULTS),
            )
        ).expanduser()
        if not inventory.is_file() or not results.is_file():
            return None, None
        return inventory, results

    @Slot(str)
    def start_scan(self, raw_path: str) -> None:
        if (
            self._shutting_down
            or self._scan_thread is not None
            or self._render_thread is not None
        ):
            return
        path = Path(raw_path).expanduser()
        if not path.is_dir():
            self.window.set_scan_busy(
                False, 0, "Choose a valid layer-library folder."
            )
            return

        self.scan_result = None
        self.last_output = None
        self._generation_history.clear()
        self._history_index = -1
        self.window.set_preview_seed_available(False)
        self.window.reset_generation_results(
            "Scanning the selected library…"
        )
        self.window.set_scan_busy(True, 0, "Inventorying library")
        confidence_inventory, confidence_results = self._key_confidence_paths()
        development_truth_path = self._development_truth_path()
        cache_path = (
            development_truth_cache_path()
            if development_truth_path is not None
            else default_cache_path()
        )
        thread = QThread(self)
        worker = ScanWorker(
            path,
            cache_path,
            classifier=self.classifier,
            development_truth_path=development_truth_path,
            key_confidence_inventory_path=confidence_inventory,
            key_confidence_results_path=confidence_results,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._scan_progress)
        worker.completed.connect(self._scan_completed)
        worker.failed.connect(self._scan_failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._scan_thread_finished)
        self._scan_thread = thread
        self._scan_worker = worker
        thread.start()

    @Slot(object)
    def _scan_completed(self, result: ScanResult) -> None:
        if result.cancelled:
            self.scan_result = None
            self.window.set_scan_busy(False, 0, "Scan cancelled.")
            return
        self.scan_result = result
        self.settings.setValue(
            "generate/last_library_path", result.library_root
        )
        self._last_generation_identities = frozenset()
        self._generation_history.clear()
        self._history_index = -1
        self.window.set_preview_seed_available(False)
        self.window.set_library_summary(
            result.inventory_count,
            result.category_counts,
            result.unreviewed_count,
        )
        predicted = sum(
            record.label_source == "prediction" for record in result.records
        )
        status = (
            f"{len(result.records)} layers ready · "
            f"{result.unreviewed_count} to review"
        )
        if predicted:
            status += f" · {predicted} model predictions"
        if result.issues:
            status += f" · {len(result.issues)} warning(s)"
        key_counts = result.key_confidence_counts
        safe = int(key_counts.get("safe", 0))
        uncertain = int(key_counts.get("uncertain", 0))
        conflicts = int(key_counts.get("conflict", 0))
        unavailable = int(key_counts.get("unavailable", 0))
        if safe or uncertain or conflicts:
            status += f" · key pool {safe} safe / {uncertain} uncertain"
            if conflicts:
                status += f" / {conflicts} conflict"
        elif unavailable:
            status += " · key confidence unavailable"
        self.window.set_scan_busy(False, 100, status)

    @Slot(str)
    def _scan_failed(self, message: str) -> None:
        self.window.set_scan_busy(False, 0, message)

    @Slot(int, str)
    def _scan_progress(self, progress: int, status: str) -> None:
        self.window.set_scan_busy(True, int(progress), str(status))

    @Slot()
    def _scan_thread_finished(self) -> None:
        self._scan_thread = None
        self._scan_worker = None

    def _generation_payload(
        self, payload: Mapping[str, object]
    ) -> dict[str, object]:
        request_payload = dict(payload)
        history_base_index = (
            self._history_index
            if 0 <= self._history_index < len(self._generation_history)
            else -1
        )
        locked_slots: dict[int, str] = {}
        previous_identities = self._last_generation_identities
        if history_base_index >= 0:
            snapshot = self._generation_history[history_base_index]
            previous_identities = self._snapshot_selection_identities(snapshot)
        categories = tuple(request_payload.get("categories") or ())
        raw_locked_slots = request_payload.get("locked_slots")
        if "locked_slots" not in request_payload and history_base_index >= 0:
            raw_locked_slots = self._snapshot_locked_slots(snapshot)
        try:
            aligned_locks = _locked_identities_by_slot(
                raw_locked_slots,
                len(categories),
            )
        except (TypeError, ValueError):
            # A legacy/stale history lock must never block a current recipe.
            aligned_locks = (None,) * len(categories)
        locked_slots = {
            slot_index: identity
            for slot_index, identity in enumerate(aligned_locks)
            if identity is not None
        }
        locked_identities = frozenset(locked_slots.values())
        request_payload["excluded_identities"] = tuple(
            previous_identities - locked_identities
        )
        request_payload["locked_slots"] = tuple(sorted(locked_slots.items()))
        alternate_key_slots: list[tuple[int, str]] = []
        manual_pitch_slots: list[tuple[int, str, int]] = []
        normalization_slots: list[tuple[int, str]] = []
        if history_base_index >= 0:
            stem_state_by_identity = {
                str(raw_stem.get("identity", "")): raw_stem
                for raw_stem in snapshot.get("stems", ())
                if isinstance(raw_stem, Mapping)
                and str(raw_stem.get("identity", "")).strip()
            }
            for slot_index, identity in locked_slots.items():
                raw_stem = stem_state_by_identity.get(identity)
                if raw_stem is None:
                    continue
                if raw_stem.get("alternate_key_used"):
                    alternate_key_slots.append((slot_index, identity))
                manual_pitch = int(
                    raw_stem.get("manual_pitch_semitones", 0) or 0
                )
                if manual_pitch:
                    manual_pitch_slots.append(
                        (slot_index, identity, manual_pitch)
                    )
                if raw_stem.get("normalization_enabled"):
                    normalization_slots.append((slot_index, identity))
        request_payload["alternate_key_slots"] = tuple(alternate_key_slots)
        request_payload["manual_pitch_slots"] = tuple(manual_pitch_slots)
        request_payload["normalization_slots"] = tuple(normalization_slots)
        request_payload["history_base_index"] = history_base_index
        return request_payload

    @staticmethod
    def _snapshot_selection_identities(
        snapshot: Mapping[str, object],
    ) -> frozenset[str]:
        explicit = snapshot.get("selection_identities")
        if explicit is not None:
            return frozenset(str(identity) for identity in explicit)
        return frozenset(
            str(stem["identity"])
            for stem in snapshot.get("stems", ())
            if isinstance(stem, Mapping) and stem.get("identity")
        )

    @staticmethod
    def _snapshot_locked_slots(
        snapshot: Mapping[str, object],
    ) -> dict[int, str]:
        if "locked_slots" in snapshot:
            raw_locked = snapshot.get("locked_slots") or ()
            items = raw_locked.items() if isinstance(raw_locked, Mapping) else raw_locked
            return {
                int(slot_index): str(identity)
                for slot_index, identity in items
                if str(identity or "").strip()
            }
        return {
            int(stem["slot_index"]): str(stem["identity"])
            for stem in snapshot.get("stems", ())
            if (
                isinstance(stem, Mapping)
                and stem.get("locked")
                and stem.get("slot_index") is not None
                and stem.get("identity")
            )
        }

    @Slot(int, str, bool)
    def update_lock_state(
        self,
        slot_index: int,
        identity: str,
        locked: bool,
    ) -> None:
        """Persist a card lock on the currently displayed history snapshot."""

        if not 0 <= self._history_index < len(self._generation_history):
            return
        normalized_identity = str(identity).strip()
        if not normalized_identity or int(slot_index) < 0:
            return
        snapshot = self._generation_history[self._history_index]
        updated_stems: list[dict[str, object]] = []
        updated_stem_payload: dict[str, object] | None = None
        matched = False
        for raw_stem in snapshot.get("stems", ()):
            stem = dict(raw_stem)
            same_slot = int(stem.get("slot_index", -1)) == int(slot_index)
            same_identity = str(stem.get("identity", "")) == normalized_identity
            if same_slot and same_identity:
                stem["locked"] = bool(locked)
                matched = True
            elif same_slot and locked:
                stem["locked"] = False
            updated_stems.append(stem)
        if not matched:
            return
        snapshot["stems"] = tuple(updated_stems)
        snapshot["locked_slots"] = tuple(
            sorted(
                (
                    int(stem["slot_index"]),
                    str(stem["identity"]),
                )
                for stem in updated_stems
                if (
                    stem.get("locked")
                    and stem.get("slot_index") is not None
                    and stem.get("identity")
                )
            )
        )

    def _truncate_history_after(self, base_index: int) -> None:
        """Drop a future branch only after its replacement rendered successfully."""

        if not -1 <= base_index < len(self._generation_history):
            return
        while len(self._generation_history) - 1 > base_index:
            self._generation_history.pop()
        self._history_index = len(self._generation_history) - 1

    @Slot(dict)
    def start_generation(self, payload: Mapping[str, object]) -> None:
        if self._shutting_down or self._render_thread is not None:
            return
        if self.scan_result is None:
            self.window.set_generation_busy(
                False, "Scan a layer library before generating."
            )
            return

        self.window.set_generation_busy(True, "Selecting compatible layers")
        request_payload = self._generation_payload(payload)
        thread = QThread(self)
        worker = RenderWorker(
            self.scan_result.records,
            request_payload,
            default_output_root(),
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._render_progress)
        worker.completed.connect(self._render_completed)
        worker.failed.connect(self._render_failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._render_thread_finished)
        self._render_thread = thread
        self._render_worker = worker
        thread.start()

    @Slot(object)
    def _render_completed(self, payload: dict) -> None:
        import json

        result = payload["render"]
        selection_identities = frozenset(
            str(identity)
            for identity in payload.get("selection_identities", ())
        )
        locked_slots = {
            int(slot_index): str(identity)
            for slot_index, identity in payload.get("locked_slots", ())
        }
        if selection_identities:
            self._last_generation_identities = selection_identities
        target_bpm = result.timeline.target_bpm
        manifest_payload = json.loads(
            result.manifest_path.read_text(encoding="utf-8")
        )
        destination_key = manifest_payload["target"]["key"]
        master = {
            "path": str(result.master_path),
            "name": result.master_path.name,
            "display_name": "GENERATED LOOP + LAYERS",
            "category": "Master",
            "bpm": target_bpm,
            "key": destination_key,
            "peaks": tuple(getattr(result, "master_waveform_peaks", ())),
        }
        stems = []
        for item in result.stem_results:
            source_key = _selection_source_key_text(item.selection)
            alternate_key = (
                " ".join(
                    str(value)
                    for value in (
                        item.selection.candidate.alternate_scanned_key,
                        item.selection.candidate.alternate_scanned_mode,
                    )
                    if value
                )
                if item.selection.candidate.key_sensitive
                else ""
            )
            stems.append(
                {
                    "path": str(item.output_path),
                    "name": item.output_path.name,
                    "display_name": item.selection.category.upper(),
                    "category": item.selection.category,
                    "slot_index": item.selection.slot_index,
                    "identity": item.selection.candidate.identity,
                    "bpm": target_bpm,
                    "key": destination_key,
                    "source_name": item.selection.candidate.path.name,
                    "source_bpm": item.selection.candidate.source_bpm,
                    "source_key": source_key or "—",
                    "alternate_key": alternate_key or None,
                    "alternate_key_used": item.selection.source_key_rank == 2,
                    "source_key_rank": item.selection.source_key_rank,
                    "manual_pitch_semitones": (
                        item.selection.manual_pitch_semitones
                    ),
                    "normalization_enabled": (
                        item.selection.normalization_enabled
                    ),
                    "key_confidence_margin": (
                        item.selection.candidate.key_confidence_margin
                    ),
                    "key_confidence_status": (
                        item.selection.candidate.key_confidence_status
                    ),
                    "confidence": item.selection.confidence,
                    "label_source": item.selection.label_source,
                    "peaks": tuple(getattr(item, "waveform_peaks", ())),
                    "locked": (
                        locked_slots.get(item.selection.slot_index)
                        == item.selection.candidate.identity
                    ),
                }
            )
        self._truncate_history_after(
            int(payload.get("history_base_index", len(self._generation_history) - 1))
        )
        snapshot = {
            "seed": int(manifest_payload["seed"]),
            "recipe": tuple(manifest_payload.get("recipe", ())),
            "output_directory": str(result.output_directory),
            "master": dict(master),
            "stems": tuple(dict(item) for item in stems),
            "selection_identities": tuple(selection_identities),
            "locked_slots": tuple(sorted(locked_slots.items())),
            "render": result,
            "plan": payload["plan"],
        }
        self._generation_history.append(snapshot)
        self._history_index = len(self._generation_history) - 1
        self._display_history_entry(
            self._history_index,
            status=f"Generation ready · {result.output_directory.name}",
        )
        self.refresh_generation_history()

    @Slot(int, str)
    def start_alternate_key_render(self, slot_index: int, identity: str) -> None:
        matching = self._matching_history_stem(slot_index, identity)
        if matching is None or not matching.get("alternate_key"):
            return
        desired_rank = 1 if matching.get("alternate_key_used") else 2
        status = (
            "Restoring original key"
            if desired_rank == 1
            else "Applying alternate key"
        )
        self._start_layer_transform(
            slot_index,
            identity,
            operation="key_rank",
            value=desired_rank,
            status=status,
        )

    @Slot(int, str, int)
    def start_manual_pitch_render(
        self,
        slot_index: int,
        identity: str,
        semitones: int,
    ) -> None:
        requested = int(semitones)
        if requested not in (-12, 0, 12):
            return
        status = (
            "Restoring original pitch"
            if requested == 0
            else f"Applying pitch {requested:+d}"
        )
        self._start_layer_transform(
            slot_index,
            identity,
            operation="manual_pitch",
            value=requested,
            status=status,
        )

    @Slot(int, str, bool)
    def start_normalization_render(
        self,
        slot_index: int,
        identity: str,
        enabled: bool,
    ) -> None:
        self._start_layer_transform(
            slot_index,
            identity,
            operation="normalization",
            value=bool(enabled),
            status=(
                "Normalizing layer"
                if enabled
                else "Restoring original level"
            ),
        )

    def _matching_history_stem(
        self,
        slot_index: int,
        identity: str,
    ) -> Mapping[str, object] | None:
        if not 0 <= self._history_index < len(self._generation_history):
            return None
        normalized_identity = str(identity).strip()
        stems = tuple(
            stem
            for stem in self._generation_history[self._history_index].get(
                "stems", ()
            )
            if isinstance(stem, Mapping)
            and str(stem.get("identity", "")) == normalized_identity
        )
        return next(
            (
                stem
                for stem in stems
                if int(stem.get("slot_index", -1)) == int(slot_index)
            ),
            stems[0] if stems else None,
        )

    def _start_layer_transform(
        self,
        slot_index: int,
        identity: str,
        *,
        operation: str,
        value: object,
        status: str,
    ) -> None:
        if self._shutting_down or self._render_thread is not None:
            return
        if not 0 <= self._history_index < len(self._generation_history):
            return
        snapshot = self._generation_history[self._history_index]
        render = snapshot.get("render")
        plan = snapshot.get("plan")
        normalized_identity = str(identity).strip()
        matching = self._matching_history_stem(slot_index, normalized_identity)
        if render is None or plan is None or matching is None:
            return

        self._layer_transform_target = (
            int(slot_index),
            normalized_identity,
            str(operation),
            value,
        )
        self.window.set_generation_busy(True, status)
        self._set_card_transform_busy(
            int(slot_index), normalized_identity, True
        )
        thread = QThread(self)
        worker = LayerTransformRenderWorker(
            render,
            plan,
            int(slot_index),
            normalized_identity,
            str(operation),
            value,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._render_progress)
        worker.completed.connect(self._layer_transform_render_completed)
        worker.failed.connect(self._layer_transform_render_failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._render_thread_finished)
        self._render_thread = thread
        self._render_worker = worker
        thread.start()

    def _set_card_transform_busy(
        self,
        slot_index: int,
        identity: str,
        busy: bool,
    ) -> None:
        setter = getattr(
            self.window,
            "set_layer_transform_busy",
            getattr(self.window, "set_alternate_key_busy", None),
        )
        if setter is not None:
            setter(int(slot_index), str(identity), bool(busy))

    @Slot(object)
    def _layer_transform_render_completed(self, payload: dict) -> None:
        target = self._layer_transform_target
        if target is None:
            return
        if not 0 <= self._history_index < len(self._generation_history):
            self._layer_transform_target = None
            self._set_card_transform_busy(target[0], target[1], False)
            self.window.set_generation_busy(
                False,
                "Layer update could not be attached to the active generation.",
            )
            return
        slot_index, identity, operation, value = target
        if (
            int(payload.get("slot_index", -1)) != slot_index
            or str(payload.get("identity", "")) != identity
            or str(payload.get("operation", "")) != operation
        ):
            self._layer_transform_target = None
            self._set_card_transform_busy(slot_index, identity, False)
            self.window.set_generation_busy(
                False,
                "Layer update response did not match the active card.",
            )
            return
        snapshot = self._generation_history[self._history_index]
        result = payload["render"]
        plan = payload["plan"]
        result_by_identity = {
            item.selection.candidate.identity: item
            for item in result.stem_results
        }
        if identity not in result_by_identity:
            self._layer_transform_target = None
            self._set_card_transform_busy(slot_index, identity, False)
            self.window.set_generation_busy(
                False,
                "The updated layer is missing from the render result.",
            )
            return
        updated_stems: list[dict[str, object]] = []
        for raw_stem in snapshot.get("stems", ()):
            stem = dict(raw_stem)
            if str(stem.get("identity", "")) == identity:
                item = result_by_identity[identity]
                source_key = _selection_source_key_text(item.selection)
                stem.update(
                    {
                        # Recipe slots may have shifted since this loop was
                        # rendered.  Identity is stable; the visible slot is
                        # kept current for subsequent card interactions.
                        "slot_index": slot_index,
                        "source_key": source_key or "—",
                        "alternate_key_used": (
                            item.selection.source_key_rank == 2
                        ),
                        "source_key_rank": item.selection.source_key_rank,
                        "manual_pitch_semitones": (
                            item.selection.manual_pitch_semitones
                        ),
                        "normalization_enabled": (
                            item.selection.normalization_enabled
                        ),
                        "peaks": tuple(item.waveform_peaks),
                    }
                )
                updated_stem_payload = stem
            updated_stems.append(stem)
        master = dict(snapshot["master"])
        master["peaks"] = tuple(result.master_waveform_peaks)
        snapshot["master"] = master
        snapshot["stems"] = tuple(updated_stems)
        snapshot["render"] = result
        snapshot["plan"] = plan
        self._layer_transform_target = None
        if operation == "key_rank":
            action = (
                "Original key restored" if int(value) == 1 else "Alternate key applied"
            )
        elif operation == "manual_pitch":
            action = (
                "Original pitch restored"
                if int(value) == 0
                else f"Pitch {int(value):+d} applied"
            )
        else:
            action = "Layer normalized" if bool(value) else "Original level restored"
        status = f"{action} · {result.output_directory.name}"
        updater = getattr(self.window, "update_generation_layer", None)
        result_offset = next(
            (
                offset
                for offset, item in enumerate(result.stem_results)
                if item.selection.candidate.identity == identity
            ),
            None,
        )
        hot_swapped = bool(
            updater is not None
            and updated_stem_payload is not None
            and result_offset is not None
            and updater(
                dict(updated_stem_payload),
                result.stem_audio_pcm[result_offset],
            )
        )
        if hot_swapped:
            self.window.set_preview_seed_available(self._history_index > 0)
            self.window.set_generation_busy(False, status)
        else:
            self._set_card_transform_busy(slot_index, identity, False)
            self.window.set_generation_busy(
                False,
                f"{action}, but the live audio buffer could not be updated.",
            )
        self.refresh_generation_history()

    @Slot(str)
    def _layer_transform_render_failed(self, message: str) -> None:
        target = self._layer_transform_target
        self._layer_transform_target = None
        if target is not None:
            self._set_card_transform_busy(target[0], target[1], False)
        self.window.set_generation_busy(False, message)

    @Slot(int, str)
    def _render_progress(self, _progress: int, status: str) -> None:
        """Marshal every worker progress update onto the controller/UI thread."""

        self.window.set_generation_busy(True, str(status))

    def _display_history_entry(self, index: int, *, status: str) -> bool:
        if not 0 <= index < len(self._generation_history):
            return False
        snapshot = self._generation_history[index]
        master = dict(snapshot["master"])
        stems = [dict(item) for item in snapshot["stems"]]
        paths = [Path(str(master["path"]))] + [
            Path(str(item["path"])) for item in stems
        ]
        missing = [path.name for path in paths if not path.is_file()]
        if missing:
            self.window.set_preview_seed_available(False)
            self.window.set_generation_busy(
                False,
                f"Previous seed is unavailable · missing {missing[0]}",
            )
            return False
        self._history_index = index
        self.last_output = Path(str(snapshot["output_directory"]))
        self.window.set_generation_results(master, stems)
        self.window.set_preview_seed_available(index > 0)
        self.window.set_generation_busy(False, status)
        return True

    @Slot()
    def preview_previous_seed(self) -> None:
        if self._shutting_down or self._render_thread is not None:
            return
        target_index = self._history_index - 1
        skipped_seeds: list[str] = []
        while target_index >= 0:
            snapshot = self._generation_history[target_index]
            master = snapshot["master"]
            stems = snapshot["stems"]
            paths = [Path(str(master["path"]))] + [
                Path(str(item["path"])) for item in stems
            ]
            if all(path.is_file() for path in paths):
                suffix = (
                    f" · skipped missing seed(s) {', '.join(skipped_seeds)}"
                    if skipped_seeds
                    else ""
                )
                self._display_history_entry(
                    target_index,
                    status=(
                        f"Previous seed {snapshot['seed']} · existing render"
                        f"{suffix}"
                    ),
                )
                return
            skipped_seeds.append(str(snapshot["seed"]))
            target_index -= 1
        if skipped_seeds:
            self.window.set_preview_seed_available(False)
            self.window.set_generation_busy(
                False,
                "Previous seed render(s) are no longer available.",
            )

    @Slot(str)
    def _render_failed(self, message: str) -> None:
        self.window.set_generation_busy(False, message)

    @Slot()
    def _render_thread_finished(self) -> None:
        self._render_thread = None
        self._render_worker = None

    @Slot()
    def open_output(self) -> None:
        self.open_generation_output(str(self.last_output or ""))

    def _generation_history_payload(self) -> dict[str, object]:
        entries = GenerateHistoryStore(default_output_root()).list_generations()
        total_bytes = sum(entry.size for entry in entries)
        total_layers = sum(entry.layers for entry in entries)
        return {
            "count": len(entries),
            "total_bytes": total_bytes,
            "total_size": format_decimal_size(total_bytes),
            "layers": total_layers,
            "entries": tuple(
                {
                    "name": entry.name,
                    "path": str(entry.path),
                    "size": entry.size,
                    "size_text": format_decimal_size(entry.size),
                    "layers": entry.layers,
                    "modified": entry.modified,
                }
                for entry in entries
            ),
        }

    def generation_history(self) -> tuple[dict[str, object], ...]:
        """Return the persistent on-disk Generate inventory, newest first."""

        return tuple(self._generation_history_payload()["entries"])

    def generation_history_summary(self) -> dict[str, object]:
        """Return decimal storage statistics for all completed generations."""

        payload = self._generation_history_payload()
        return {key: payload[key] for key in ("count", "total_bytes", "total_size", "layers")}

    @Slot()
    def refresh_generation_history(self) -> dict[str, object]:
        """Refresh footer consumers and popup models from the persistent root."""

        try:
            payload = self._generation_history_payload()
        except Exception as error:
            message = f"{type(error).__name__}: {error}"
            self.generationHistoryFailed.emit(message)
            return {
                "count": 0,
                "total_bytes": 0,
                "total_size": format_decimal_size(0),
                "layers": 0,
                "entries": (),
            }
        setter = getattr(self.window, "set_generation_history_summary", None)
        if setter is not None:
            setter(
                int(payload["count"]),
                int(payload["total_bytes"]),
                int(payload["layers"]),
            )
        self.generationHistoryChanged.emit(payload)
        return payload

    @Slot(str, result=bool)
    def open_generation_output(self, raw_path: str) -> bool:
        """Open only the Generate root or one direct child generation."""

        root = default_output_root().expanduser().resolve(strict=False)
        if str(raw_path or "").strip():
            target = Path(raw_path).expanduser().resolve(strict=False)
            if target.parent != root or not target.is_dir():
                self.generationHistoryFailed.emit(
                    "Refusing to open a path outside Generated Loops."
                )
                return False
        else:
            root.mkdir(parents=True, exist_ok=True)
            target = root
        try:
            open_in_file_manager(str(target))
        except Exception as error:
            self.generationHistoryFailed.emit(f"{type(error).__name__}: {error}")
            return False
        return True

    @Slot(str, result=bool)
    def trash_generation_output(self, raw_path: str) -> bool:
        """Move one complete generated package to Trash, never delete it."""

        if self._render_thread is not None:
            self.generationHistoryFailed.emit(
                "Wait for the current generation before moving history to Trash."
            )
            return False
        target = Path(raw_path).expanduser().resolve(strict=False)
        if not GenerateHistoryStore(default_output_root()).move_to_trash(target):
            self.generationHistoryFailed.emit(
                "The selected generation could not be moved to Trash."
            )
            return False
        self._forget_generation_output(target)
        self.refresh_generation_history()
        return True

    def _forget_generation_output(self, target: Path) -> None:
        """Keep Previous Seed state coherent after an on-disk package is trashed."""

        target = target.resolve(strict=False)
        snapshots = list(self._generation_history)
        current = (
            snapshots[self._history_index]
            if 0 <= self._history_index < len(snapshots)
            else None
        )
        kept = [
            snapshot
            for snapshot in snapshots
            if Path(str(snapshot.get("output_directory", ""))).resolve(strict=False)
            != target
        ]
        self._generation_history = deque(kept, maxlen=10)
        if current in kept:
            self._history_index = kept.index(current)
        else:
            self._history_index = len(kept) - 1
            if self.last_output is not None and self.last_output.resolve(strict=False) == target:
                self.last_output = None
        self.window.set_preview_seed_available(self._history_index > 0)

    @Slot()
    def show_generation_manager(self) -> None:
        """Open the Quick Extract-style persistent Generate history manager."""

        if self._render_thread is not None:
            self.window.set_generation_busy(
                True, "Finish the current generation before managing history."
            )
            return
        dialog = GenerateHistoryManagerDialog(
            default_output_root(),
            changed_callback=self._history_manager_changed,
            parent=self.dialog_parent,
        )
        dialog.exec()

    def _history_manager_changed(self) -> None:
        existing = {
            entry["path"] for entry in self.generation_history()
        }
        for snapshot in tuple(self._generation_history):
            output = str(snapshot.get("output_directory", ""))
            if output and output not in existing:
                self._forget_generation_output(Path(output))
        self.refresh_generation_history()

    @Slot()
    def shutdown(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        if self._scan_worker is not None:
            self._scan_worker.cancel()
        threads = tuple(
            thread
            for thread in (self._scan_thread, self._render_thread)
            if thread is not None
        )
        for thread in threads:
            thread.requestInterruption()
            thread.quit()
        for thread in threads:
            thread.wait()
        self._scan_thread = None
        self._scan_worker = None
        self._render_thread = None
        self._render_worker = None
        self.classifier.stop()


__all__ = [
    "GeneratorController",
    "default_cache_path",
    "default_output_root",
]
