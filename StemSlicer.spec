# -*- mode: python ; coding: utf-8 -*-

import shutil
import subprocess

datas = [
    ("assets/stem-slicer-wordmark.png", "assets"),
    ("assets/antiworld-logo.png", "assets"),
    ("assets/app-icon.png", "assets"),
    ("assets/midi-logo-mask.png", "assets"),
    ("assets/key-engine-warmup.wav", "assets"),
    ("basic_pitch/saved_models/icassp_2022/nmp.onnx", "basic_pitch/saved_models/icassp_2022"),
    ("licenses/basic-pitch", "licenses/basic-pitch"),
    ("THIRD_PARTY_NOTICES.md", "."),
]

binaries = [
    ("vendor/ffmpeg-bin/ffmpeg", "."),
]

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=["basic_pitch", "basic_pitch.inference", "pretty_midi", "onnxruntime"],
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
        "__main__",
    ],
    noarchive=False,
    optimize=1,
)

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
    name="StemSlicer15SBeta",
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
    name="StemSlicer15SBeta",
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
        name="Stem Slicer 1.5S Beta.app",
        icon="assets/StemSlicer.icns",
        bundle_identifier="com.antiworld.stemslicer.15sbeta",
        info_plist={
            "CFBundleDisplayName": "Stem Slicer 1.5S Beta",
            "CFBundleName": "Stem Slicer 1.5S Beta",
            "CFBundleShortVersionString": "1.5.1",
            "CFBundleVersion": "1.5.1",
            "NSHighResolutionCapable": True,
        },
    )
finally:
    shutil.copyfile = _copyfile
