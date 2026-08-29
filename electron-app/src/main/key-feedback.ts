import { createHash } from "node:crypto"
import { existsSync, mkdirSync } from "node:fs"
import path from "node:path"
import { DatabaseSync } from "node:sqlite"

import type {
  KeyIssueAffectedLayer,
  KeyIssueReport,
  LibraryIssueType,
  ReportKeyIssueRequest,
} from "../shared/contracts"

interface FeedbackRow {
  id: string
  issue_type: LibraryIssueType
  library_root: string
  source_loop_id: string
  reported_identity: string
  reported_path: string
  reported_file: string
  detected_key: string
  target_key: string
  generation_output_directory: string
  created_at: string
  resolved_at: string | null
  hidden_at: string | null
}

interface LayerRow {
  identity: string
  path: string
  filename: string
  scanned_key: string | null
  scanned_mode: string | null
  filename_key: string | null
  filename_mode: string | null
}

function feedbackDatabasePath(acceptedCachePath: string): string {
  return path.join(acceptedCachePath, "generate", "key-feedback.sqlite3")
}

function libraryDatabasePath(acceptedCachePath: string): string {
  return path.join(acceptedCachePath, "generate", "library.sqlite3")
}

function ensureFeedbackSchema(database: DatabaseSync): void {
  database.exec(`
    CREATE TABLE IF NOT EXISTS key_issue_reports (
      id TEXT PRIMARY KEY,
      issue_type TEXT NOT NULL DEFAULT 'wrong-key',
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
      hidden_at TEXT,
      UNIQUE (library_root, source_loop_id)
    )
  `)
  const columns = database.prepare("PRAGMA table_info(key_issue_reports)").all() as unknown as Array<{ name: string }>
  if (!columns.some((column) => column.name === "issue_type")) {
    database.exec("ALTER TABLE key_issue_reports ADD COLUMN issue_type TEXT NOT NULL DEFAULT 'wrong-key'")
  }
  if (!columns.some((column) => column.name === "hidden_at")) {
    database.exec("ALTER TABLE key_issue_reports ADD COLUMN hidden_at TEXT")
  }
}

function normalizedIssueType(value: unknown): LibraryIssueType {
  if (value === "wrong-key" || value === "wrong-slice") return value
  throw new Error("Library issue type must be wrong-key or wrong-slice.")
}

