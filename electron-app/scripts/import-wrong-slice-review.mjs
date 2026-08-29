import { createHash } from "node:crypto"
import { readFile } from "node:fs/promises"
import path from "node:path"
import process from "node:process"
import { DatabaseSync } from "node:sqlite"

function argument(name, required = true) {
  const index = process.argv.indexOf(`--${name}`)
  const value = index >= 0 ? process.argv[index + 1] : undefined
  if (required && (!value || value.startsWith("--"))) {
    throw new Error(`Missing --${name}`)
  }
  return value
}

function issueId(libraryRoot, sourceLoopId) {
  return createHash("sha256")
    .update(`${libraryRoot}\0${sourceLoopId}`)
    .digest("hex")
}

function ensureFeedbackSchema(database) {
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
      UNIQUE (library_root, source_loop_id)
    )
  `)
  const columns = database.prepare("PRAGMA table_info(key_issue_reports)").all()
  if (!columns.some((column) => column.name === "issue_type")) {
    database.exec(
      "ALTER TABLE key_issue_reports ADD COLUMN issue_type TEXT NOT NULL DEFAULT 'wrong-key'",
    )
  }
}

const manifestPath = path.resolve(argument("manifest"))
const libraryDatabasePath = path.resolve(argument("library-db"))
const feedbackDatabasePath = path.resolve(argument("feedback-db"))
const apply = process.argv.includes("--apply")
const rows = JSON.parse(await readFile(manifestPath, "utf8"))
if (!Array.isArray(rows) || rows.length === 0) {
  throw new Error("Wrong-slice manifest must contain at least one row.")
}

const library = new DatabaseSync(libraryDatabasePath, { readOnly: true })
const resolved = []
try {
  const findLayer = library.prepare(`
    SELECT
      path,
      filename,
      sha256,
      library_root,
      source_loop_id
    FROM layer_cache
    WHERE sha256 = ?
    ORDER BY path
  `)
  for (const row of rows) {
    const matches = findLayer.all(row.sha256)
    if (matches.length !== 1) {
      throw new Error(
        `Expected one indexed layer for ${row.filename} (${row.sha256}), found ${matches.length}.`,
      )
    }
    const match = matches[0]
    resolved.push({
      id: issueId(match.library_root, match.source_loop_id),
      libraryRoot: match.library_root,
      sourceLoopId: match.source_loop_id,
      reportedIdentity: match.sha256,
      reportedPath: match.path,
      reportedFile: match.filename,
      generationOutputDirectory: path.dirname(match.path),
    })
  }
} finally {
  library.close()
}

const uniqueLoops = new Set(
  resolved.map((row) => `${row.libraryRoot}\0${row.sourceLoopId}`),
)
if (uniqueLoops.size !== resolved.length) {
  throw new Error("The manifest reports more than one bad layer for the same source loop.")
}

if (apply) {
  const feedback = new DatabaseSync(feedbackDatabasePath)
  try {
    ensureFeedbackSchema(feedback)
    const insert = feedback.prepare(`
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
        resolved_at
      ) VALUES (?, 'wrong-slice', ?, ?, ?, ?, ?, 'Not applicable', 'Not applicable', ?, ?, NULL)
      ON CONFLICT (library_root, source_loop_id) DO UPDATE SET
        issue_type = excluded.issue_type,
        reported_identity = excluded.reported_identity,
        reported_path = excluded.reported_path,
        reported_file = excluded.reported_file,
        detected_key = excluded.detected_key,
        target_key = excluded.target_key,
        generation_output_directory = excluded.generation_output_directory,
        created_at = excluded.created_at,
        resolved_at = NULL
    `)
    feedback.exec("BEGIN IMMEDIATE")
    try {
      const createdAt = new Date().toISOString()
      for (const row of resolved) {
        insert.run(
          row.id,
          row.libraryRoot,
          row.sourceLoopId,
          row.reportedIdentity,
          row.reportedPath,
          row.reportedFile,
          row.generationOutputDirectory,
          createdAt,
        )
      }
      feedback.exec("COMMIT")
    } catch (error) {
      feedback.exec("ROLLBACK")
      throw error
    }
  } finally {
    feedback.close()
  }
}

process.stdout.write(`${JSON.stringify({
  mode: apply ? "applied" : "dry-run",
  manifest: manifestPath,
  wrongSliceLoops: resolved.length,
  libraryRoots: [...new Set(resolved.map((row) => row.libraryRoot))],
}, null, 2)}\n`)
