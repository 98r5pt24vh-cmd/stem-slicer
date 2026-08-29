import { existsSync, mkdirSync, mkdtempSync } from "node:fs"
import { homedir, tmpdir } from "node:os"
import path from "node:path"
import { DatabaseSync } from "node:sqlite"

import { describe, expect, it } from "vitest"

import { dismissCategoryCorrections, getSourceLoopEditor, listCategoryCorrections, saveSourceLoopEdit, setLayerCategory } from "./catalog-edits"
import { readLibraryOverview } from "./library-cache"

// These are native, disk-backed SQLite integration tests. Windows runners can
// spend several seconds in durable schema and journal writes under antivirus
// scanning, so keep a file-scoped ceiling without relaxing any assertion.
const DISK_BACKED_SQLITE_TEST_TIMEOUT_MS = 20_000

function recoverableTestRoot(): string {
  const trash = path.join(homedir(), ".Trash")
  const parent = existsSync(trash) ? trash : tmpdir()
  return mkdtempSync(path.join(parent, "stem-slicer-catalog-edit-test-"))
}

function createCatalogue(): { acceptedCache: string; libraryRoot: string; paths: string[] } {
  const acceptedCache = recoverableTestRoot()
  const generateRoot = path.join(acceptedCache, "generate")
  const libraryRoot = path.join(acceptedCache, "library")
  mkdirSync(generateRoot, { recursive: true })
  mkdirSync(libraryRoot, { recursive: true })
  const paths = [path.join(libraryRoot, "Loop_L1.mp3"), path.join(libraryRoot, "Loop_L2.mp3")]
  const database = new DatabaseSync(path.join(generateRoot, "library.sqlite3"))
  database.exec(`
    CREATE TABLE layer_cache (
      path TEXT PRIMARY KEY,
      library_root TEXT NOT NULL,
      relative_path TEXT NOT NULL,
      filename TEXT NOT NULL,
      source_loop_id TEXT NOT NULL,
      layer_index INTEGER,
      bpm INTEGER,
      key TEXT,
      mode TEXT,
      duration_seconds REAL,
      sha256 TEXT NOT NULL,
      predicted_label TEXT,
      manual_label TEXT,
      manual_origin TEXT,
      scanned_key TEXT,
      scanned_mode TEXT,
      key_confidence_status TEXT,
      updated_at_ns INTEGER NOT NULL
    )
  `)
  const insert = database.prepare(`
    INSERT INTO layer_cache (
      path, library_root, relative_path, filename, source_loop_id, layer_index,
      bpm, key, mode, duration_seconds, sha256, predicted_label,
      manual_label, manual_origin, scanned_key, scanned_mode, key_confidence_status, updated_at_ns
    ) VALUES (?, ?, ?, ?, 'loop-source', ?, 140, 'A', 'minor', 13.714, ?, ?, NULL, NULL, 'A', 'minor', 'analyzed', 1)
  `)
  insert.run(paths[0], libraryRoot, "Loop_L1.mp3", "Loop_L1.mp3", 1, "identity-1", "Lead")
  insert.run(paths[1], libraryRoot, "Loop_L2.mp3", "Loop_L2.mp3", 2, "identity-2", "Pad")
  database.close()
  return { acceptedCache, libraryRoot, paths }
}

