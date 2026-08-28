# -*- mode: python ; coding: utf-8 -*-

import shutil
import subprocess
from pathlib import Path


def filtered_payload(source_root, destination_root):
    """Collect a payload without mutable runtime caches or Finder metadata."""
    source_root = Path(source_root)
    excluded_suffixes = {".nbi", ".nbc"}
    items = []
    for source in source_root.rglob("*"):
        if not source.is_file() or source.name == ".DS_Store" or source.suffix.lower() in excluded_suffixes:
            continue
        relative_parent = source.relative_to(source_root).parent
        destination = Path(destination_root) / relative_parent
        items.append((str(source), str(destination)))
    return items

datas = [
    ("assets/stem-slicer-wordmark.png", "assets"),
    ("assets/antiworld-logo.png", "assets"),
    ("assets/app-icon.png", "assets"),
    ("assets/midi-logo-mask.png", "assets"),
    ("assets/key-engine-warmup.wav", "assets"),
    ("assets/key-and-bpm-engine-warmup.wav", "assets"),
    ("basic_pitch/saved_models/icassp_2022/nmp.onnx", "basic_pitch/saved_models/icassp_2022"),
    ("licenses/basic-pitch", "licenses/basic-pitch"),
    ("licenses/DeepRhythm-LICENSE.txt", "licenses"),
    ("licenses/Bungee-MPL-2.0.txt", "licenses"),
    ("THIRD_PARTY_NOTICES.md", "."),
    ("models/layer_roles_v3.joblib", "models"),
    ("models/layer_roles_v3.json", "models"),
]

# MERT is an offline first-scan dependency.  Bundle only its 95M snapshot and
# dynamic modeling module; mutable Hugging Face locks/logs are intentionally
# omitted from the signed application.
datas += filtered_payload(
    "models/huggingface/models--m-a-p--MERT-v1-95M",
    "models/huggingface/models--m-a-p--MERT-v1-95M",
)
datas += filtered_payload(
    "models/huggingface/modules",
    "models/huggingface/modules",
)

# Keep the validated OpenKeyScan/DeepRhythm runtime self-contained while
# excluding Numba cache files that must never be sealed into or rewrite the
# signed application bundle.
datas += filtered_payload("vendor/openkeyscan-analyzer", "openkeyscan-analyzer")

binaries = [
    ("vendor/ffmpeg-bin/ffmpeg", "."),
    ("bin/bungee", "bin"),
]

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        "basic_pitch",
        "basic_pitch.inference",
        "pretty_midi",
        "onnxruntime",
        "mert_worker",
        "torch",
        "transformers",
        "transformers.models.wav2vec2",
        "sklearn.pipeline",
        "sklearn.preprocessing._data",
        "sklearn.linear_model._logistic",
        "layer_role_classifier",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "AppKit",
        "Foundation",
        "objc",
        "coremltools",
        "tensorflow",
        "tflite_runtime",
        "torchaudio",
        "torchvision",
        "matplotlib",
        "pandas",
        "PySide6.Qt3DCore",
        "PySide6.QtBluetooth",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtLocation",
        "PySide6.QtNetworkAuth",
        "PySide6.QtPdf",
        "PySide6.QtPositioning",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtRemoteObjects",
        "PySide6.QtScxml",
        "PySide6.QtSensors",
        "PySide6.QtSerialPort",
        "PySide6.QtSpatialAudio",
        "PySide6.QtSql",
        "PySide6.QtMultimediaWidgets",
        "PySide6.QtSvg",
        "PySide6.QtVirtualKeyboard",
        "PySide6.QtWebChannel",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebSockets",
        "__main__",
    ],
    noarchive=False,
    optimize=1,
    module_collection_mode={"librosa": "py"},
)

# PyInstaller promotes Mach-O files from the self-contained OpenKeyScan data
# payload to application binaries.  That promotion both rewrites their local
# loader paths and copies a second set of Torch libraries into the parent
# Frameworks directory.  The parent process never imports Torch: OpenKeyScan
# runs as its own pre-built executable and must retain the loader paths and
# signatures of the validated payload beside that executable.  Keep every
# OpenKeyScan file as DATA and remove only the dependency copies that escaped
# to the bundle root.
_ESCAPED_OPENKEYSCAN_LIBRARIES = {
    "libc10.dylib",
    "libshm.dylib",
    "libtorch.dylib",
    "libtorch_cpu.dylib",
    "libtorch_python.dylib",
    "libtorchaudio.so",
    "libtorchaudio_sox.so",
}
_openkeyscan_promoted_entries = [
    item for item in a.binaries
    if item[0].replace("\\", "/").startswith("openkeyscan-analyzer/")
]

