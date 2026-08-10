# Clean rebuild runbook — Stem Slicer 1.9B

Read `BUILD_INVARIANTS.md` first. The canonical source is the Git repository,
not a previous release folder.

## Before either platform

1. Work from `/Users/nrgy/Documents/Stem Slicer Repository` or a clean checkout
   of the same Git revision.
2. Record `git status --short --branch` and `git rev-parse HEAD`.
3. Refuse to build from a dirty or unidentified source tree.
4. Create a new build/worktree and a brand-new virtual environment.
5. Do not import any previous `.venv`, `build`, `dist`, Release, extracted ZIP,
   `.app`, `_internal` or PyInstaller cache.
6. Verify the external trees with:

```bash
python scripts/verify_external_payloads.py --root /absolute/source/root
```

7. If the pinned offline MERT payload is missing, fetch it only with:

```bash
python scripts/fetch_mert_payload.py
```

## macOS 1.9B

Required runtime:

```text
CPython 3.12.13 arm64
PySide6 6.11.1
PyInstaller 6.18.0
```

Use an explicit CPython 3.12.13 arm64 binary and a new environment outside the
canonical repository:

```bash
/absolute/python3.12 -c "import platform,sys; assert sys.version_info[:3] == (3,12,13); assert platform.machine() == 'arm64'"
/absolute/python3.12 -m venv /absolute/new/build/venv-1.9B
/absolute/new/build/venv-1.9B/bin/python -m pip install --upgrade pip
/absolute/new/build/venv-1.9B/bin/python -m pip install -r requirements.txt
/absolute/new/build/venv-1.9B/bin/python -m pip check
/absolute/new/build/venv-1.9B/bin/python -c "import platform,sys,PySide6; assert sys.version_info[:3] == (3,12,13); assert platform.machine() == 'arm64'; assert PySide6.__version__ == '6.11.1'"
QT_QPA_PLATFORM=offscreen STEM_SLICER_DISABLE_ENGINE_AUTOSTART=1 /absolute/new/build/venv-1.9B/bin/python -m unittest discover -s tests -v
/absolute/new/build/venv-1.9B/bin/python -m PyInstaller --clean --noconfirm StemSlicer.spec
```

After packaging:

- verify the main executable and `libpython3.12.dylib` are arm64;
- verify PySide6 6.11.1 inside the bundle;
- verify no mutable `.nbi`, `.nbc`, model cache or `.DS_Store` was sealed in;
- run the UI, key/BPM, MIDI and real MERT+DSP packaged smokes;
- recursively ad-hoc sign the bundle, then run
  `codesign --verify --deep --strict --verbose=2`;
- create the archive with
  `ditto -c -k --sequesterRsrc --keepParent`;
- run `unzip -t`, extract to a new folder, repeat deep strict signature
  verification and rerun the packaged smokes.

Last accepted macOS evidence:

- artifact source revision: `5e2e790a747a5ded488f221da79c5704ba859683`;
- functional scan fix: `fc35a9c143b41ca766b0619585375e719ab9944f`;
- 313 source tests passed;
- ZIP SHA-256:
  `dfb4bf375c95509a1b865685a45fbccf6945bd094284e88b997346b7ff86919b`.

The current Git head contains later Windows dialog/removal hardening. A future
macOS release must be rebuilt cleanly from that newer recorded Git revision; do
not copy files into the accepted old `.app`.

## Windows 1.9B

Do not build Windows locally on macOS. Push the intended Git revision to the
branch consumed by `.github/workflows/build-windows.yml`, then dispatch that
workflow.

The workflow is the source of truth and performs, in order:

1. official CPython 3.12.10 x64 setup and verification;
2. exact engine/model hash validation;
3. dependency installation and `pip check`;
4. pinned offline MERT fetch/verification;
5. strict 30-second complete Quick Extract MIDI lifecycle;
6. full cross-platform tests and native Windows regressions;
7. clean OpenKeyScan analyzer build;
8. pinned static Bungee build and pinned FFmpeg download;
9. clean PyInstaller build using `StemSlicerWindows.spec`;
10. bundle audit, ZIP creation/extraction and exact extracted-payload smoke;
11. upload of `Stem-Slicer-1.9B-Windows.zip` and `smoke-test.log`.

Do not weaken the MIDI timeout, skip the native Windows regressions or package
after any failed test.

Last accepted Windows build:

- branch: `codex/windows-1.9b`;
- final tested revision: `c0340675a51229c9634f24458f295e840ccd00f7`;
- CI run: `31313639704`;
- 315 tests passed;
- clean MIDI lifecycle: 13.153 seconds;
- ZIP SHA-256:
  `b284f144de49d2654f5bdbd087279dec73b84e4cd5c36ff3cdd2517aff932ab9`.

## Final release record

For each platform, record:

- source branch and exact commit;
- Python, architecture, PySide6 and PyInstaller versions;
- payload verification, source tests and platform regressions;
- packaged runtime/engine/UI smokes;
- signature or Windows GUI/hidden-console audit;
- final ZIP filename, byte size and SHA-256;
- ZIP integrity, fresh extraction and extracted-payload smoke;
- real beta-tester status separately from automated validation.
