import { randomUUID } from "node:crypto"
import { constants, copyFileSync, existsSync, mkdirSync, statSync } from "node:fs"
import path from "node:path"
import { DatabaseSync, type StatementSync } from "node:sqlite"

import type { CloudTrackedDragRequest } from "../shared/contracts"

const DEFAULT_PENDING_LIMIT = 50
const MAX_PENDING_LIMIT = 500

type CloudExportOutboxState = "pending" | "sending" | "complete"

interface CloudExportOutboxRow {
  client_event_id: string
  project_url: string
  user_id: string
  payload_json: string
  state: CloudExportOutboxState
  attempts: number
  next_attempt_at: number
  last_error: string
  created_at: number
  updated_at: number
}

export interface CloudExportOutboxBinding {
  projectUrl: string
  userId: string
}

export interface CloudExportOutboxEntry {
  clientEventId: string
  binding: CloudExportOutboxBinding
  request: CloudTrackedDragRequest
  state: CloudExportOutboxState
  attempts: number
  nextAttemptAt: number
  lastError: string
  createdAt: number
  updatedAt: number
}

function nonEmptyString(value: unknown, field: string): asserts value is string {
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new TypeError(`${field} must be a non-empty string.`)
  }
}

function finiteNumber(value: unknown, field: string): asserts value is number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new TypeError(`${field} must be a finite number.`)
  }
}

function validatedBinding(binding: CloudExportOutboxBinding): CloudExportOutboxBinding {
  if (!binding || typeof binding !== "object") throw new TypeError("The Cloud export binding is invalid.")
  nonEmptyString(binding.projectUrl, "projectUrl")
  nonEmptyString(binding.userId, "userId")
  return {
    projectUrl: binding.projectUrl.trim().replace(/\/+$/, ""),
    userId: binding.userId.trim(),
  }
}

function validateRequest(request: CloudTrackedDragRequest): void {
  if (!request || typeof request !== "object") throw new TypeError("The tracked drag request is invalid.")
  nonEmptyString(request.exportPath, "exportPath")
  nonEmptyString(request.masterPath, "masterPath")
  nonEmptyString(request.generatedLoopName, "generatedLoopName")
  nonEmptyString(request.targetKey, "targetKey")
  if (!(["drag-all", "layer-audio", "layer-midi"] as const).includes(request.exportKind)) {
    throw new TypeError("exportKind is invalid.")
  }
  finiteNumber(request.generationSeed, "generationSeed")
  if (!Number.isSafeInteger(request.generationSeed)) throw new TypeError("generationSeed must be a safe integer.")
  finiteNumber(request.targetBpm, "targetBpm")
  if (request.targetBpm <= 0) throw new TypeError("targetBpm must be positive.")
  finiteNumber(request.durationSeconds, "durationSeconds")
  if (request.durationSeconds < 0) throw new TypeError("durationSeconds cannot be negative.")
  if (!Array.isArray(request.layers) || request.layers.length === 0) {
    throw new TypeError("layers must contain at least one layer snapshot.")
  }
  const slotIndexes = new Set<number>()
  for (const [index, layer] of request.layers.entries()) {
    if (!layer || typeof layer !== "object") throw new TypeError(`layers[${index}] is invalid.`)
    finiteNumber(layer.slotIndex, `layers[${index}].slotIndex`)
    if (!Number.isSafeInteger(layer.slotIndex) || layer.slotIndex < 0) {
      throw new TypeError(`layers[${index}].slotIndex must be a non-negative integer.`)
    }
    if (slotIndexes.has(layer.slotIndex)) throw new TypeError("Layer slot indexes must be unique.")
    slotIndexes.add(layer.slotIndex)
    nonEmptyString(layer.category, `layers[${index}].category`)
    nonEmptyString(layer.sourceLayerName, `layers[${index}].sourceLayerName`)
    if (typeof layer.sourceLoopId !== "string") throw new TypeError(`layers[${index}].sourceLoopId must be a string.`)
    if (typeof layer.sourceLoopName !== "string") throw new TypeError(`layers[${index}].sourceLoopName must be a string.`)
    if (layer.sourceOrigin !== "local" && layer.sourceOrigin !== "cloud") {
      throw new TypeError(`layers[${index}].sourceOrigin is invalid.`)
    }
    if (typeof layer.triggered !== "boolean") throw new TypeError(`layers[${index}].triggered must be a boolean.`)
    if (layer.cloudLayerId !== undefined) nonEmptyString(layer.cloudLayerId, `layers[${index}].cloudLayerId`)
    if (layer.cloudOwnerId !== undefined) nonEmptyString(layer.cloudOwnerId, `layers[${index}].cloudOwnerId`)
    if (layer.sourceSha256 !== undefined) nonEmptyString(layer.sourceSha256, `layers[${index}].sourceSha256`)
  }
}

