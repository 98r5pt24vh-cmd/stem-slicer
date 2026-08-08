"""Generated-loop history model and manager dialog.

The dialog deliberately mirrors ``QuickExtractManagerDialog`` while keeping
Generate's output root independent from the accepted Stem Slicer storage
categories.  Every destructive action uses the platform Trash through Qt.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QFile, Qt, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from functional_core import (
    FileDragHandle,
    LayerPlayButton,
    button,
    icon_button,
    label,
    panel,
)
from storage import format_decimal_size, open_in_file_manager


_AUDIO_EXTENSIONS = frozenset({".mp3", ".wav", ".flac", ".aif", ".aiff"})


@dataclass(frozen=True, slots=True)
class GenerationHistoryEntry:
    """One on-disk generated-loop package."""

    name: str
    path: Path
    size: int
    layers: int
    modified: float
    master_path: Path | None = None


class GenerateHistoryStore:
    """Read and safely trash generated-loop packages below one output root."""

    def __init__(self, output_root: str | os.PathLike[str]) -> None:
        self.output_root = Path(output_root).expanduser().absolute()

    def list_generations(self) -> list[GenerationHistoryEntry]:
        root = self.output_root
        if not root.is_dir():
            return []

        entries: list[GenerationHistoryEntry] = []
        try:
            children = tuple(os.scandir(root))
        except OSError:
            return []

        for child in children:
            if not child.is_dir(follow_symlinks=False):
                continue
            path = Path(child.path)
            size = self._recursive_size(path)
            layers = self._layer_count(path)
            try:
                modified = child.stat(follow_symlinks=False).st_mtime
            except OSError:
                modified = 0.0
            entries.append(
                GenerationHistoryEntry(
                    name=child.name,
                    path=path,
                    size=size,
                    layers=layers,
                    modified=float(modified),
                    master_path=self._master_path(path),
                )
            )
        return sorted(entries, key=lambda entry: entry.modified, reverse=True)

    def stats(self) -> tuple[int, int, int]:
        """Return ``(generation_count, total_bytes, total_layer_count)``."""

        entries = self.list_generations()
        return (
            len(entries),
            sum(entry.size for entry in entries),
            sum(entry.layers for entry in entries),
        )

    def move_to_trash(self, path: str | os.PathLike[str]) -> bool:
        """Move one direct child generation to Trash after boundary checks."""

        root = self.output_root.resolve(strict=False)
        target = Path(path).expanduser().resolve(strict=False)
        if target == root or target.parent != root or not target.is_dir():
            return False
        return bool(QFile.moveToTrash(str(target)))

    @staticmethod
    def _recursive_size(path: Path) -> int:
        total = 0
        for directory, _, files in os.walk(path, followlinks=False):
            for filename in files:
                candidate = Path(directory, filename)
                if candidate.is_symlink():
                    continue
                try:
                    total += candidate.stat().st_size
                except OSError:
                    continue
        return total

    @classmethod
    def _layer_count(cls, path: Path) -> int:
        manifest_path = path / "generation.json"
        try:
            with manifest_path.open("r", encoding="utf-8") as stream:
                payload = json.load(stream)
            stems = payload.get("outputs", {}).get("stems", ())
            if isinstance(stems, list):
                return len(stems)
        except (OSError, TypeError, ValueError, AttributeError):
            pass

        count = 0
        try:
            candidates = tuple(path.iterdir())
        except OSError:
            return 0
        for candidate in candidates:
            if not candidate.is_file() or candidate.suffix.lower() not in _AUDIO_EXTENSIONS:
                continue
            lowered = candidate.stem.lower()
            if "master" in lowered or "presentation" in lowered:
                continue
            count += 1
        return count

    @classmethod
    def _master_path(cls, path: Path) -> Path | None:
        """Return the direct-child Full Loop referenced by one generation."""

        root = path.resolve(strict=False)
        manifest_path = path / "generation.json"
        try:
            with manifest_path.open("r", encoding="utf-8") as stream:
                payload = json.load(stream)
            raw_master = payload.get("outputs", {}).get("master")
            if isinstance(raw_master, str) and raw_master.strip():
                candidate = (path / raw_master).resolve(strict=False)
                if (
                    candidate.parent == root
                    and candidate.is_file()
                    and candidate.suffix.lower() in _AUDIO_EXTENSIONS
                ):
                    return candidate
        except (OSError, TypeError, ValueError, AttributeError):
            pass

        try:
            candidates = tuple(path.iterdir())
        except OSError:
            return None
        for candidate in candidates:
            if (
                candidate.is_file()
                and not candidate.is_symlink()
                and candidate.suffix.lower() in _AUDIO_EXTENSIONS
                and "master" in candidate.stem.lower()
            ):
                return candidate.resolve(strict=False)
        return None


def generate_history_stats(
    output_root: str | os.PathLike[str],
) -> tuple[int, int, int]:
    """Convenience adapter used by the compact Generate footer."""

    return GenerateHistoryStore(output_root).stats()


class GenerateHistoryManagerDialog(QDialog):
    """Quick Extract-style manager for prior Generate packages."""

    def __init__(
        self,
        output_root: str | os.PathLike[str],
        changed_callback: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.history = GenerateHistoryStore(output_root)
        self.changed_callback = changed_callback
        self.confirm_all = False
        self._current_audio_path = ""
        self._play_buttons: dict[str, LayerPlayButton] = {}

        self._audio_output = QAudioOutput(self)
        self._audio_output.setVolume(1.0)
        self._player = QMediaPlayer(self)
        self._player.setAudioOutput(self._audio_output)
        self._player.playbackStateChanged.connect(self._playback_state_changed)
        self.finished.connect(lambda _result: self._stop_playback())

        self.setWindowTitle("Generate Manager")
        self.setModal(True)
        self.setMinimumSize(760, 520)
        self.resize(760, 520)
        self.setProperty("role", "managerDialog")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(10)

        title_row = QHBoxLayout()
        title_copy = QVBoxLayout()
        title_copy.setSpacing(2)
        title_copy.addWidget(label("GENERATE HISTORY", "pageTitle"))
        title_copy.addWidget(
            label(
                "Saved generations remain available for DAWs and external projects.",
                "muted",
            )
        )
        title_row.addLayout(title_copy)
        title_row.addStretch()
        close_button = button("✕", "icon")
        close_button.setFixedSize(36, 32)
        close_button.clicked.connect(self.accept)
        title_row.addWidget(close_button)
        outer.addLayout(title_row)

        self.summary = label("", "storage")
        outer.addWidget(self.summary)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setProperty("role", "managerList")
        self.content = QWidget()
        self.rows = QVBoxLayout(self.content)
        self.rows.setContentsMargins(6, 6, 6, 6)
        self.rows.setSpacing(7)
        self.scroll.setWidget(self.content)
        outer.addWidget(self.scroll, 1)

        bottom = QHBoxLayout()
        open_button = icon_button(
            "folder", "OPEN GENERATED LOOPS FOLDER", icon_size=17
        )
        open_button.clicked.connect(
            lambda: open_in_file_manager(str(self.history.output_root))
        )
        self.trash_all = button("MOVE ALL TO TRASH", "danger")
        self.trash_all.clicked.connect(self._move_all)
        bottom.addWidget(open_button)
        bottom.addStretch()
        bottom.addWidget(self.trash_all)
        outer.addLayout(bottom)

        self.refresh()

    def refresh(self) -> None:
        self._play_buttons.clear()
        while self.rows.count():
            item = self.rows.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        entries = self.history.list_generations()
        total = sum(entry.size for entry in entries)
        layers = sum(entry.layers for entry in entries)
        generation_word = "generation" if len(entries) == 1 else "generations"
        layer_word = "layer" if layers == 1 else "layers"
        self.summary.setText(
            f"{len(entries)} {generation_word}  ·  "
            f"{layers} {layer_word}  ·  {format_decimal_size(total)}"
        )
        self.trash_all.setEnabled(bool(entries))

        if not entries:
            empty = label("No saved Generate history.", "muted")
            empty.setAlignment(Qt.AlignCenter)
            self.rows.addWidget(empty)
            self.rows.addStretch()
            return

        for entry in entries:
            row = panel("managerRow")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(12, 8, 10, 8)
            row_layout.setSpacing(12)

            master_path = str(entry.master_path or "")
            play_button = LayerPlayButton()
            play_button.setProperty("role", "layerPlay")
            play_button.setFixedSize(25, 25)
            play_button.setStyleSheet("padding:0;border-radius:12px;")
            play_button.setEnabled(bool(master_path))
            play_button.setToolTip(
                "Play or pause the Full Loop"
                if master_path
                else "Full Loop audio is unavailable"
            )
            play_button.clicked.connect(
                lambda checked=False, path=master_path: self._play_path(path)
            )
            if master_path:
                self._play_buttons[master_path] = play_button
            row_layout.addWidget(play_button)

            copy = QVBoxLayout()
            name = label(entry.name, "managerName")
            name.setToolTip(str(entry.path))
            layer_word = "layer" if entry.layers == 1 else "layers"
            copy.addWidget(name)
            copy.addWidget(
                label(
                    f"{entry.layers} {layer_word}  ·  "
                    f"{format_decimal_size(entry.size)}",
                    "mutedSmall",
                )
            )
            row_layout.addLayout(copy, 1)

            drag_handle = FileDragHandle(master_path)
            drag_handle.set_path(master_path)
            drag_handle.setToolTip(
                "Drag the Full Loop to your DAW"
                if master_path
                else "Full Loop audio is unavailable"
            )

            open_button = button("OPEN")
            open_button.clicked.connect(
                lambda checked=False, path=entry.path: open_in_file_manager(str(path))
            )
            trash_button = button("MOVE TO TRASH", "danger")
            trash_button.clicked.connect(
                lambda checked=False, path=entry.path: self._move_one(path)
            )
            row_layout.addWidget(drag_handle)
            row_layout.addWidget(open_button)
            row_layout.addWidget(trash_button)
            self.rows.addWidget(row)
        self.rows.addStretch()

    def _changed(self) -> None:
        self._stop_playback()
        self.confirm_all = False
        self.trash_all.setText("MOVE ALL TO TRASH")
        self.refresh()
        if self.changed_callback is not None:
            self.changed_callback()

    def _move_one(self, path: str | os.PathLike[str]) -> None:
        if self.history.move_to_trash(path):
            self._changed()

    def _move_all(self) -> None:
        entries = self.history.list_generations()
        if not entries:
            return
        if not self.confirm_all:
            self.confirm_all = True
            self.trash_all.setText(
                f"CONFIRM: MOVE {len(entries)} GENERATIONS TO TRASH"
            )
            return
        changed = False
        for entry in entries:
            changed = self.history.move_to_trash(entry.path) or changed
        if changed:
            self._changed()

    def _play_path(self, path: str) -> None:
        if not path:
            return
        if (
            self._current_audio_path == path
            and self._player.playbackState()
            == QMediaPlayer.PlaybackState.PlayingState
        ):
            self._player.pause()
            return
        if self._current_audio_path != path:
            self._current_audio_path = path
            self._player.setSource(QUrl.fromLocalFile(path))
        self._player.play()

    def _playback_state_changed(self, state) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        for path, play_button in self._play_buttons.items():
            active = playing and path == self._current_audio_path
            play_button.setText("" if active else "▶")
            play_button.setProperty("state", "playing" if active else "stopped")
            play_button.style().unpolish(play_button)
            play_button.style().polish(play_button)

    def _stop_playback(self) -> None:
        self._player.stop()
        self._current_audio_path = ""
        self._playback_state_changed(QMediaPlayer.PlaybackState.StoppedState)

    def closeEvent(self, event) -> None:
        self._stop_playback()
        super().closeEvent(event)


__all__ = [
    "GenerateHistoryManagerDialog",
    "GenerateHistoryStore",
    "GenerationHistoryEntry",
    "generate_history_stats",
]
