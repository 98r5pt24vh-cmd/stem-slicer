import { createHash } from "node:crypto"
import { existsSync } from "node:fs"
import path from "node:path"
import { DatabaseSync } from "node:sqlite"

import { PRIMARY_PRODUCER, sourceProvenance, uniqueProducerNames } from "../lib/source-provenance"

export interface LocalCloudLayer {
  path: string
  relativePath: string
  fileName: string
  sourceLoopId: string
  sha256: string
  byteSize: number
  metadata: Record<string, unknown>
}

export interface LocalCloudManifest {
  root: string
  name: string
  fingerprint: string
  totalBytes: number
  loopCount: number
  layers: LocalCloudLayer[]
}

interface LayerCacheRow {
  path: string
  relative_path: string
  filename: string
  source_loop_id: string
  layer_index: number | null
  bpm: number | null
  key: string | null
  mode: string | null
  duration_seconds: number | null
  byte_size: number
  sha256: string
  predicted_label: string | null
  prediction_confidence: number | null
  manual_label: string | null
  scanned_key: string | null
  scanned_mode: string | null
  key_confidence_margin: number | null
  key_confidence_status: string
  key_analyzer_id: string | null
  alternate_scanned_key: string | null
  alternate_scanned_mode: string | null
  key_top1_probability: number | null
  key_top2_probability: number | null
  manual_bpm: number | null
  manual_key: string | null
  manual_mode: string | null
  timeline_offset_beats: number
  trim_start_beats: number
  trim_end_beats: number
}

function cloudProducerCredits(fileName: string, sourceLoopId: string, primaryProducer: string): string[] {
  const parsed = sourceProvenance(fileName, sourceLoopId)
  return uniqueProducerNames(parsed.producers.map((producer) => (
    producer.toLowerCase() === PRIMARY_PRODUCER.toLowerCase() ? primaryProducer : producer
  )))
}

function layerMetadata(row: LayerCacheRow, primaryProducer: string): Record<string, unknown> {
  const provenance = sourceProvenance(row.filename, row.source_loop_id)
  const category = row.manual_label || row.predicted_label || "Unknown"
  return {
    source_loop_id: row.source_loop_id,
    source_loop_name: provenance.loopName,
    layer_index: row.layer_index,
    bpm: row.bpm,
    key: row.key,
    mode: row.mode,
    duration_seconds: row.duration_seconds,
    predicted_label: row.predicted_label,
    prediction_confidence: row.prediction_confidence,
    manual_label: row.manual_label,
    category,
    scanned_key: row.scanned_key,
    scanned_mode: row.scanned_mode,
    key_confidence_margin: row.key_confidence_margin,
    key_confidence_status: row.key_confidence_status,
    key_analyzer_id: row.key_analyzer_id,
    alternate_scanned_key: row.alternate_scanned_key,
    alternate_scanned_mode: row.alternate_scanned_mode,
    key_top1_probability: row.key_top1_probability,
    key_top2_probability: row.key_top2_probability,
    manual_bpm: row.manual_bpm,
    manual_key: row.manual_key,
    manual_mode: row.manual_mode,
    timeline_offset_beats: row.timeline_offset_beats,
    trim_start_beats: row.trim_start_beats,
    trim_end_beats: row.trim_end_beats,
    producers: cloudProducerCredits(row.filename, row.source_loop_id, primaryProducer),
  }
}

export function readLocalCloudManifest(
  databasePath: string,
  requestedRoot: string,
  primaryProducer: string,
): LocalCloudManifest {
  const root = path.resolve(requestedRoot)
  if (!path.isAbsolute(requestedRoot) || !existsSync(root)) {
    throw new Error("The selected local library folder is unavailable.")
  }
  if (!existsSync(databasePath)) throw new Error("The local Generate catalogue is unavailable.")

  const database = new DatabaseSync(databasePath, { readOnly: true })
  let rows: LayerCacheRow[]
  try {
    rows = database.prepare(`
      SELECT
        path, relative_path, filename, source_loop_id, layer_index, bpm, key, mode,
        duration_seconds, byte_size, sha256, predicted_label, prediction_confidence,
        manual_label, scanned_key, scanned_mode, key_confidence_margin,
        key_confidence_status, key_analyzer_id, alternate_scanned_key,
        alternate_scanned_mode, key_top1_probability, key_top2_probability,
        manual_bpm, manual_key, manual_mode, timeline_offset_beats,
        trim_start_beats, trim_end_beats
      FROM layer_cache
      WHERE library_root = ? AND COALESCE(manual_excluded, 0) = 0
      ORDER BY relative_path COLLATE NOCASE
    `).all(root) as unknown as LayerCacheRow[]
  } finally {
    database.close()
  }

  const fingerprint = createHash("sha256")
  const loops = new Set<string>()
  const layers: LocalCloudLayer[] = []
  let totalBytes = 0
  for (const row of rows) {
    const sourcePath = path.resolve(row.path)
    if (!existsSync(sourcePath)) continue
    fingerprint.update(row.relative_path)
    fingerprint.update("\0")
    fingerprint.update(row.sha256)
    fingerprint.update("\0")
    loops.add(row.source_loop_id)
    totalBytes += Number(row.byte_size)
    layers.push({
      path: sourcePath,
      relativePath: row.relative_path,
      fileName: row.filename,
      sourceLoopId: row.source_loop_id,
      sha256: row.sha256.toLowerCase(),
      byteSize: Number(row.byte_size),
      metadata: layerMetadata(row, primaryProducer),
    })
  }
  if (layers.length === 0) {
    throw new Error("This folder has no active indexed layers to publish.")
  }
  return {
    root,
    name: path.basename(root) || "Cloud library",
    fingerprint: fingerprint.digest("hex"),
    totalBytes,
    loopCount: loops.size,
    layers,
  }
}

export function audioMimeType(fileName: string): string {
  switch (path.extname(fileName).toLowerCase()) {
    case ".mp3": return "audio/mpeg"
    case ".wav": return "audio/wav"
    case ".aif":
    case ".aiff": return "audio/aiff"
    case ".flac": return "audio/flac"
    case ".m4a": return "audio/mp4"
    default: return "application/octet-stream"
  }
}

export function safeObjectFileName(fileName: string): string {
  const originalExtension = path.extname(fileName)
  const extension = originalExtension.toLowerCase()
  const stem = path.basename(fileName, originalExtension)
    .normalize("NFKD")
    .replace(/[^a-zA-Z0-9._,'!&$@=;:+?() -]+/g, "-")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 120)
  return `${stem || "layer"}${extension || ".mp3"}`
}

export function cloudCachePath(cacheRoot: string, ownerId: string, libraryId: string, sha256: string, fileName: string): string {
  const extension = path.extname(fileName).toLowerCase() || ".mp3"
  return path.join(cacheRoot, ownerId, libraryId, `${sha256}${extension}`)
}
