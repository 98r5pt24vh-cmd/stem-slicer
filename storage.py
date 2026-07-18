import os
import re
import subprocess
import sys
from datetime import datetime

from PySide6.QtCore import QFile, QSettings, QStandardPaths


APP_FOLDER = "Stem Slicer"
EXTRACTIONS_FOLDER = "Extractions"
ANALYZED_FOLDER = "Analyzed Loops"
QUICK_EXTRACT_FOLDER = "Quick Extract"
QUICK_CONVERT_FOLDER = "Quick Convert"
CONVERTED_LOOPS_FOLDER = "Converted Loops"


def safe_name(value):
    value = re.sub(r'[\\/:*?"<>|]', "-", str(value)).strip().strip(".")
    return re.sub(r"\s+", " ", value) or "Untitled"


class StorageManager:
    CATEGORIES = {
        "extractions": EXTRACTIONS_FOLDER,
        "analyzed": ANALYZED_FOLDER,
        "quick": QUICK_EXTRACT_FOLDER,
        "convert": QUICK_CONVERT_FOLDER,
        "converted": CONVERTED_LOOPS_FOLDER,
    }

    def __init__(self, settings=None, now=None):
        self._uses_external_settings = settings is not None
        self.settings = settings or QSettings("Antiworld", "Stem Slicer")
        self._now = now or datetime.now

    @staticmethod
    def default_root():
        documents = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
        return os.path.abspath(os.path.join(documents or os.path.expanduser("~/Documents"), APP_FOLDER))

    @property
    def root(self):
        # The application workspace is deliberately stable. Injected settings
        # remain supported for isolated tests, but user destination choices are
        # session state managed by MainWindow rather than a persisted root.
        if not self._uses_external_settings:
            return self.default_root()
        configured = self.settings.value("storage/root", "", type=str)
        if configured:
            configured = os.path.abspath(os.path.expanduser(configured))
            default = self.default_root()
            try:
                inside_default_workspace = os.path.commonpath((configured, default)) == default
            except ValueError:
                inside_default_workspace = False
            if configured != default and inside_default_workspace:
                return default
            return configured
        return self.default_root()

    def set_root(self, path):
        path = os.path.abspath(os.path.expanduser(path))
        default = self.default_root()
        try:
            if path != default and os.path.commonpath((path, default)) == default:
                path = default
        except ValueError:
            pass
        self.settings.setValue("storage/root", path)

    def category_path(self, category):
        try:
            folder = self.CATEGORIES[category]
        except KeyError as exc:
            raise ValueError(f"Unknown storage category: {category}") from exc
        return os.path.join(self.root, folder)

    def ensure_category(self, category):
        path = self.category_path(category)
        os.makedirs(path, exist_ok=True)
        return path

    def unique_session_folder(self, category, base_name):
        parent = self.ensure_category(category)
        return self.unique_session_folder_in(parent, base_name)

    def unique_session_folder_in(self, parent, base_name):
        os.makedirs(parent, exist_ok=True)
        clean = safe_name(base_name)
        candidate = os.path.join(parent, clean)
        if not os.path.exists(candidate):
            os.makedirs(candidate)
            return candidate

        stamp = self._now()
        minute = stamp.strftime("%y-%m-%d %H-%M")
        candidate = os.path.join(parent, f"{clean} — {minute}")
        if not os.path.exists(candidate):
            os.makedirs(candidate)
            return candidate

        seconds = stamp.strftime("%y-%m-%d %H-%M-%S")
        candidate = os.path.join(parent, f"{clean} — {seconds}")
        os.makedirs(candidate)
        return candidate

    def list_quick_extracts(self):
        return self.list_sessions("quick", "layers")

    def list_quick_conversions(self):
        return self.list_sessions("convert", "files")

    def list_sessions(self, category, count_key):
        root = self.category_path(category)
        if not os.path.isdir(root):
            return []
        extracts = []
        for entry in os.scandir(root):
            if not entry.is_dir(follow_symlinks=False):
                continue
            size = 0
            layers = 0
            for directory, _, files in os.walk(entry.path):
                for filename in files:
                    path = os.path.join(directory, filename)
                    try:
                        size += os.path.getsize(path)
                    except OSError:
                        continue
                    if filename.lower().endswith(".mp3"):
                        layers += 1
            try:
                modified = entry.stat(follow_symlinks=False).st_mtime
            except OSError:
                modified = 0
            extracts.append({"name": entry.name, "path": entry.path, "size": size, count_key: layers, "layers": layers, "modified": modified})
        return sorted(extracts, key=lambda item: item["modified"], reverse=True)

    def move_quick_extract_to_trash(self, path):
        return self.move_session_to_trash("quick", path)

    def move_quick_conversion_to_trash(self, path):
        return self.move_session_to_trash("convert", path)

    def move_session_to_trash(self, category, path):
        root = os.path.realpath(self.category_path(category))
        target = os.path.realpath(path)
        try:
            inside_root = os.path.commonpath((root, target)) == root
        except ValueError:
            inside_root = False
        if not inside_root or target == root or not os.path.isdir(target):
            return False
        return bool(QFile.moveToTrash(target))

    @staticmethod
    def unique_file(path):
        if not os.path.exists(path):
            return path
        directory, filename = os.path.split(path)
        stem, extension = os.path.splitext(filename)
        index = 2
        while True:
            candidate = os.path.join(directory, f"{stem} ({index}){extension}")
            if not os.path.exists(candidate):
                return candidate
            index += 1


def format_decimal_size(byte_count):
    byte_count = max(0, int(byte_count))
    if byte_count >= 1_000_000_000:
        return f"{byte_count / 1_000_000_000:.1f} Go".replace(".", ",")
    if byte_count >= 1_000_000:
        return f"{byte_count / 1_000_000:.1f} Mo".replace(".", ",")
    if byte_count >= 1_000:
        return f"{byte_count / 1_000:.1f} Ko".replace(".", ",")
    return f"{byte_count} o"


def open_in_file_manager(path):
    path = os.path.abspath(path)
    os.makedirs(path, exist_ok=True)
    if sys.platform == "darwin":
        subprocess.Popen(["open", path])
    elif sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", path])
