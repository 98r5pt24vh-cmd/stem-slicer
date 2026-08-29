import { existsSync, mkdirSync, mkdtempSync } from "node:fs"
import { homedir, tmpdir } from "node:os"
import path from "node:path"
import { DatabaseSync } from "node:sqlite"
import { describe, expect, it } from "vitest"

import {
  dismissKeyIssueReport,
  listKeyIssueReports,
  reportKeyIssue,
  setKeyIssueActive,
} from "./key-feedback"

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
      issueType: "wrong-key",
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
    expect(reported[0].issueType).toBe("wrong-key")
    expect(reported[0].active).toBe(true)
    expect(reported[0].affectedLayers.map((layer) => layer.identity)).toEqual(["hash-1", "hash-2"])

    const restored = setKeyIssueActive(acceptedCache, reported[0].id, false)
    expect(restored[0].active).toBe(false)
    expect(restored[0].resolvedAt).toBeTruthy()

    const quarantinedAgain = setKeyIssueActive(acceptedCache, reported[0].id, true)
    expect(quarantinedAgain[0].active).toBe(true)
    expect(quarantinedAgain[0].resolvedAt).toBeUndefined()

    expect(dismissKeyIssueReport(acceptedCache, reported[0].id)).toEqual([])
    const retained = new DatabaseSync(path.join(generateCache, "key-feedback.sqlite3"), { readOnly: true })
    const archived = retained.prepare("SELECT hidden_at FROM key_issue_reports WHERE id = ?").get(reported[0].id) as { hidden_at: string }
    retained.close()
    expect(archived.hidden_at).toBeTruthy()

    const visibleAgain = reportKeyIssue(acceptedCache, {
      issueType: "wrong-key",
      libraryRoot,
      sourceLoopId: "loop 140 am",
      reportedIdentity: "hash-1",
      reportedPath: firstPath,
      reportedFile: path.basename(firstPath),
      detectedKey: "A minor",
      targetKey: "F minor",
      generationOutputDirectory: path.join(acceptedCache, "generation"),
    })
    expect(visibleAgain).toHaveLength(1)
  })

  it("stores a wrong-slice quarantine separately from a wrong-key report", () => {
    const acceptedCache = recoverableTestRoot()
    const generateCache = path.join(acceptedCache, "generate")
    mkdirSync(generateCache, { recursive: true })
    const libraryRoot = path.join(acceptedCache, "library")
    const layerPath = path.join(libraryRoot, "Loop 140 Am_L1.mp3")
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
    database.prepare("INSERT INTO layer_cache VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)")
      .run("hash-slice", layerPath, path.basename(layerPath), "A", "minor", "A", "minor", libraryRoot, "loop 140 am", 1, path.basename(layerPath))
    database.close()

    const reported = reportKeyIssue(acceptedCache, {
      issueType: "wrong-slice",
      libraryRoot,
      sourceLoopId: "loop 140 am",
      reportedIdentity: "hash-slice",
      reportedPath: layerPath,
      reportedFile: path.basename(layerPath),
      detectedKey: "A minor",
      targetKey: "F minor",
      generationOutputDirectory: path.join(acceptedCache, "generation"),
    })

    expect(reported).toHaveLength(1)
    expect(reported[0].issueType).toBe("wrong-slice")
    expect(reported[0].affectedLayers.map((layer) => layer.identity)).toEqual(["hash-slice"])
  })

  it("migrates legacy key-only feedback without losing the report", () => {
    const acceptedCache = recoverableTestRoot()
    const generateCache = path.join(acceptedCache, "generate")
    mkdirSync(generateCache, { recursive: true })
    const feedback = new DatabaseSync(path.join(generateCache, "key-feedback.sqlite3"))
    feedback.exec(`
      CREATE TABLE key_issue_reports (
        id TEXT PRIMARY KEY,
        library_root TEXT NOT NULL,
        source_loop_id TEXT NOT NULL,
        reported_identity TEXT NOT NULL,
        reported_path TEXT NOT NULL,
        reported_file TEXT NOT NULL,
        detected_key TEXT NOT NULL,
        target_key TEXT NOT NULL,
        generation_output_directory TEXT NOT NULL,
        created_at TEXT NOT NULL,
        resolved_at TEXT,
        UNIQUE (library_root, source_loop_id)
      );
      INSERT INTO key_issue_reports VALUES (
        'legacy', '/library', 'loop', 'hash', '/library/layer.mp3', 'layer.mp3',
        'A minor', 'F minor', '/generation', '2026-08-28T00:00:00.000Z', NULL
      );
    `)
    feedback.close()

    const reports = listKeyIssueReports(acceptedCache)
    expect(reports).toHaveLength(1)
    expect(reports[0].id).toBe("legacy")
    expect(reports[0].issueType).toBe("wrong-key")
    expect(reports[0].active).toBe(true)
    const migrated = new DatabaseSync(path.join(generateCache, "key-feedback.sqlite3"), { readOnly: true })
    const migratedColumns = migrated.prepare("PRAGMA table_info(key_issue_reports)").all() as Array<{ name: string }>
    migrated.close()
    expect(migratedColumns.some((column) => column.name === "hidden_at")).toBe(true)
  })
})