function rowToEntry(row: CloudExportOutboxRow): CloudExportOutboxEntry {
  let request: unknown
  try {
    request = JSON.parse(row.payload_json)
  } catch (error) {
    throw new Error(`Cloud export outbox entry ${row.client_event_id} has an invalid payload.`, { cause: error })
  }
  validateRequest(request as CloudTrackedDragRequest)
  return {
    clientEventId: row.client_event_id,
    binding: {
      projectUrl: row.project_url,
      userId: row.user_id,
    },
    request: request as CloudTrackedDragRequest,
    state: row.state,
    attempts: Number(row.attempts),
    nextAttemptAt: Number(row.next_attempt_at),
    lastError: row.last_error,
    createdAt: Number(row.created_at),
    updatedAt: Number(row.updated_at),
  }
}

export class CloudExportOutbox {
  private readonly database: DatabaseSync
  private readonly snapshotRoot: string
  private lastCreatedAt: number
  private readonly insertStatement: StatementSync
  private readonly pendingStatement: StatementSync
  private readonly markSendingStatement: StatementSync
  private readonly markRetryStatement: StatementSync
  private readonly markCompleteStatement: StatementSync
  private readonly resetInterruptedStatement: StatementSync
  private readonly nextPendingAtStatement: StatementSync
  private readonly completedStatement: StatementSync
  private readonly removeCompletedStatement: StatementSync

