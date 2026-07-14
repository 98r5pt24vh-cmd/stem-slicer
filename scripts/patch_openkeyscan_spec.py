import sys
from pathlib import Path


IMPORT_LINE = "from PyInstaller.utils.hooks import collect_submodules"
HIDDEN_IMPORTS_LINE = "hiddenimports = collect_submodules('scipy._external.array_api_compat') + ["
WINDOWS_FFMPEG_LINE = "if sys.platform == 'win32' and ffmpeg_windows.exists():"
UNIX_FFMPEG_LINE = "if sys.platform != 'win32' and ffmpeg_unix.exists():"


def patch_spec_source(source):
    if IMPORT_LINE not in source:
        marker = "from pathlib import Path"
        if marker not in source:
            raise RuntimeError("OpenKeyScan spec import marker was not found.")
        source = source.replace(marker, f"{marker}\n{IMPORT_LINE}", 1)
    if HIDDEN_IMPORTS_LINE not in source:
        marker = "hiddenimports = ["
        if marker not in source:
            raise RuntimeError("OpenKeyScan hiddenimports marker was not found.")
        source = source.replace(marker, HIDDEN_IMPORTS_LINE, 1)

    windows_marker = "if ffmpeg_windows.exists():"
    if WINDOWS_FFMPEG_LINE not in source:
        if windows_marker not in source:
            raise RuntimeError("OpenKeyScan Windows FFmpeg marker was not found.")
        source = source.replace(windows_marker, WINDOWS_FFMPEG_LINE, 1)
    unix_marker = "if ffmpeg_unix.exists():"
    if UNIX_FFMPEG_LINE not in source:
        if unix_marker not in source:
            raise RuntimeError("OpenKeyScan Unix FFmpeg marker was not found.")
        source = source.replace(unix_marker, UNIX_FFMPEG_LINE, 1)
    return source


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: patch_openkeyscan_spec.py <openkeyscan_analyzer.spec>")
    path = Path(sys.argv[1])
    source = patch_spec_source(path.read_text(encoding="utf-8"))
    path.write_text(source, encoding="utf-8")
    print("Patched OpenKeyScan spec for SciPy imports and platform-specific FFmpeg collection.")


if __name__ == "__main__":
    main()
