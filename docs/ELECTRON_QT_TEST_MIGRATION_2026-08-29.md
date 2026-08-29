# Electron migration of the retired Qt test surface

This repository is the clean Electron line. The accepted PySide6 1.9B source
and its historical tests remain preserved in the separate canonical 1.9B
repository. Electron validation must not import PySide6.

## Retired implementation-only Qt tests

These tests exercised widgets and controllers that Electron does not load:

- `test_cards_as_slots_ui.py`
- `test_generate_19_compact_ui.py`
- `test_generate_prototype_ui.py`
- `test_qt_interface.py`

Their product behavior is now owned by the React renderer, the headless engine
tests, and packaged Electron UI verification. Qt pixel geometry, proxy widgets,
signals and `QApplication` behavior are not valid Electron contracts.

## Protections transferred before retirement

| Retired Qt-bound test | Electron/headless replacement |
| --- | --- |
| `test_generate_midi_bridge.py`, `test_midi_engine_service.py` | `electron-app/python/test_engine_bridge_workflows.py` verifies ordered MIDI production, converter reuse through the persistent bridge, and per-layer failure isolation. |
| `test_workflow.py` | `electron-app/python/test_engine_bridge_workflows.py` verifies batch validation, one analysis per source, Quick Extract ordering and target-mode behavior. |
| `test_runtime_truth_isolation.py` | `tests/test_layer_library.py` verifies stale training truth removal; the bridge test verifies that library scans never activate truth CSV environment variables. |
| `test_storage.py` | `electron-app/src/main/activity-history.test.ts`, `electron-app/src/lib/utils.test.ts` and bridge workflow tests cover filesystem boundaries, decimal units, portable names and collisions. |
| `test_generation_history_ui.py`, `test_generator_history_controller.py` | Electron activity-history boundary tests plus generation-policy and bridge tests protect path isolation, generation state and locked selections. |
| `test_synchronized_layer_player.py` | `electron-app/src/renderer/shared-web-audio-engine.test.ts` verifies the shared clock, synchronized duration, seek behavior and atomic graph replacement. |
| Native Browse ownership inside `test_qt_interface.py` | `electron-app/src/main/native-dialog.test.ts` verifies that every native dialog is parented to the requesting Electron window. |

## Validation contract

`pnpm run validate` is the canonical local command. It uses the repository's
own `electron-app/.runtime/python` and fails before testing if Torch,
Joblib or SoundFile are unavailable. It runs TypeScript checks, Vitest, all
headless Python engine tests and the persistent Electron bridge tests.

The development engine source is the parent of `electron-app` in this
same worktree. It no longer silently imports Python modules from another local
repository.