  constructor(databasePath: string, snapshotRoot = path.join(path.dirname(databasePath), "export-masters")) {
    nonEmptyString(databasePath, "databasePath")
    nonEmptyString(snapshotRoot, "snapshotRoot")
    mkdirSync(path.dirname(databasePath), { recursive: true })
    this.snapshotRoot = path.resolve(snapshotRoot)
    mkdirSync(this.snapshotRoot, { recursive: true })
    this.database = new DatabaseSync(databasePath)
    this.database.exec(`
      PRAGMA journal_mode = WAL;
      PRAGMA synchronous = FULL;
      PRAGMA busy_timeout = 5000;

      CREATE TABLE IF NOT EXISTS cloud_export_outbox (
        client_event_id TEXT PRIMARY KEY NOT NULL CHECK(length(client_event_id) = 36),
        project_url TEXT NOT NULL DEFAULT '',
        user_id TEXT NOT NULL DEFAULT '',
        payload_json TEXT NOT NULL,
        state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN ('pending', 'sending', 'complete')),
        attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
        next_attempt_at INTEGER NOT NULL,
        last_error TEXT NOT NULL DEFAULT '',
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL
      );

      CREATE INDEX IF NOT EXISTS cloud_export_outbox_pending
        ON cloud_export_outbox(state, next_attempt_at, created_at);
    `)
    const existingColumns = new Set((this.database.prepare(`
      PRAGMA table_info(cloud_export_outbox)
    `).all() as unknown as Array<{ name: string }>).map((column) => column.name))
    if (!existingColumns.has("project_url")) {
      this.database.exec("ALTER TABLE cloud_export_outbox ADD COLUMN project_url TEXT NOT NULL DEFAULT ''")
    }
    if (!existingColumns.has("user_id")) {
      this.database.exec("ALTER TABLE cloud_export_outbox ADD COLUMN user_id TEXT NOT NULL DEFAULT ''")
    }
    this.database.exec(`
      CREATE INDEX IF NOT EXISTS cloud_export_outbox_binding_pending
        ON cloud_export_outbox(project_url, user_id, state, next_attempt_at, created_at);
    `)
    const latest = this.database.prepare(`
      SELECT MAX(created_at) AS created_at FROM cloud_export_outbox
    `).get() as { created_at: number | null }
    this.lastCreatedAt = latest.created_at == null ? 0 : Number(latest.created_at)
    this.insertStatement = this.database.prepare(`
      INSERT INTO cloud_export_outbox (
        client_event_id, project_url, user_id, payload_json, state, attempts,
        next_attempt_at, last_error, created_at, updated_at
      ) VALUES (?, ?, ?, ?, 'pending', 0, ?, '', ?, ?)
    `)
    this.pendingStatement = this.database.prepare(`
      SELECT client_event_id, project_url, user_id, payload_json, state, attempts,
             next_attempt_at, last_error, created_at, updated_at
      FROM cloud_export_outbox
      WHERE project_url = ? AND user_id = ? AND state = 'pending' AND next_attempt_at <= ?
      ORDER BY next_attempt_at ASC, created_at ASC, client_event_id ASC
      LIMIT ?
    `)
    this.markSendingStatement = this.database.prepare(`
      UPDATE cloud_export_outbox
      SET state = 'sending', attempts = attempts + 1, updated_at = ?
      WHERE client_event_id = ? AND project_url = ? AND user_id = ? AND state = 'pending'
    `)
    this.markRetryStatement = this.database.prepare(`
      UPDATE cloud_export_outbox
      SET state = 'pending', next_attempt_at = ?, last_error = ?, updated_at = ?
      WHERE client_event_id = ? AND project_url = ? AND user_id = ? AND state <> 'complete'
    `)
    this.markCompleteStatement = this.database.prepare(`
      UPDATE cloud_export_outbox
      SET state = 'complete', last_error = '', updated_at = ?
      WHERE client_event_id = ? AND project_url = ? AND user_id = ?
    `)
    this.resetInterruptedStatement = this.database.prepare(`
      UPDATE cloud_export_outbox
      SET state = 'pending', next_attempt_at = ?, updated_at = ?
      WHERE state = 'sending'
    `)
    this.nextPendingAtStatement = this.database.prepare(`
      SELECT MIN(next_attempt_at) AS next_attempt_at
      FROM cloud_export_outbox
      WHERE project_url = ? AND user_id = ? AND state = 'pending'
    `)
    this.completedStatement = this.database.prepare(`
      SELECT client_event_id, project_url, user_id, payload_json, state, attempts,
             next_attempt_at, last_error, created_at, updated_at
      FROM cloud_export_outbox
      WHERE project_url = ? AND user_id = ? AND state = 'complete'
      ORDER BY updated_at ASC, created_at ASC, client_event_id ASC
      LIMIT ?
    `)
    this.removeCompletedStatement = this.database.prepare(`
      DELETE FROM cloud_export_outbox
      WHERE client_event_id = ? AND project_url = ? AND user_id = ? AND state = 'complete'
    `)
  }

  enqueue(binding: CloudExportOutboxBinding, request: CloudTrackedDragRequest): string {
    const owner = validatedBinding(binding)
    validateRequest(request)
    if (!existsSync(request.masterPath) || !statSync(request.masterPath).isFile()) {
      throw new Error("The rendered master for this Cloud activity is unavailable.")
    }
    const clientEventId = randomUUID()
    const rawExtension = path.extname(request.masterPath).toLocaleLowerCase()
    const extension = /^\.[a-z0-9]{1,10}$/.test(rawExtension) ? rawExtension : ".audio"
    const snapshotPath = path.join(this.snapshotRoot, `${clientEventId}${extension}`)
    copyFileSync(request.masterPath, snapshotPath, constants.COPYFILE_FICLONE)
    const snapshotRequest: CloudTrackedDragRequest = {
      ...request,
      masterPath: snapshotPath,
      layers: request.layers.map((layer) => ({ ...layer })),
    }
    const now = Date.now()
    const createdAt = Math.max(now, this.lastCreatedAt + 1)
    this.lastCreatedAt = createdAt
    this.insertStatement.run(
      clientEventId,
      owner.projectUrl,
      owner.userId,
      JSON.stringify(snapshotRequest),
      now,
      createdAt,
      createdAt,
    )
    return clientEventId
  }

