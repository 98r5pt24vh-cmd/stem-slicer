import { mkdtempSync, readFileSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"
import { DatabaseSync } from "node:sqlite"

import { describe, expect, it } from "vitest"

import type { CloudTrackedDragRequest } from "../shared/contracts"
import { CloudExportOutbox, type CloudExportOutboxBinding } from "./cloud-export-outbox"

const firstBinding: CloudExportOutboxBinding = {
  projectUrl: "https://first.supabase.co",
  userId: "producer-one",
}
const secondBinding: CloudExportOutboxBinding = {
  projectUrl: "https://second.supabase.co",
  userId: "producer-two",
}

function request(masterPath: string, overrides: Partial<CloudTrackedDragRequest> = {}): CloudTrackedDragRequest {
  return {
    exportPath: "/tmp/generated/Lead.mid",
    masterPath,
    exportKind: "layer-midi",
    generatedLoopName: "L Gen161_140_Em +NRGY XT",
    generationSeed: 161,
    targetBpm: 140,
    targetKey: "E minor",
    durationSeconds: 7.4,
    layers: [{
      slotIndex: 0,
      category: "Lead",
      sourceLayerName: "Bm FM 151 FMIN XT_L10.mp3",
      sourceLoopId: "bm-fm-151-fmin-xt",
      sourceLoopName: "Bm FM 151 FMIN XT",
      sourceOrigin: "cloud",
      cloudLayerId: "cloud-layer",
      cloudOwnerId: "cloud-owner",
      sourceSha256: "a".repeat(64),
      triggered: true,
    }],
    ...overrides,
  }
}

function fixture(): { databasePath: string; masterPath: string; root: string } {
  const root = mkdtempSync(path.join(tmpdir(), "slicer-cloud-export-outbox-"))
  const masterPath = path.join(root, "MASTER.wav")
  writeFileSync(masterPath, "immutable-master")
  return { databasePath: path.join(root, "outbox.sqlite3"), masterPath, root }
}

describe("Cloud export outbox", () => {
  it("persists a validated drag request with a stable UUID", () => {
    const { databasePath, masterPath } = fixture()
    const first = new CloudExportOutbox(databasePath)
    const clientEventId = first.enqueue(firstBinding, request(masterPath))
    expect(clientEventId).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
    first.close()

    const reopened = new CloudExportOutbox(databasePath)
    const entries = reopened.pending(firstBinding, Number.MAX_SAFE_INTEGER)
    expect(entries).toEqual([expect.objectContaining({
      clientEventId,
      binding: firstBinding,
      state: "pending",
      attempts: 0,
      lastError: "",
    })])
    expect(entries[0].request).toMatchObject({
      ...request(masterPath),
      masterPath: expect.not.stringMatching(masterPath),
    })
    expect(reopened.isManagedSnapshot(entries[0].request.masterPath)).toBe(true)
    expect(readFileSync(entries[0].request.masterPath, "utf8")).toBe("immutable-master")
    expect(reopened.pending(secondBinding, Number.MAX_SAFE_INTEGER)).toEqual([])
    reopened.close()
  })

  it("returns only due pending work and applies a deterministic limit", () => {
    const { databasePath, masterPath } = fixture()
    const outbox = new CloudExportOutbox(databasePath)
    const firstId = outbox.enqueue(firstBinding, request(masterPath, { generatedLoopName: "First" }))
    const secondId = outbox.enqueue(firstBinding, request(masterPath, { generatedLoopName: "Second" }))

    expect(outbox.pending(firstBinding, Number.MAX_SAFE_INTEGER, 1).map((entry) => entry.clientEventId)).toEqual([firstId])
    outbox.markSending(firstBinding, firstId)
    expect(outbox.pending(firstBinding, Number.MAX_SAFE_INTEGER).map((entry) => entry.clientEventId)).toEqual([secondId])
    outbox.close()
  })

  it("increments attempts, schedules retry and permanently excludes completed work", () => {
    const { databasePath, masterPath } = fixture()
    const outbox = new CloudExportOutbox(databasePath)
    const clientEventId = outbox.enqueue(firstBinding, request(masterPath))
    outbox.markSending(firstBinding, clientEventId)
    expect(outbox.pending(firstBinding, Number.MAX_SAFE_INTEGER)).toEqual([])

    const retryAt = Date.now() + 60_000
    outbox.markRetry(firstBinding, clientEventId, "  network unavailable  ", retryAt)
    expect(outbox.pending(firstBinding, retryAt - 1)).toEqual([])
    expect(outbox.nextPendingAt(firstBinding)).toBe(retryAt)
    expect(outbox.nextPendingAt(secondBinding)).toBeUndefined()
    expect(outbox.pending(firstBinding, retryAt)).toEqual([expect.objectContaining({
      clientEventId,
      state: "pending",
      attempts: 1,
      nextAttemptAt: retryAt,
      lastError: "network unavailable",
    })])

    outbox.markComplete(firstBinding, clientEventId)
    expect(outbox.pending(firstBinding, Number.MAX_SAFE_INTEGER)).toEqual([])
    expect(outbox.nextPendingAt(firstBinding)).toBeUndefined()
    expect(outbox.completed(firstBinding)).toEqual([expect.objectContaining({ clientEventId, state: "complete" })])
    expect(outbox.removeCompleted(secondBinding, clientEventId)).toBe(false)
    expect(outbox.removeCompleted(firstBinding, clientEventId)).toBe(true)
    outbox.close()
  })

  it("recovers interrupted sending rows immediately without losing attempts", () => {
    const { databasePath, masterPath } = fixture()
    const outbox = new CloudExportOutbox(databasePath)
    const clientEventId = outbox.enqueue(firstBinding, request(masterPath))
    outbox.markSending(firstBinding, clientEventId)

    expect(outbox.resetInterrupted()).toBe(1)
    expect(outbox.resetInterrupted()).toBe(0)
    expect(outbox.pending(firstBinding, Number.MAX_SAFE_INTEGER)).toEqual([expect.objectContaining({
      clientEventId,
      state: "pending",
      attempts: 1,
    })])
    outbox.close()
  })

  it("rejects malformed payloads before touching the durable queue", () => {
    const { databasePath, masterPath } = fixture()
    const outbox = new CloudExportOutbox(databasePath)
    const valid = request(masterPath)
    expect(() => outbox.enqueue(firstBinding, request(masterPath, { exportPath: "" }))).toThrow("exportPath")
    expect(() => outbox.enqueue(firstBinding, request(masterPath, { durationSeconds: -1 }))).toThrow("durationSeconds")
    expect(() => outbox.enqueue(firstBinding, request(masterPath, { layers: [{ ...valid.layers[0], slotIndex: -1 }] }))).toThrow("slotIndex")
    expect(() => outbox.enqueue(firstBinding, request(masterPath, { layers: [valid.layers[0], { ...valid.layers[0] }] }))).toThrow("unique")
    expect(outbox.pending(firstBinding, Number.MAX_SAFE_INTEGER)).toEqual([])
    outbox.close()
  })

  it("keeps the queued master immutable when the generated file is overwritten", () => {
    const { databasePath, masterPath } = fixture()
    const outbox = new CloudExportOutbox(databasePath)
    outbox.enqueue(firstBinding, request(masterPath))
    const snapshotPath = outbox.pending(firstBinding, Number.MAX_SAFE_INTEGER)[0].request.masterPath

    writeFileSync(masterPath, "a-new-generation")

    expect(readFileSync(snapshotPath, "utf8")).toBe("immutable-master")
    expect(outbox.isManagedSnapshot(masterPath)).toBe(false)
    expect(outbox.isManagedSnapshot(snapshotPath)).toBe(true)
    outbox.close()
  })

  it("migrates legacy rows without assigning them to whichever account signs in next", () => {
    const { databasePath, masterPath } = fixture()
    const legacy = new DatabaseSync(databasePath)
    legacy.exec(`
      CREATE TABLE cloud_export_outbox (
        client_event_id TEXT PRIMARY KEY NOT NULL,
        payload_json TEXT NOT NULL,
        state TEXT NOT NULL,
        attempts INTEGER NOT NULL,
        next_attempt_at INTEGER NOT NULL,
        last_error TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL
      )
    `)
    legacy.prepare(`
      INSERT INTO cloud_export_outbox VALUES (?, ?, 'pending', 0, 0, '', 1, 1)
    `).run("00000000-0000-4000-8000-000000000000", JSON.stringify(request(masterPath)))
    legacy.close()

    const migrated = new CloudExportOutbox(databasePath)
    expect(migrated.pending(firstBinding, Number.MAX_SAFE_INTEGER)).toEqual([])
    expect(migrated.pending(secondBinding, Number.MAX_SAFE_INTEGER)).toEqual([])
    migrated.close()

    const inspected = new DatabaseSync(databasePath)
    const row = inspected.prepare("SELECT project_url, user_id FROM cloud_export_outbox").get() as { project_url: string; user_id: string }
    expect(row).toEqual({ project_url: "", user_id: "" })
    inspected.close()
  })
})
