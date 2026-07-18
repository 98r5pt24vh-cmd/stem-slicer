# -*- mode: python ; coding: utf-8 -*-

import sys
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# Read target architecture from environment variable (set by build script)
# This ensures PyInstaller validates that the terminal arch matches the target
target_arch = os.environ.get('TARGET_ARCH', None)  # 'arm64', 'x86_64', or None (auto-detect)

# Determine the base path
base_path = Path.cwd()

# Data files to bundle
datas = [
    (str(base_path / 'checkpoints' / 'openkeyscan3.pt'), 'checkpoints'),
    (str(base_path / 'checkpoints' / 'deeprhythm-0.7.pth'), 'checkpoints'),
    # Bundle ffmpeg binaries for fast MP3/M4A/AAC decoding (fixes 25x slowdown)
    # The ffmpeg.exe (4.3MB) is a minimal audio-only build
]
datas += collect_data_files('librosa', include_py_files=True)

# Add ffmpeg binaries if they exist (platform-specific)
ffmpeg_windows = base_path / 'ffmpeg.exe'
ffmpeg_unix = base_path / 'ffmpeg'
if sys.platform == 'win32' and ffmpeg_windows.exists():
    datas.append((str(ffmpeg_windows), '.'))
if sys.platform != 'win32' and ffmpeg_unix.exists():
    datas.append((str(ffmpeg_unix), '.'))

# Hidden imports that PyInstaller might miss
hiddenimports = collect_submodules('scipy._external.array_api_compat') + [
    'librosa',
    'numba',
    'soundfile',
    'cffi',
    'av',  # PyAV for optimized audio loading
    'deeprhythm',
    'deeprhythm.audio_proc.hcqm',
    'deeprhythm.model.frame_cnn',
    'deeprhythm.model.predictor',
    'nnAudio',
    'nnAudio.Spectrogram',
    # Comprehensive scipy imports to prevent lazy loading issues
    'scipy._lib',
    'scipy._lib.messagestream',
    'scipy.special',
    'scipy.special._cdflib',
    'scipy.special._ufuncs',
    'scipy.special._ufuncs_cxx',
    'scipy.signal',
    'scipy.signal.windows',
    'scipy.signal._peak_finding',
    'scipy.fft',
    'scipy.fftpack',
    'scipy.linalg',
    'scipy.linalg.blas',
    'scipy.linalg.lapack',
]

# Runtime hooks to fix scipy initialization
runtime_hooks = []

a = Analysis(
    ['openkeyscan_analyzer_server.py'],
    pathex=[str(base_path)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=runtime_hooks,
    # Basic Pitch owns the application's only ONNX Runtime. This analyzer uses
    # Torch for both OpenKeyScan and DeepRhythm, so collecting onnxruntime here
    # would add an unused duplicate to the nested payload.
    excludes=['onnxruntime', 'google'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe_server = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='openkeyscan-analyzer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=target_arch,  # Set from environment variable (arm64, x86_64, or None)
    python_options=['X utf8_mode=1'],  # Force UTF-8 mode for proper Unicode handling on Windows
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe_server,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='openkeyscan-analyzer',
)
