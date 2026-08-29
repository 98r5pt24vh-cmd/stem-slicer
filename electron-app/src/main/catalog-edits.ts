import path from "node:path"
import { existsSync, mkdirSync } from "node:fs"
import { DatabaseSync } from "node:sqlite"

import type {
  CategoryCorrection,
  SaveSourceLoopEditRequest,
  SetLayerCategoryRequest,
  SourceLoopEditorData,
  SourceLoopEditorLayer,
} from "../shared/contracts"

interface CategoryFeedbackRow {
  identity: string
  library_root: string
  source_loop_id: string
  path: string
  filename: string
  previous_category: string | null
  corrected_category: string
  validated_at: string
}

const CATEGORIES = new Set([
  "Bass",
  "Chords",
  "Counter",
  "Keys",
  "Piano",
  "Lead",
  "Pad",
  "Pluck",
  "Vocal Chop",
  "Bells",
  "Strings",
  "Texture",
  "Guitar Lead",
  "Guitar Chords",
  "Vocal",
  "Arp",
  "Brass",
  "Synth",
])

interface LayerRow {
  identity: string
  path: string
  filename: string
  layer_index: number | null
  bpm: number | null
  manual_bpm: number | null
  key: string | null
  mode: string | null
  scanned_key: string | null
  scanned_mode: string | null
  manual_key: string | null
  manual_mode: string | null
  category: string
  duration_seconds: number | null
  timeline_offset_beats: number
  trim_start_beats: number
  trim_end_beats: number
}

function libraryDatabasePath(acceptedCachePath: string): string {
  return path.join(acceptedCachePath, "generate", "library.sqlite3")
}

function feedbackDatabasePath(acceptedCachePath: string): string {
  return path.join(acceptedCachePath, "generate", "key-feedback.sqlite3")
}

function normalizedText(value: unknown, label: string): string {
  const text = typeof value === "string" ? value.trim() : ""
  if (!text) throw new Error(`${label} is required.`)
  return text
}

function normalizedAbsolutePath(value: unknown, label: string): string {
  const text = normalizedText(value, label)
  if (!path.isAbsolute(text)) throw new Error(`${label} must be an absolute path.`)
  return path.resolve(text)
}

function normalizedCategory(value: unknown): string {
  const category = normalizedText(value, "Layer category")
  const canonical = [...CATEGORIES].find((candidate) => candidate.toLowerCase() === category.toLowerCase())
  if (!canonical) throw new Error(`Unknown layer category: ${category}`)
  return canonical
}

function normalizedBpm(value: unknown): number {
  const bpm = Number(value)
  if (!Number.isFinite(bpm) || bpm < 40 || bpm > 300) {
    throw new Error("Loop BPM must be between 40 and 300.")
  }
  return Math.round(bpm)
}

function normalizedBeatValue(value: unknown, label: string): number {
  const beats = Number(value)
  if (!Number.isFinite(beats) || beats < 0 || beats > 64) {
    throw new Error(`${label} must be between 0 and 64 beats.`)
  }
  return Math.round(beats * 4) / 4
}

