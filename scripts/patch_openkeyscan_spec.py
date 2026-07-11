import sys
from pathlib import Path


IMPORT_LINE = "from PyInstaller.utils.hooks import collect_submodules"
HIDDEN_IMPORTS_LINE = "hiddenimports = collect_submodules('scipy._external.array_api_compat') + ["


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: patch_openkeyscan_spec.py <openkeyscan_analyzer.spec>")
    path = Path(sys.argv[1])
    source = path.read_text(encoding="utf-8")
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
    path.write_text(source, encoding="utf-8")
    print("Patched OpenKeyScan spec with complete SciPy array API compatibility imports.")


if __name__ == "__main__":
    main()