# Analysis removes Mach-O files from ``datas`` when it promotes them. Restore
# those entries explicitly as DATA (while preserving its symlinks) before
# removing the promoted copies, otherwise the isolated executable would be
# incomplete in the final bundle.
a.datas.extend(
    (
        destination,
        source,
        "DATA" if typecode == "BINARY" else typecode,
    )
    for destination, source, typecode in _openkeyscan_promoted_entries
)
a.binaries = [
    item for item in a.binaries
    if not item[0].replace("\\", "/").startswith("openkeyscan-analyzer/")
    and item[0].replace("\\", "/") not in _ESCAPED_OPENKEYSCAN_LIBRARIES
]

# PySide's platform hooks conservatively collect several Qt feature families
# that Stem Slicer never imports or uses. Filter both each unused plugin and
# the frameworks pulled in only by that plugin, while retaining Core/Gui/
# Widgets/Multimedia, Cocoa, the macOS style and both media backends.
_UNUSED_QT_FRAMEWORKS = {
    "QtVirtualKeyboardQml", "QtVirtualKeyboard", "QtQuick", "QtQml",
    "QtQmlModels", "QtQmlMeta", "QtQmlWorkerScript", "QtOpenGL",
    "QtPdf", "QtSvg", "QtMultimediaWidgets",
}
_UNUSED_QT_PLUGIN_PREFIXES = (
    "PySide6/Qt/plugins/platforminputcontexts/",
    "PySide6/Qt/plugins/imageformats/",
    "PySide6/Qt/plugins/iconengines/",
    "PySide6/Qt/plugins/generic/",
)
_UNUSED_QT_PLUGIN_FILES = {
    "PySide6/Qt/plugins/platforms/libqminimal.dylib",
}


def _drop_unused_qt_binary(item):
    destination = item[0].replace("\\", "/")
    if destination in _UNUSED_QT_PLUGIN_FILES or destination.startswith(_UNUSED_QT_PLUGIN_PREFIXES):
        return True
    for framework in _UNUSED_QT_FRAMEWORKS:
        if destination == framework or destination.startswith(framework + ".framework/"):
            return True
        if destination.startswith(f"PySide6/Qt/lib/{framework}.framework/"):
            return True
    return False


a.binaries = [item for item in a.binaries if not _drop_unused_qt_binary(item)]
a.datas = [
    item for item in a.datas
    if not _drop_unused_qt_binary(item)
    and not item[0].replace("\\", "/").startswith("PySide6/Qt/translations/")
]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    name="StemSlicer19B",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    argv_emulation=False,
    target_arch="arm64",
    codesign_identity=None,
    entitlements_file=None,
    exclude_binaries=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="StemSlicer19B",
)

# BUNDLE normally copies the whole COLLECT tree a second time. Prefer APFS
# clonefile copies while assembling the macOS app, which preserves identical
# standalone files without temporarily consuming another full bundle's worth
# of disk blocks. Fall back to shutil on filesystems without clone support.
_copyfile = shutil.copyfile


def _clonefile_or_copy(source, destination, *, follow_symlinks=True):
    result = subprocess.run(
        ["/bin/cp", "-c", source, destination],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode == 0:
        return destination
    return _copyfile(source, destination, follow_symlinks=follow_symlinks)


shutil.copyfile = _clonefile_or_copy
try:
    app = BUNDLE(
        coll,
        name="Stem Slicer 1.9B.app",
        icon="assets/StemSlicer.icns",
        bundle_identifier="com.antiworld.stemslicer.19b",
        info_plist={
            "CFBundleDisplayName": "Stem Slicer 1.9B",
            "CFBundleName": "Stem Slicer 1.9B",
            "CFBundleShortVersionString": "1.9.0",
            "CFBundleVersion": "1.9.0.1",
            "NSHighResolutionCapable": True,
        },
    )
finally:
    shutil.copyfile = _copyfile
