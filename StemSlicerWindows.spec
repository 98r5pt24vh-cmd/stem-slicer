# -*- mode: python ; coding: utf-8 -*-

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
]

binaries = [
    ("vendor-windows/ffmpeg-bin/ffmpeg.exe", "."),
    ("bin/bungee.exe", "bin"),
]

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=["midi_conversion", "basic_pitch", "basic_pitch.inference", "pretty_midi", "onnxruntime"],
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
        "torch",
        "torchaudio",
        "torchvision",
        "matplotlib",
        "pandas",
        "sklearn",
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
    name="Stem Slicer 1.8.2B",
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
    name="Stem Slicer 1.8.2B",
)
