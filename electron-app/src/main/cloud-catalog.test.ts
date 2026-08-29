import { mkdtempSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"
import { DatabaseSync } from "node:sqlite"
import { describe, expect, it } from "vitest"

import { audioMimeType, cloudCachePath, readLocalCloudManifest, safeObjectFileName } from "./cloud-catalog"

describe("cloud catalogue helpers", () => {
  it("normalizes storage object names without losing the audio extension", () => {
    expect(safeObjectFileName("D♯ héro layer 01.MP3")).toBe("D- he-ro layer 01.mp3")
  })

  it("uses a deterministic isolated cache path", () => {
    expect(cloudCachePath("/cache", "owner", "library", "abc123", "Layer.wav"))
      .toBe(path.join("/cache", "owner", "library", "abc123.wav"))
  })

  it("maps the supported alpha audio formats", () => {
    expect(audioMimeType("layer.mp3")).toBe("audio/mpeg")
    expect(audioMimeType("layer.flac")).toBe("audio/flac")
    expect(audioMimeType("layer.unknown")).toBe("application/octet-stream")
  })

  it("publishes a legacy indexed catalogue before editor columns have been created", () => {
    const root = mkdtempSync(path.join(tmpdir(), "slicer-cloud-catalog-"))
    const databasePath = path.join(root, "library.sqlite3")
    const audioPath = path.join(root, "LOOP 140 XT_L1.mp3")
    writeFileSync(audioPath, "audio")
    const database = new DatabaseSync(databasePath)
    database.exec(`
      CREATE TABLE layer_cache (
        path TEXT, library_root TEXT, relative_path TEXT, filename TEXT,
        source_loop_id TEXT, layer_index INTEGER, bpm INTEGER, key TEXT, mode TEXT,
        duration_seconds REAL, byte_size INTEGER, sha256 TEXT,
        predicted_label TEXT, prediction_confidence REAL, manual_label TEXT,
        scanned_key TEXT, scanned_mode TEXT, key_confidence_margin REAL,
        key_confidence_status TEXT, key_analyzer_id TEXT,
        alternate_scanned_key TEXT, alternate_scanned_mode TEXT,
        key_top1_probability REAL, key_top2_probability REAL
      )
    `)
    database.prepare(`
      INSERT INTO layer_cache VALUES (
        ?, ?, ?, ?, 'source-loop', 1, 140, 'F', 'minor', 13.7, 5, 'abc123',
        'Bass', 0.99, NULL, 'F', 'minor', 0.8, 'safe', 'test',
        NULL, NULL, 0.9, 0.1
      )
    `).run(audioPath, root, path.basename(audioPath), path.basename(audioPath))
    database.close()

    const manifest = readLocalCloudManifest(databasePath, root, "XT")

    expect(manifest.layers).toHaveLength(1)
    expect(manifest.layers[0].metadata).toMatchObject({
      manual_bpm: null,
      manual_key: null,
      manual_mode: null,
      timeline_offset_beats: 0,
      trim_start_beats: 0,
      trim_end_beats: 0,
      producers: ["XT"],
    })
  })
})