function issueId(libraryRoot: string, sourceLoopId: string): string {
  return createHash("sha256")
    .update(`${libraryRoot}\0${sourceLoopId}`)
    .digest("hex")
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

function detectedKey(row: LayerRow): string {
  const key = row.scanned_key || row.filename_key || "Unknown"
  const mode = row.scanned_key ? row.scanned_mode : row.filename_mode
  return [key, mode].filter(Boolean).join(" ")
}

function excludesHiddenLayers(database: DatabaseSync): string {
  const columns = database.prepare("PRAGMA table_info(layer_cache)").all() as unknown as Array<{ name: string }>
  return columns.some((column) => column.name === "manual_excluded")
    ? " AND COALESCE(manual_excluded, 0) = 0"
    : ""
}

function affectedLayers(
  libraryDatabase: DatabaseSync | undefined,
  libraryRoot: string,
  sourceLoopId: string,
): KeyIssueAffectedLayer[] {
  if (!libraryDatabase) return []
  const activeLayerCondition = excludesHiddenLayers(libraryDatabase)
  const rows = libraryDatabase.prepare(`
    SELECT
      sha256 AS identity,
      path,
      filename,
      scanned_key,
      scanned_mode,
      key AS filename_key,
      mode AS filename_mode
    FROM layer_cache
    WHERE library_root = ? AND source_loop_id = ?
      ${activeLayerCondition}
    ORDER BY COALESCE(layer_index, 2147483647), relative_path
  `).all(libraryRoot, sourceLoopId) as unknown as LayerRow[]
  return rows.map((row) => ({
    identity: row.identity,
    path: row.path,
    file: row.filename,
    detectedKey: detectedKey(row),
  }))
}

export function listKeyIssueReports(acceptedCachePath: string): KeyIssueReport[] {
  const feedbackPath = feedbackDatabasePath(acceptedCachePath)
  mkdirSync(path.dirname(feedbackPath), { recursive: true })
  const feedbackDatabase = new DatabaseSync(feedbackPath)
  const libraryPath = libraryDatabasePath(acceptedCachePath)
  const libraryDatabase = existsSync(libraryPath)
    ? new DatabaseSync(libraryPath, { readOnly: true })
    : undefined
  try {
    ensureFeedbackSchema(feedbackDatabase)
    const rows = feedbackDatabase.prepare(`
      SELECT *
      FROM key_issue_reports
      WHERE hidden_at IS NULL
      ORDER BY created_at DESC
    `).all() as unknown as FeedbackRow[]
    return rows.map((row) => ({
      id: row.id,
      issueType: normalizedIssueType(row.issue_type),
      libraryRoot: row.library_root,
      sourceLoopId: row.source_loop_id,
      reportedIdentity: row.reported_identity,
      reportedPath: row.reported_path,
      reportedFile: row.reported_file,
      detectedKey: row.detected_key,
      targetKey: row.target_key,
      generationOutputDirectory: row.generation_output_directory,
      createdAt: row.created_at,
      resolvedAt: row.resolved_at ?? undefined,
      active: row.resolved_at == null,
      affectedLayers: affectedLayers(
        libraryDatabase,
        row.library_root,
        row.source_loop_id,
      ),
    }))
  } finally {
    libraryDatabase?.close()
    feedbackDatabase.close()
  }
}

export function reportKeyIssue(
  acceptedCachePath: string,
  request: ReportKeyIssueRequest,
): KeyIssueReport[] {
  const libraryRoot = normalizedAbsolutePath(request.libraryRoot, "Library root")
  const issueType = normalizedIssueType(request.issueType)
  const sourceLoopId = normalizedText(request.sourceLoopId, "Source loop id")
  const reportedPath = normalizedAbsolutePath(request.reportedPath, "Reported layer path")
  const reportedIdentity = normalizedText(request.reportedIdentity, "Reported layer identity")
  const reportedFile = normalizedText(request.reportedFile, "Reported layer filename")
  const detected = normalizedText(request.detectedKey, "Detected key")
  const target = normalizedText(request.targetKey, "Generation target key")
  const generationOutputDirectory = normalizedAbsolutePath(
    request.generationOutputDirectory,
    "Generation output directory",
  )

  const libraryPath = libraryDatabasePath(acceptedCachePath)
  if (!existsSync(libraryPath)) throw new Error("The Generate catalogue is unavailable.")
  const libraryDatabase = new DatabaseSync(libraryPath, { readOnly: true })
  try {
    const match = libraryDatabase.prepare(`
      SELECT COUNT(*) AS count
      FROM layer_cache
      WHERE library_root = ?
        AND source_loop_id = ?
        AND path = ?
        AND sha256 = ?
    `).get(libraryRoot, sourceLoopId, reportedPath, reportedIdentity) as unknown as { count: number }
    if (Number(match.count) !== 1) {
      throw new Error("The reported card no longer matches the indexed source layer.")
    }
  } finally {
    libraryDatabase.close()
  }

  const feedbackPath = feedbackDatabasePath(acceptedCachePath)
  mkdirSync(path.dirname(feedbackPath), { recursive: true })
  const database = new DatabaseSync(feedbackPath)
  try {
    ensureFeedbackSchema(database)
    const createdAt = new Date().toISOString()
    database.prepare(`
      INSERT INTO key_issue_reports (
        id,
        issue_type,
        library_root,
        source_loop_id,
        reported_identity,
        reported_path,
        reported_file,
        detected_key,
        target_key,
        generation_output_directory,
        created_at,
        resolved_at,
        hidden_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
      ON CONFLICT (library_root, source_loop_id) DO UPDATE SET
        issue_type = excluded.issue_type,
        reported_identity = excluded.reported_identity,
        reported_path = excluded.reported_path,
        reported_file = excluded.reported_file,
        detected_key = excluded.detected_key,
        target_key = excluded.target_key,
        generation_output_directory = excluded.generation_output_directory,
        created_at = excluded.created_at,
        resolved_at = NULL,
        hidden_at = NULL
    `).run(
      issueId(libraryRoot, sourceLoopId),
      issueType,
      libraryRoot,
      sourceLoopId,
      reportedIdentity,
      reportedPath,
      reportedFile,
      detected,
      target,
      generationOutputDirectory,
      createdAt,
    )
  } finally {
    database.close()
  }
  return listKeyIssueReports(acceptedCachePath)
}

export function setKeyIssueActive(
  acceptedCachePath: string,
  requestedIssueId: string,
  active: boolean,
): KeyIssueReport[] {
  const id = normalizedText(requestedIssueId, "Key issue id")
  const feedbackPath = feedbackDatabasePath(acceptedCachePath)
  if (!existsSync(feedbackPath)) throw new Error("The key-issue report is unavailable.")
  const database = new DatabaseSync(feedbackPath)
  try {
    ensureFeedbackSchema(database)
    const result = database.prepare(`
      UPDATE key_issue_reports
      SET resolved_at = ?
      WHERE id = ?
    `).run(active ? null : new Date().toISOString(), id)
    if (Number(result.changes) !== 1) throw new Error("The key-issue report is unavailable.")
  } finally {
    database.close()
  }
  return listKeyIssueReports(acceptedCachePath)
}

export function dismissKeyIssueReport(
  acceptedCachePath: string,
  requestedIssueId: string,
): KeyIssueReport[] {
  const id = normalizedText(requestedIssueId, "Key issue id")
  const feedbackPath = feedbackDatabasePath(acceptedCachePath)
  if (!existsSync(feedbackPath)) throw new Error("The key-issue report is unavailable.")
  const database = new DatabaseSync(feedbackPath)
  try {
    ensureFeedbackSchema(database)
    const result = database.prepare(`
      UPDATE key_issue_reports
      SET hidden_at = ?
      WHERE id = ?
    `).run(new Date().toISOString(), id)
    if (Number(result.changes) !== 1) throw new Error("The key-issue report is unavailable.")
  } finally {
    database.close()
  }
  return listKeyIssueReports(acceptedCachePath)
}
