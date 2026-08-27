import { existsSync, mkdirSync, mkdtempSync } from "node:fs"
import { homedir, tmpdir } from "node:os"
import path from "node:path"
import { DatabaseSync } from "node:sqlite"
import { describe, expect, it } from "vitest"

import { dismissKeyIssueReport, reportKeyIssue, setKeyIssueActive } from "./key-feedback"

function recoverableTestRoot(): string {
  const trash = path.join(homedir(), ".Trash")
  const parent = existsSync(trash) ? trash : tmpdir()
  return mkdtempSync(path.join(parent, "stem-slicer-key-feedback-test-"))
}

describe("key issue feedback", () => {
  it("quarantines and restores every layer attached to the source loop", () => {
    const acceptedCache = recoverableTestRoot()
    const generateCache = path.join(acceptedCache, "generate")
    mkdirSync(generateCache, { recursive: true })
    const libraryRoot = path.join(acceptedCache, "library")
    const firstPath = path.join(libraryRoot, "Loop 140 Am_L1.mp3")
    const secondPath = path.join(libraryRoot, "Loop 140 Am_L2.mp3")
    const database = new DatabaseSync(path.join(generateCache, "library.sqlite3"))
    database.exec(`
      CREATE TABLE layer_cache (
        sha256 TEXT NOT NULL,
        path TEXT NOT NULL,
        filename TEXT NOT NULL,
        scanned_key TEXT,
        scanned_mode TEXT,
        key TEXT,
        mode TEXT,
        library_root TEXT NOT NULL,
        source_loop_id TEXT NOT NULL,
        layer_index INTEGER,
        relative_path TEXT NOT NULL
      )
    `)
    const insert = database.prepare(`
      INSERT INTO layer_cache VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `)
    insert.run("hash-1", firstPath, path.basename(firstPath), "A", "minor", "A", "minor", libraryRoot, "loop 140 am", 1, path.basename(firstPath))
    insert.run("hash-2", secondPath, path.basename(secondPath), "A", "minor", "A", "minor", libraryRoot, "loop 140 am", 2, path.basename(secondPath))
    database.close()

    const reported = reportKeyIssue(acceptedCache, {
      libraryRoot,
      sourceLoopId: "loop 140 am",
      reportedIdentity: "hash-1",
      reportedPath: firstPath,
      reportedFile: path.basename(firstPath),
      detectedKey: "A minor",
      targetKey: "F minor",
      generationOutputDirectory: path.join(acceptedCache, "generation"),
    })

    expect(reported).toHaveLength(1)
    expect(reported[0].active).toBe(true)
    expect(reported[0].affectedLayers.map((layer) => layer.identity)).toEqual(["hash-1", "hash-2"])

    const restored = setKeyIssueActive(acceptedCache, reported[0].id, false)
    expect(restored[0].active).toBe(false)
    expect(restored[0].resolvedAt).toBeTruthy()

    const quarantinedAgain = setKeyIssueActive(acceptedCache, reported[0].id, true)
    expect(quarantinedAgain[0].active).toBe(true)
    expect(quarantinedAgain[0].resolvedAt).toBeUndefined()

    expect(dismissKeyIssueReport(acceptedCache, reported[0].id)).toEqual([])
  })
})