  pending(binding: CloudExportOutboxBinding, now = Date.now(), limit = DEFAULT_PENDING_LIMIT): CloudExportOutboxEntry[] {
    const owner = validatedBinding(binding)
    finiteNumber(now, "now")
    if (!Number.isSafeInteger(now) || now < 0) throw new TypeError("now must be a non-negative integer timestamp.")
    if (!Number.isSafeInteger(limit) || limit < 1 || limit > MAX_PENDING_LIMIT) {
      throw new TypeError(`limit must be an integer between 1 and ${MAX_PENDING_LIMIT}.`)
    }
    return (this.pendingStatement.all(owner.projectUrl, owner.userId, now, limit) as unknown as CloudExportOutboxRow[]).map(rowToEntry)
  }

  markSending(binding: CloudExportOutboxBinding, clientEventId: string): void {
    const owner = validatedBinding(binding)
    nonEmptyString(clientEventId, "clientEventId")
    this.markSendingStatement.run(Date.now(), clientEventId, owner.projectUrl, owner.userId)
  }

  markRetry(binding: CloudExportOutboxBinding, clientEventId: string, error: string, nextAttemptAt: number): void {
    const owner = validatedBinding(binding)
    nonEmptyString(clientEventId, "clientEventId")
    nonEmptyString(error, "error")
    finiteNumber(nextAttemptAt, "nextAttemptAt")
    if (!Number.isSafeInteger(nextAttemptAt) || nextAttemptAt < 0) {
      throw new TypeError("nextAttemptAt must be a non-negative integer timestamp.")
    }
    this.markRetryStatement.run(nextAttemptAt, error.trim(), Date.now(), clientEventId, owner.projectUrl, owner.userId)
  }

  markComplete(binding: CloudExportOutboxBinding, clientEventId: string): void {
    const owner = validatedBinding(binding)
    nonEmptyString(clientEventId, "clientEventId")
    this.markCompleteStatement.run(Date.now(), clientEventId, owner.projectUrl, owner.userId)
  }

  resetInterrupted(): number {
    const now = Date.now()
    return Number(this.resetInterruptedStatement.run(now, now).changes)
  }

  nextPendingAt(binding: CloudExportOutboxBinding): number | undefined {
    const owner = validatedBinding(binding)
    const row = this.nextPendingAtStatement.get(owner.projectUrl, owner.userId) as { next_attempt_at: number | null }
    return row.next_attempt_at == null ? undefined : Number(row.next_attempt_at)
  }

  completed(binding: CloudExportOutboxBinding, limit = DEFAULT_PENDING_LIMIT): CloudExportOutboxEntry[] {
    const owner = validatedBinding(binding)
    if (!Number.isSafeInteger(limit) || limit < 1 || limit > MAX_PENDING_LIMIT) {
      throw new TypeError(`limit must be an integer between 1 and ${MAX_PENDING_LIMIT}.`)
    }
    return (this.completedStatement.all(owner.projectUrl, owner.userId, limit) as unknown as CloudExportOutboxRow[]).map(rowToEntry)
  }

  removeCompleted(binding: CloudExportOutboxBinding, clientEventId: string): boolean {
    const owner = validatedBinding(binding)
    nonEmptyString(clientEventId, "clientEventId")
    return Number(this.removeCompletedStatement.run(clientEventId, owner.projectUrl, owner.userId).changes) === 1
  }

  isManagedSnapshot(candidatePath: string): boolean {
    if (typeof candidatePath !== "string" || candidatePath.length === 0) return false
    const resolved = path.resolve(candidatePath)
    const relative = path.relative(this.snapshotRoot, resolved)
    return Boolean(relative)
      && !relative.startsWith("..")
      && !path.isAbsolute(relative)
      && path.dirname(resolved) === this.snapshotRoot
  }

  close(): void {
    this.database.close()
  }
}