function parseKeyName(value: unknown): { tonic: string; mode: "major" | "minor"; keyName: string } {
  const normalized = normalizedText(value, "Loop key")
    .replaceAll("♯", "#")
    .replaceAll("♭", "b")
  const match = /^([A-G](?:#|b)?)\s+(major|minor)$/i.exec(normalized)
  if (!match) throw new Error("Choose an exact major or minor key.")
  const tonic = `${match[1][0].toUpperCase()}${match[1].slice(1)}`
  const mode = match[2].toLowerCase() as "major" | "minor"
  return { tonic, mode, keyName: `${tonic.replace("#", "♯").replace("b", "♭")} ${mode}` }
}

function ensureEditorColumns(database: DatabaseSync): void {
  const columns = new Set(
    (database.prepare("PRAGMA table_info(layer_cache)").all() as unknown as Array<{ name: string }>)
      .map((column) => column.name),
  )
  const additions: Array<[string, string]> = [
    ["manual_bpm", "INTEGER"],
    ["manual_key", "TEXT"],
    ["manual_mode", "TEXT"],
    ["manual_excluded", "INTEGER NOT NULL DEFAULT 0"],
    ["timeline_offset_beats", "REAL NOT NULL DEFAULT 0"],
    ["trim_start_beats", "REAL NOT NULL DEFAULT 0"],
    ["trim_end_beats", "REAL NOT NULL DEFAULT 0"],
  ]
  const missing = additions.filter(([name]) => !columns.has(name))
  if (missing.length === 0) return

  // A fresh editor upgrade can add several columns. Keep those schema writes
  // in one transaction so Windows performs one durable commit instead of one
  // disk flush per ALTER TABLE.
  database.exec("BEGIN IMMEDIATE")
  try {
    for (const [name, definition] of missing) {
      database.exec(`ALTER TABLE layer_cache ADD COLUMN ${name} ${definition}`)
    }
    database.exec("COMMIT")
  } catch (error) {
    database.exec("ROLLBACK")
    throw error
  }
}

function ensureTruthFeedbackSchema(database: DatabaseSync): void {
  database.exec(`
    CREATE TABLE IF NOT EXISTS category_truth_feedback (
      identity TEXT PRIMARY KEY,
      library_root TEXT NOT NULL,
      source_loop_id TEXT NOT NULL,
      path TEXT NOT NULL,
      filename TEXT NOT NULL,
      previous_category TEXT,
      corrected_category TEXT NOT NULL,
      validated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS category_correction_history_hidden (
      identity TEXT PRIMARY KEY,
      hidden_at TEXT NOT NULL
    )
  `)
}

function editorRows(database: DatabaseSync, libraryRoot: string, sourceLoopId: string): LayerRow[] {
  return database.prepare(`
    SELECT
      sha256 AS identity,
      path,
      filename,
      layer_index,
      bpm,
      manual_bpm,
      key,
      mode,
      scanned_key,
      scanned_mode,
      manual_key,
      manual_mode,
      COALESCE(NULLIF(manual_label, ''), NULLIF(predicted_label, ''), 'Unassigned') AS category,
      duration_seconds,
      COALESCE(timeline_offset_beats, 0) AS timeline_offset_beats,
      COALESCE(trim_start_beats, 0) AS trim_start_beats,
      COALESCE(trim_end_beats, 0) AS trim_end_beats
    FROM layer_cache
    WHERE library_root = ? AND source_loop_id = ?
      AND COALESCE(manual_excluded, 0) = 0
    ORDER BY COALESCE(layer_index, 2147483647), relative_path
  `).all(libraryRoot, sourceLoopId) as unknown as LayerRow[]
}

function rowToLayer(row: LayerRow): SourceLoopEditorLayer {
  return {
    identity: row.identity,
    path: row.path,
    file: row.filename,
    layerIndex: row.layer_index ?? undefined,
    category: row.category,
    duration: Math.max(0, Number(row.duration_seconds) || 0),
    offsetBeats: Number(row.timeline_offset_beats) || 0,
    trimStartBeats: Number(row.trim_start_beats) || 0,
    trimEndBeats: Number(row.trim_end_beats) || 0,
  }
}

function rowsToEditorData(libraryRoot: string, sourceLoopId: string, rows: LayerRow[]): SourceLoopEditorData {
  if (rows.length === 0) throw new Error("No indexed layer belongs to this source loop.")
  const reference = rows[0]
  const bpm = Number(reference.manual_bpm ?? reference.bpm) || 140
  const tonic = reference.manual_key || reference.scanned_key || reference.key || "A"
  const mode = reference.manual_mode || reference.scanned_mode || reference.mode || "minor"
  return {
    libraryRoot,
    sourceLoopId,
    bpm,
    keyName: `${tonic.replace("#", "♯").replace("b", "♭")} ${mode}`,
    layers: rows.map(rowToLayer),
  }
}

function openLibraryDatabase(acceptedCachePath: string): DatabaseSync {
  const databasePath = libraryDatabasePath(acceptedCachePath)
  if (!existsSync(databasePath)) throw new Error("The Generate catalogue is unavailable.")
  const database = new DatabaseSync(databasePath)
  ensureEditorColumns(database)
  return database
}

function recordCategoryTruth(
  acceptedCachePath: string,
  row: LayerRow,
  libraryRoot: string,
  sourceLoopId: string,
  correctedCategory: string,
): void {
  const feedbackPath = feedbackDatabasePath(acceptedCachePath)
  mkdirSync(path.dirname(feedbackPath), { recursive: true })
  const database = new DatabaseSync(feedbackPath)
  try {
    ensureTruthFeedbackSchema(database)
    database.prepare(`
      INSERT INTO category_truth_feedback (
        identity, library_root, source_loop_id, path, filename,
        previous_category, corrected_category, validated_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT (identity) DO UPDATE SET
        library_root = excluded.library_root,
        source_loop_id = excluded.source_loop_id,
        path = excluded.path,
        filename = excluded.filename,
        corrected_category = excluded.corrected_category,
        validated_at = excluded.validated_at
    `).run(
      row.identity,
      libraryRoot,
      sourceLoopId,
      row.path,
      row.filename,
      row.category,
      correctedCategory,
      new Date().toISOString(),
    )
    database.prepare("DELETE FROM category_correction_history_hidden WHERE identity = ?").run(row.identity)
  } finally {
    database.close()
  }
}

export function listCategoryCorrections(acceptedCachePath: string): CategoryCorrection[] {
  const feedbackPath = feedbackDatabasePath(acceptedCachePath)
  mkdirSync(path.dirname(feedbackPath), { recursive: true })
  const database = new DatabaseSync(feedbackPath)
  try {
    ensureTruthFeedbackSchema(database)
    const rows = database.prepare(`
      SELECT feedback.*
      FROM category_truth_feedback AS feedback
      LEFT JOIN category_correction_history_hidden AS hidden
        ON hidden.identity = feedback.identity
      WHERE hidden.identity IS NULL
      ORDER BY validated_at DESC
    `).all() as unknown as CategoryFeedbackRow[]
    return rows.map((row) => ({
      identity: row.identity,
      libraryRoot: row.library_root,
      sourceLoopId: row.source_loop_id,
      path: row.path,
      filename: row.filename,
      previousCategory: row.previous_category ?? undefined,
      correctedCategory: row.corrected_category,
      validatedAt: row.validated_at,
    }))
  } finally {
    database.close()
  }
}

export function dismissCategoryCorrections(
  acceptedCachePath: string,
  requestedIdentities: unknown,
): CategoryCorrection[] {
  if (!Array.isArray(requestedIdentities) || requestedIdentities.length === 0) {
    throw new Error("Choose at least one category correction to remove from history.")
  }
  const identities = [...new Set(requestedIdentities.map((identity) => normalizedText(identity, "Category correction identity")))]
  const feedbackPath = feedbackDatabasePath(acceptedCachePath)
  mkdirSync(path.dirname(feedbackPath), { recursive: true })
  const database = new DatabaseSync(feedbackPath)
  try {
    ensureTruthFeedbackSchema(database)
    const hide = database.prepare(`
      INSERT INTO category_correction_history_hidden (identity, hidden_at)
      VALUES (?, ?)
      ON CONFLICT (identity) DO UPDATE SET hidden_at = excluded.hidden_at
    `)
    const hiddenAt = new Date().toISOString()
    database.exec("BEGIN IMMEDIATE")
    try {
      for (const identity of identities) hide.run(identity, hiddenAt)
      database.exec("COMMIT")
    } catch (error) {
      database.exec("ROLLBACK")
      throw error
    }
  } finally {
    database.close()
  }
  return listCategoryCorrections(acceptedCachePath)
}

export function getSourceLoopEditor(
  acceptedCachePath: string,
  requestedLibraryRoot: unknown,
  requestedSourceLoopId: unknown,
): SourceLoopEditorData {
  const libraryRoot = normalizedAbsolutePath(requestedLibraryRoot, "Library root")
  const sourceLoopId = normalizedText(requestedSourceLoopId, "Source loop id")
  const database = openLibraryDatabase(acceptedCachePath)
  try {
    return rowsToEditorData(libraryRoot, sourceLoopId, editorRows(database, libraryRoot, sourceLoopId))
  } finally {
    database.close()
  }
}

export function saveSourceLoopEdit(
  acceptedCachePath: string,
  request: SaveSourceLoopEditRequest,
): SourceLoopEditorData {
  const libraryRoot = normalizedAbsolutePath(request.libraryRoot, "Library root")
  const sourceLoopId = normalizedText(request.sourceLoopId, "Source loop id")
  const bpm = normalizedBpm(request.bpm)
  const key = parseKeyName(request.keyName)
  if (request.excludedIdentities !== undefined && !Array.isArray(request.excludedIdentities)) {
    throw new Error("Excluded layers must be a list.")
  }
  const excludedIdentities = new Set(
    (request.excludedIdentities ?? []).map((identity) => normalizedText(identity, "Excluded layer identity")),
  )
  if (!Array.isArray(request.layers) || request.layers.length === 0) {
    throw new Error("Keep at least one layer in the source loop.")
  }

  const database = openLibraryDatabase(acceptedCachePath)
  const truthUpdates: Array<{ row: LayerRow; category: string }> = []
  try {
    const rows = editorRows(database, libraryRoot, sourceLoopId)
    const rowsByIdentity = new Map(rows.map((row) => [row.identity, row]))
    const editedIdentities = new Set(request.layers.map((edit) => normalizedText(edit.identity, "Layer identity")))
    if (
      rows.length !== editedIdentities.size + excludedIdentities.size
      || [...editedIdentities].some((identity) => excludedIdentities.has(identity))
      || [...rowsByIdentity.keys()].some((identity) => !editedIdentities.has(identity) && !excludedIdentities.has(identity))
    ) {
      throw new Error("The source loop changed while it was being edited. Reopen the editor and try again.")
    }

    database.exec("BEGIN IMMEDIATE")
    try {
      const updatedAt = Date.now() * 1_000_000
      database.prepare(`
        UPDATE layer_cache
        SET manual_bpm = ?, manual_key = ?, manual_mode = ?, updated_at_ns = ?
        WHERE library_root = ? AND source_loop_id = ?
      `).run(bpm, key.tonic, key.mode, updatedAt, libraryRoot, sourceLoopId)

      const updateLayer = database.prepare(`
        UPDATE layer_cache
        SET manual_label = ?, manual_origin = 'user',
            timeline_offset_beats = ?, trim_start_beats = ?, trim_end_beats = ?,
            updated_at_ns = ?
        WHERE library_root = ? AND source_loop_id = ? AND sha256 = ?
      `)
      for (const edit of request.layers) {
        const identity = normalizedText(edit.identity, "Layer identity")
        const row = rowsByIdentity.get(identity)
        if (!row) throw new Error("One edited layer no longer belongs to this source loop.")
        const category = normalizedCategory(edit.category)
        const offsetBeats = normalizedBeatValue(edit.offsetBeats, "Layer start")
        const trimStartBeats = normalizedBeatValue(edit.trimStartBeats, "Trim in")
        const trimEndBeats = normalizedBeatValue(edit.trimEndBeats, "Trim out")
        const availableBeats = row.duration_seconds && bpm > 0
          ? row.duration_seconds * bpm / 60
          : 32
        if (trimStartBeats + trimEndBeats >= availableBeats) {
          throw new Error(`${row.filename}: trim points would remove the complete layer.`)
        }
        const result = updateLayer.run(
          category,
          offsetBeats,
          trimStartBeats,
          trimEndBeats,
          updatedAt,
          libraryRoot,
          sourceLoopId,
          identity,
        )
        if (Number(result.changes) !== 1) throw new Error(`Unable to update ${row.filename}.`)
        if (category !== row.category) truthUpdates.push({ row, category })
      }

      const excludeLayer = database.prepare(`
        UPDATE layer_cache
        SET manual_excluded = 1, updated_at_ns = ?
        WHERE library_root = ? AND source_loop_id = ? AND sha256 = ?
          AND COALESCE(manual_excluded, 0) = 0
      `)
      for (const identity of excludedIdentities) {
        const row = rowsByIdentity.get(identity)
        if (!row) throw new Error("One excluded layer no longer belongs to this source loop.")
        const result = excludeLayer.run(updatedAt, libraryRoot, sourceLoopId, identity)
        if (Number(result.changes) !== 1) throw new Error(`Unable to exclude ${row.filename}.`)
      }
      database.exec("COMMIT")
    } catch (error) {
      database.exec("ROLLBACK")
      throw error
    }

    for (const update of truthUpdates) {
      recordCategoryTruth(acceptedCachePath, update.row, libraryRoot, sourceLoopId, update.category)
    }
    return rowsToEditorData(libraryRoot, sourceLoopId, editorRows(database, libraryRoot, sourceLoopId))
  } finally {
    database.close()
  }
}

export function setLayerCategory(
  acceptedCachePath: string,
  request: SetLayerCategoryRequest,
): SourceLoopEditorLayer {
  const libraryRoot = normalizedAbsolutePath(request.libraryRoot, "Library root")
  const sourceLoopId = normalizedText(request.sourceLoopId, "Source loop id")
  const identity = normalizedText(request.identity, "Layer identity")
  const layerPath = normalizedAbsolutePath(request.path, "Layer path")
  const category = normalizedCategory(request.category)
  const database = openLibraryDatabase(acceptedCachePath)
  try {
    const rows = editorRows(database, libraryRoot, sourceLoopId)
    const row = rows.find((candidate) => candidate.identity === identity && path.resolve(candidate.path) === layerPath)
    if (!row) throw new Error("The selected card no longer matches the indexed source layer.")
    const result = database.prepare(`
      UPDATE layer_cache
      SET manual_label = ?, manual_origin = 'user', updated_at_ns = ?
      WHERE library_root = ? AND source_loop_id = ? AND sha256 = ? AND path = ?
    `).run(category, Date.now() * 1_000_000, libraryRoot, sourceLoopId, identity, layerPath)
    if (Number(result.changes) !== 1) throw new Error("The layer category could not be saved.")
    if (category !== row.category) recordCategoryTruth(acceptedCachePath, row, libraryRoot, sourceLoopId, category)
    return { ...rowToLayer(row), category }
  } finally {
    database.close()
  }
}
