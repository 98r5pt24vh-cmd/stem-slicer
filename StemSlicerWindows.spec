# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


def filtered_payload(source_root, destination_root):
    """Collect immutable model files without cache metadata or Finder noise."""
    source_root = Path(source_root)
    items = []
    for source in source_root.rglob("*"):
        if not source.is_file() or source.name == ".DS_Store":
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

# Generate classifies unknown layers fully offline.  The CI fetch step creates
# this exact deterministic snapshot and trusted-code module layout before
# PyInstaller runs.
datas += filtered_payload(
    "models/huggingface/models--m-a-p--MERT-v1-95M",
    "models/huggingface/models--m-a-p--MERT-v1-95M",
)
datas += filtered_payload(
    "models/huggingface/modules",
    "models/huggingface/modules",
)

binaries = [
    ("vendor-windows/ffmpeg-bin/ffmpeg.exe", "."),
    ("bin/bungee.exe", "bin"),
]

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        "midi_conversion",
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
    ],
    noarchive=False,
    optimize=1,
    module_collection_mode={"librosa": "py"},
)

# PySide's hooks collect feature families that this Widgets + Multimedia app
# never imports. Keep the Windows platform plugin, multimedia backend and
# opengl32sw.dll, but remove the unused Qt modules and translations.
_UNUSED_QT_DLLS = {
    "qt6multimediawidgets.dll",
    "qt6opengl.dll",
    "qt6pdf.dll",
    "qt6qml.dll",
    "qt6qmlmeta.dll",
    "qt6qmlmodels.dll",
    "qt6qmlworkerscript.dll",
    "qt6quick.dll",
    "qt6svg.dll",
    "qt6virtualkeyboard.dll",
}
_UNUSED_QT_PREFIXES = (
    "pyside6/translations/",
    "pyside6/qt/translations/",
    "pyside6/plugins/generic/",
    "pyside6/plugins/platforminputcontexts/",
)


def _drop_unused_qt_item(item):
    destination = item[0].replace("\\", "/").lower()
    filename = destination.rsplit("/", 1)[-1]
    return filename in _UNUSED_QT_DLLS or destination.startswith(_UNUSED_QT_PREFIXES)


a.binaries = [item for item in a.binaries if not _drop_unused_qt_item(item)]
a.datas = [item for item in a.datas if not _drop_unused_qt_item(item)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    name="Stem Slicer 1.9B",
    icon="assets/StemSlicer.ico",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    # Keep Windows Explorer and Stem Slicer at the same integrity level so
    # native file/folder drops are not blocked by UIPI.
    uac_admin=False,
    uac_uiaccess=False,
    exclude_binaries=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Stem Slicer 1.9B",
)
