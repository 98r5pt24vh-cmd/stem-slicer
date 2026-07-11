# -*- mode: python ; coding: utf-8 -*-

datas = [
    ("assets/stem-slicer-wordmark.png", "assets"),
    ("assets/antiworld-logo.png", "assets"),
    ("assets/app-icon.png", "assets"),
    ("THIRD_PARTY_NOTICES.md", "."),
    ("vendor/openkeyscan-analyzer", "openkeyscan-analyzer"),
]

binaries = [
    ("vendor/ffmpeg-bin/ffmpeg.exe", "."),
    ("vendor/ffmpeg-bin/ffprobe.exe", "."),
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
    excludes=["AppKit", "Foundation", "objc"],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    name="Stem Slicer 1.4 Qt Prototype",
    icon="assets/StemSlicer.ico",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    exclude_binaries=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Stem Slicer 1.4 Qt Prototype",
)
