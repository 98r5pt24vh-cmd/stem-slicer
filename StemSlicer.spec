# -*- mode: python ; coding: utf-8 -*-

datas = [
    ("assets/stem-slicer-wordmark.png", "assets"),
    ("assets/antiworld-logo.png", "assets"),
    ("assets/app-icon.png", "assets"),
    ("assets/key-engine-warmup.wav", "assets"),
    ("THIRD_PARTY_NOTICES.md", "."),
]

binaries = [
    ("../../04_Applications_Mac/Stem Slicer 1.4 Qt Prototype.app/Contents/Frameworks/ffmpeg", "."),
    ("../../04_Applications_Mac/Stem Slicer 1.4 Qt Prototype.app/Contents/Frameworks/ffprobe", "."),
]

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "AppKit",
        "Foundation",
        "objc",
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
        "PySide6.QtWebChannel",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebSockets",
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    name="StemSlicer141MPackagingTest",
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
    name="StemSlicer141MPackagingTest",
)

app = BUNDLE(
    coll,
    name="Stem Slicer 1.4.1 M - Packaging Test.app",
    icon="assets/StemSlicer.icns",
    bundle_identifier="com.antiworld.stemslicer.141m.packagingtest",
    info_plist={
        "CFBundleDisplayName": "Stem Slicer",
        "CFBundleName": "Stem Slicer",
        "CFBundleShortVersionString": "1.4.1",
        "CFBundleVersion": "1.4.1",
        "NSHighResolutionCapable": True,
    },
)