describe("catalogue edits", () => {
  it("persists loop metadata, categories and beat-based timeline edits", () => {
    const fixture = createCatalogue()
    const initial = getSourceLoopEditor(fixture.acceptedCache, fixture.libraryRoot, "loop-source")
    expect(initial.bpm).toBe(140)
    expect(initial.keyName).toBe("A minor")
    expect(initial.layers.map((layer) => layer.category)).toEqual(["Lead", "Pad"])

    const saved = saveSourceLoopEdit(fixture.acceptedCache, {
      libraryRoot: fixture.libraryRoot,
      sourceLoopId: "loop-source",
      bpm: 150,
      keyName: "C♯ minor",
      layers: [
        { identity: "identity-1", category: "Counter", offsetBeats: 1.25, trimStartBeats: 0.5, trimEndBeats: 0.25 },
        { identity: "identity-2", category: "Pad", offsetBeats: 0, trimStartBeats: 0, trimEndBeats: 0 },
      ],
    })

    expect(saved.bpm).toBe(150)
    expect(saved.keyName).toBe("C♯ minor")
    expect(saved.layers[0]).toMatchObject({ category: "Counter", offsetBeats: 1.25, trimStartBeats: 0.5, trimEndBeats: 0.25 })

    const database = new DatabaseSync(path.join(fixture.acceptedCache, "generate", "library.sqlite3"), { readOnly: true })
    const row = database.prepare(`
      SELECT manual_bpm, manual_key, manual_mode, manual_label,
             timeline_offset_beats, trim_start_beats, trim_end_beats
      FROM layer_cache WHERE sha256 = 'identity-1'
    `).get() as unknown as Record<string, unknown>
    database.close()
    expect(row).toMatchObject({
      manual_bpm: 150,
      manual_key: "C#",
      manual_mode: "minor",
      manual_label: "Counter",
      timeline_offset_beats: 1.25,
      trim_start_beats: 0.5,
      trim_end_beats: 0.25,
    })

    const feedback = new DatabaseSync(path.join(fixture.acceptedCache, "generate", "key-feedback.sqlite3"), { readOnly: true })
    const truth = feedback.prepare("SELECT corrected_category FROM category_truth_feedback WHERE identity = 'identity-1'").get() as unknown as { corrected_category: string }
    feedback.close()
    expect(truth.corrected_category).toBe("Counter")
  }, DISK_BACKED_SQLITE_TEST_TIMEOUT_MS)

  it("saves a card category correction as a manual label", () => {
    const fixture = createCatalogue()
    const corrected = setLayerCategory(fixture.acceptedCache, {
      libraryRoot: fixture.libraryRoot,
      sourceLoopId: "loop-source",
      identity: "identity-2",
      path: fixture.paths[1],
      category: "Texture",
    })
    expect(corrected.category).toBe("Texture")
    expect(getSourceLoopEditor(fixture.acceptedCache, fixture.libraryRoot, "loop-source").layers[1].category).toBe("Texture")
    expect(listCategoryCorrections(fixture.acceptedCache)).toEqual([
      expect.objectContaining({
        identity: "identity-2",
        filename: "Loop_L2.mp3",
        previousCategory: "Pad",
        correctedCategory: "Texture",
      }),
    ])
  }, DISK_BACKED_SQLITE_TEST_TIMEOUT_MS)

  it("hides a correction from history without deleting its truth feedback", () => {
    const fixture = createCatalogue()
    setLayerCategory(fixture.acceptedCache, {
      libraryRoot: fixture.libraryRoot,
      sourceLoopId: "loop-source",
      identity: "identity-2",
      path: fixture.paths[1],
      category: "Texture",
    })

    expect(dismissCategoryCorrections(fixture.acceptedCache, ["identity-2"])).toEqual([])
    const feedback = new DatabaseSync(path.join(fixture.acceptedCache, "generate", "key-feedback.sqlite3"), { readOnly: true })
    const truth = feedback.prepare("SELECT corrected_category FROM category_truth_feedback WHERE identity = 'identity-2'").get() as unknown as { corrected_category: string }
    feedback.close()
    expect(truth.corrected_category).toBe("Texture")
  }, DISK_BACKED_SQLITE_TEST_TIMEOUT_MS)

  it("excludes only the selected layer while preserving its catalogue record", () => {
    const fixture = createCatalogue()
    getSourceLoopEditor(fixture.acceptedCache, fixture.libraryRoot, "loop-source")

    const saved = saveSourceLoopEdit(fixture.acceptedCache, {
      libraryRoot: fixture.libraryRoot,
      sourceLoopId: "loop-source",
      bpm: 140,
      keyName: "A minor",
      layers: [
        { identity: "identity-2", category: "Pad", offsetBeats: 0, trimStartBeats: 0, trimEndBeats: 0 },
      ],
      excludedIdentities: ["identity-1"],
    })

    expect(saved.layers.map((layer) => layer.identity)).toEqual(["identity-2"])
    const database = new DatabaseSync(path.join(fixture.acceptedCache, "generate", "library.sqlite3"), { readOnly: true })
    const rows = database.prepare(`
      SELECT sha256, manual_excluded
      FROM layer_cache
      ORDER BY sha256
    `).all() as unknown as Array<{ sha256: string; manual_excluded: number }>
    database.close()
    expect(rows).toEqual([
      { sha256: "identity-1", manual_excluded: 1 },
      { sha256: "identity-2", manual_excluded: 0 },
    ])
    const overview = readLibraryOverview(fixture.acceptedCache)
    expect(overview.error).toBeUndefined()
    expect(overview.totalLayers).toBe(1)
    expect(overview.roots[0]?.layerCount).toBe(1)
  }, DISK_BACKED_SQLITE_TEST_TIMEOUT_MS)
})
