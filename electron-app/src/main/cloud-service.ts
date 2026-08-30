import { createHash, randomUUID } from "node:crypto"
import { createReadStream, existsSync, mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from "node:fs"
import { readFile } from "node:fs/promises"
import path from "node:path"
import { nativeImage, safeStorage, shell } from "electron"
import { createClient, type RealtimeChannel, type Session, type SupabaseClient } from "@supabase/supabase-js"

import type {
  CloudActivityAudio,
  CloudConnection,
  CloudCredentialsRequest,
  CloudExportActivity,
  CloudExportActivitySource,
  CloudLibrarySummary,
  CloudProfile,
  CloudProfileUpdateRequest,
  CloudPublishEvent,
  CloudPublishStart,
  CloudSignUpRequest,
  CloudState,
  CloudSyncEvent,
  CloudTestAccount,
  CloudTrackedDragRequest,
  ConfigureCloudRequest,
  GenerateJobRequest,
} from "../shared/contracts"
import { CloudExportOutbox, type CloudExportOutboxBinding } from "./cloud-export-outbox"
import {
  audioMimeType,
  cloudCachePath,
  readLocalCloudManifest,
  safeObjectFileName,
} from "./cloud-catalog"

const CLOUD_BUCKET = "cloud-layers"
const PROFILE_AVATAR_BUCKET = "profile-avatars"
const FREE_PROJECT_OBJECT_LIMIT = 50_000_000
const STANDARD_UPLOAD_FAST_PATH_LIMIT = 6_000_000
const DEFAULT_UPLOAD_CONCURRENCY = 3
const SMALL_LAYER_UPLOAD_CONCURRENCY = 6
const INSERT_BATCH_SIZE = 200
const CATALOG_PAGE_SIZE = 1_000
const STORAGE_LIST_PAGE_SIZE = 1_000
const STORAGE_DELETE_BATCH_SIZE = 1_000
const PROFILE_AVATAR_SOURCE_LIMIT = 25_000_000
const PROFILE_AVATAR_UPLOAD_LIMIT = 5_000_000
const PROFILE_AVATAR_EDGE = 512
const CLOUD_EXPORT_BUCKET = "cloud-export-masters"
const CLOUD_EXPORT_ACTIVITY_LIMIT = 100
const CLOUD_EXPORT_RETRY_BASE_MS = 5_000
const CLOUD_EXPORT_RETRY_MAX_MS = 5 * 60_000
const CLOUD_ACTIVITY_CACHE_SIDECAR_SUFFIX = ".expiry.json"

interface ActivityAudioCacheSidecar {
  version: 1
  audioFileName: string
  sha256: string
  expiresAt: string
}

interface ExpiredActivityAudioCacheEntry {
  audioPath: string
  sidecarPath: string
}

class ExportBindingChangedError extends Error {}

interface CloudLocalSettings {
  projectUrl?: string
  publishableKey?: string
  enabledLibraryIds?: string[]
  pendingProfiles?: Record<string, { handle: string; displayName: string }>
}

interface AlphaCredentialsFile {
  projectRef?: string
  accounts?: Record<string, {
    email?: string
    password?: string
    handle?: string
    displayName?: string
  }>
}

interface ProfileRow {
  id: string
  handle: string
  display_name: string
  avatar_path: string | null
  bio: string | null
  instagram_handle: string | null
  aliases: string[] | null
  updated_at: string
}

const PROFILE_COLUMNS = "id,handle,display_name,avatar_path,bio,instagram_handle,aliases,updated_at"

interface ConnectionRow {
  id: string
  requester_id: string
  addressee_id: string
  status: "pending" | "accepted" | "declined"
  created_at: string
}

interface LibraryRow {
  id: string
  owner_id: string
  name: string
  status: "uploading" | "ready" | "failed" | "archived"
  layer_count: number
  loop_count: number
  total_bytes: number
  updated_at: string
}

interface LibraryAccessBlockRow {
  library_id: string
  producer_id: string
}

interface RemoteLayerRow {
  id: string
  library_id: string
  owner_id: string
  object_path: string
  file_name: string
  relative_path: string
  sha256: string
  byte_size: number
  metadata: Record<string, unknown>
}

interface CloudExportEventRow {
  id: string
  client_event_id: string
  created_by: string
  creator_handle_snapshot: string
  creator_display_name_snapshot: string
  export_kind: "drag-all" | "layer-audio" | "layer-midi"
  generated_loop_name: string
  generation_seed: number
  target_bpm: number
  target_key: string
  layer_count: number
  duration_seconds: number
  asset_id: string | null
  audio_status: "preparing" | "uploading" | "available" | "failed" | "expired"
  audio_expires_at: string | null
  audio_error: string | null
  created_at: string
}

interface CloudExportSourceRow {
  event_id: string
  slot_index: number
  source_origin: "local" | "cloud"
  source_owner_id: string | null
  source_owner_handle_snapshot: string | null
  source_owner_display_name_snapshot: string | null
  source_sha256: string | null
  source_layer_name: string
  source_loop_id: string
  source_loop_name: string
  category: string
  triggered: boolean
}

interface CloudExportRecipientRow {
  event_id: string
  recipient_id: string
  read_at: string | null
}

interface CloudExportAssetRow {
  id: string
  owner_id: string
  sha256: string
  object_path: string
  mime_type: string | null
  byte_size: number | null
  duration_seconds: number
  status: "uploading" | "available" | "failed" | "expiring" | "expired"
  retain_until: string
  error_message: string | null
}

interface CloudGenerateJobRequest extends GenerateJobRequest {
  cloudLayers?: Array<Record<string, unknown>>
  cloudAuth?: Record<string, unknown>
}

type PublishListener = (event: CloudPublishEvent) => void
type SyncListener = (event: CloudSyncEvent) => void

async function sha256File(filePath: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const digest = createHash("sha256")
    const stream = createReadStream(filePath)
    stream.on("data", (chunk) => digest.update(chunk))
    stream.once("error", reject)
    stream.once("end", () => resolve(digest.digest("hex")))
  })
}

export function normalizeCloudHandle(value: string): string {
  const normalized = value.trim().toLocaleLowerCase().normalize("NFKD").replace(/\p{M}+/gu, "")
  const leadingPlus = normalized.startsWith("+")
  const body = normalized
    .replace(/^\+/, "")
    .replace(/\s+/g, "-")
    .replace(/[^a-z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "")
  return `${leadingPlus ? "+" : ""}${body}`
}

function assertValidCloudHandle(handle: string): void {
  const body = handle.replace(/^\+/, "")
  if (body.length < 3 || handle.length > 32 || !/^\+?[a-z0-9][a-z0-9_-]*$/.test(handle)) {
    throw new Error("Use 3–32 letters or numbers, with an optional leading +, hyphens or underscores.")
  }
}

function profileFromRow(row: ProfileRow, avatarUrl?: string): CloudProfile {
  return {
    id: row.id,
    handle: row.handle,
    displayName: row.display_name,
    avatarPath: row.avatar_path || undefined,
    avatarUrl,
    bio: row.bio || undefined,
    instagramHandle: row.instagram_handle || undefined,
    aliases: Array.isArray(row.aliases) ? row.aliases : [],
  }
}

function fallbackProfile(id: string): CloudProfile {
  return {
    id,
    handle: "producer",
    displayName: "Producer",
    aliases: [],
  }
}

function snapshotProfile(id: string, handle: string | null, displayName: string | null): CloudProfile {
  const normalizedHandle = handle?.trim() || "producer"
  return {
    id,
    handle: normalizedHandle,
    displayName: displayName?.trim() || `@${normalizedHandle}`,
    aliases: [],
  }
}

export function normalizeInstagramHandle(value: string): string {
  const raw = value.trim().replace(/^@/, "")
  if (!raw) return ""
  const fromUrl = raw.match(/^(?:https?:\/\/)?(?:www\.)?instagram\.com\/([^/?#]+)/i)?.[1]
  const handle = (fromUrl || raw).replace(/^@/, "").trim()
  if (!/^[a-z0-9._]{1,30}$/i.test(handle)) {
    throw new Error("Use an Instagram username, for example nrgyloops.")
  }
  return handle
}

export function normalizeAliases(values: string[]): string[] {
  const aliases: string[] = []
  const seen = new Set<string>()
  for (const raw of values) {
    const alias = String(raw || "").trim().replace(/\s+/g, " ")
    const key = alias.normalize("NFKC").replace(/^@/, "").toLocaleLowerCase()
    if (!alias || seen.has(key)) continue
    if (alias.length > 64) throw new Error("Each producer alias must contain 64 characters or fewer.")
    seen.add(key)
    aliases.push(alias)
  }
  if (aliases.length > 12) throw new Error("Keep up to 12 producer aliases on one profile.")
  return aliases
}

export function profileAvatarCropRect(width: number, height: number): { x: number; y: number; width: number; height: number } {
  const edge = Math.max(1, Math.min(Math.floor(width), Math.floor(height)))
  return {
    x: Math.max(0, Math.floor((width - edge) / 2)),
    y: Math.max(0, Math.floor((height - edge) / 2)),
    width: edge,
    height: edge,
  }
}

export function chunkCloudObjectPaths(paths: string[], batchSize = STORAGE_DELETE_BATCH_SIZE): string[][] {
  if (!Number.isInteger(batchSize) || batchSize < 1) throw new Error("The Cloud deletion batch size is invalid.")
  const batches: string[][] = []
  for (let index = 0; index < paths.length; index += batchSize) {
    batches.push(paths.slice(index, index + batchSize))
  }
  return batches
}

export function canonicalizeCloudProducerCredits(producers: string[], owner?: CloudProfile): string[] {
  const identityKey = (value: string) => value.normalize("NFKC").trim().replace(/^@/, "").replace(/\s+/g, " ").toLocaleLowerCase()
  const ownerIdentityKeys = new Set([
    owner?.displayName,
    owner?.handle,
    ...(owner?.aliases ?? []),
  ].filter((item): item is string => Boolean(item)).map(identityKey))
  return [...new Set(producers.map((producer) => (
    owner && ownerIdentityKeys.has(identityKey(producer))
      ? owner.displayName
      : producer.trim()
  )).filter(Boolean))]
}

export function cloudErrorMessage(error: unknown, fallback = "The Cloud request failed."): string {
  const rawMessage = error instanceof Error
    ? error.message
    : error && typeof error === "object" && "message" in error
      ? String(error.message)
      : ""
  const message = rawMessage.trim()
  return message && !/^(?:<none>|none|null|undefined)$/i.test(message) ? message : fallback
}

function isInvalidRefreshSession(error: unknown): boolean {
  if (!error || typeof error !== "object") return false
  const code = "code" in error ? String(error.code) : ""
  const message = "message" in error ? String(error.message) : ""
  return code === "refresh_token_not_found"
    || code === "refresh_token_already_used"
    || /refresh token (?:not found|already used)/i.test(message)
}

function validateConfiguration(request: ConfigureCloudRequest): ConfigureCloudRequest {
  const projectUrl = request.projectUrl.trim().replace(/\/+$/, "")
  const publishableKey = request.publishableKey.trim()
  let parsed: URL
  try {
    parsed = new URL(projectUrl)
  } catch {
    throw new Error("Enter a valid Supabase project URL.")
  }
  const localDevelopment = parsed.hostname === "localhost" || parsed.hostname === "127.0.0.1"
  if (parsed.protocol !== "https:" && !localDevelopment) {
    throw new Error("The Supabase project URL must use HTTPS.")
  }
  if (!localDevelopment && !parsed.hostname.endsWith(".supabase.co")) {
    throw new Error("This does not look like a Supabase project URL.")
  }
  if (!publishableKey.startsWith("sb_publishable_") && publishableKey.split(".").length !== 3) {
    throw new Error("Enter the project's publishable key, never its secret key.")
  }
  if (publishableKey.startsWith("sb_secret_")) {
    throw new Error("A Supabase secret key must never be stored in the desktop application.")
  }
  return { projectUrl, publishableKey }
}

export function loadCloudBootstrapConfiguration(configurationPath?: string): ConfigureCloudRequest | null {
  if (!configurationPath || !existsSync(configurationPath)) return null
  try {
    const parsed = JSON.parse(readFileSync(configurationPath, "utf8")) as Partial<ConfigureCloudRequest>
    if (typeof parsed.projectUrl !== "string" || typeof parsed.publishableKey !== "string") return null
    return validateConfiguration({
      projectUrl: parsed.projectUrl,
      publishableKey: parsed.publishableKey,
    })
  } catch {
    return null
  }
}

class EncryptedAuthStorage {
  private readonly memory = new Map<string, string>()

  constructor(private readonly filePath: string) {}

  private load(): Record<string, string> {
    if (!safeStorage.isEncryptionAvailable() || !existsSync(this.filePath)) return {}
    try {
      const encrypted = Buffer.from(readFileSync(this.filePath, "utf8"), "base64")
      return JSON.parse(safeStorage.decryptString(encrypted)) as Record<string, string>
    } catch {
      return {}
    }
  }

  private save(values: Record<string, string>): void {
    if (!safeStorage.isEncryptionAvailable()) return
    mkdirSync(path.dirname(this.filePath), { recursive: true })
    const encrypted = safeStorage.encryptString(JSON.stringify(values)).toString("base64")
    writeFileSync(this.filePath, encrypted, { mode: 0o600 })
  }

  async getItem(key: string): Promise<string | null> {
    return this.memory.get(key) ?? this.load()[key] ?? null
  }

  async setItem(key: string, value: string): Promise<void> {
    this.memory.set(key, value)
    this.save({ ...this.load(), [key]: value })
  }

  async removeItem(key: string): Promise<void> {
    this.memory.delete(key)
    const values = this.load()
    delete values[key]
    this.save(values)
  }

  async clear(): Promise<void> {
    this.memory.clear()
    this.save({})
  }
}

async function parallelMap<T>(items: T[], concurrency: number, task: (item: T, index: number) => Promise<void>): Promise<void> {
  let nextIndex = 0
  let firstError: unknown
  const workers = Array.from({ length: Math.min(concurrency, items.length) }, async () => {
    while (firstError === undefined && nextIndex < items.length) {
      const index = nextIndex
      nextIndex += 1
      try {
        await task(items[index], index)
      } catch (error) {
        if (firstError === undefined) firstError = error
        return
      }
    }
  })
  await Promise.all(workers)
  if (firstError !== undefined) throw firstError
}

export function cloudUploadConcurrency(byteSizes: number[]): number {
  const allLayersUseStandardUploadFastPath = byteSizes.length > 0 && byteSizes.every((byteSize) => (
    Number.isFinite(byteSize) && byteSize >= 0 && byteSize <= STANDARD_UPLOAD_FAST_PATH_LIMIT
  ))
  return allLayersUseStandardUploadFastPath ? SMALL_LAYER_UPLOAD_CONCURRENCY : DEFAULT_UPLOAD_CONCURRENCY
}

function activityAudioCacheSidecarPath(audioPath: string): string {
  return `${audioPath}${CLOUD_ACTIVITY_CACHE_SIDECAR_SUFFIX}`
}

function readActivityAudioCacheSidecar(sidecarPath: string): ActivityAudioCacheSidecar | null {
  try {
    const parsed = JSON.parse(readFileSync(sidecarPath, "utf8")) as Partial<ActivityAudioCacheSidecar>
    if (
      parsed.version !== 1
      || typeof parsed.audioFileName !== "string"
      || !parsed.audioFileName
      || path.basename(parsed.audioFileName) !== parsed.audioFileName
      || typeof parsed.sha256 !== "string"
      || !/^[0-9a-f]{64}$/.test(parsed.sha256)
      || typeof parsed.expiresAt !== "string"
      || !Number.isFinite(new Date(parsed.expiresAt).getTime())
    ) return null
    return parsed as ActivityAudioCacheSidecar
  } catch {
    return null
  }
}

function writeActivityAudioCacheSidecar(audioPath: string, sha256: string, expiresAt: string): void {
  const sidecarPath = activityAudioCacheSidecarPath(audioPath)
  const existing = existsSync(sidecarPath) ? readActivityAudioCacheSidecar(sidecarPath) : null
  const requestedExpiry = new Date(expiresAt).getTime()
  if (!Number.isFinite(requestedExpiry)) return
  const existingExpiry = existing ? new Date(existing.expiresAt).getTime() : 0
  const retainedExpiry = Math.max(requestedExpiry, existingExpiry)
  const sidecar: ActivityAudioCacheSidecar = {
    version: 1,
    audioFileName: path.basename(audioPath),
    sha256,
    expiresAt: new Date(retainedExpiry).toISOString(),
  }
  writeFileSync(sidecarPath, JSON.stringify(sidecar), { mode: 0o600 })
}

export function expiredActivityAudioCacheEntries(
  cacheRoot: string,
  now = Date.now(),
): ExpiredActivityAudioCacheEntry[] {
  if (!existsSync(cacheRoot) || !statSync(cacheRoot).isDirectory()) return []
  const resolvedRoot = path.resolve(cacheRoot)
  return readdirSync(resolvedRoot, { withFileTypes: true }).flatMap((entry) => {
    if (!entry.isFile() || !entry.name.endsWith(CLOUD_ACTIVITY_CACHE_SIDECAR_SUFFIX)) return []
    const sidecarPath = path.join(resolvedRoot, entry.name)
    const sidecar = readActivityAudioCacheSidecar(sidecarPath)
    if (!sidecar || new Date(sidecar.expiresAt).getTime() > now) return []
    const audioPath = path.resolve(resolvedRoot, sidecar.audioFileName)
    if (path.dirname(audioPath) !== resolvedRoot) return []
    return [{ audioPath, sidecarPath }]
  })
}

function sameExportBinding(
  left: CloudExportOutboxBinding | null,
  right: CloudExportOutboxBinding | null,
): boolean {
  return Boolean(left && right && left.projectUrl === right.projectUrl && left.userId === right.userId)
}

export class CloudService {
  private readonly settingsPath: string
  private readonly sessionPath: string
  private readonly alphaCredentialsPath: string
  private readonly audioCacheRoot: string
  private readonly exportAudioCacheRoot: string
  private readonly authStorage: EncryptedAuthStorage
  private readonly exportOutbox: CloudExportOutbox
  private settings: CloudLocalSettings
  private client: SupabaseClient | null = null
  private realtimeChannel: RealtimeChannel | null = null
  private realtimeClient: SupabaseClient | null = null
  private realtimeUserId = ""
  private realtimeReconnectTimer: ReturnType<typeof setTimeout> | null = null
  private realtimeOperation: Promise<void> = Promise.resolve()
  private activeExportBinding: CloudExportOutboxBinding | null = null
  private exportFlushPromise: Promise<void> | null = null
  private exportFlushTimer: ReturnType<typeof setTimeout> | null = null
  private exportFlushAt = 0
  private exportSnapshotCleanupPromise: Promise<void> | null = null
  private activityAudioCachePurgePromise: Promise<void> | null = null
  private readonly syncListeners = new Set<SyncListener>()
  private readonly libraryCategoryCache = new Map<string, { signature: string; categories: Array<{ name: string; count: number }> }>()
  private readonly remoteLayerCache = new Map<string, { signature: string; rows: RemoteLayerRow[] }>()

  constructor(
    private readonly acceptedCachePath: string,
    appCachePath: string,
    private readonly bootstrapConfigurationPath?: string,
  ) {
    const root = path.join(appCachePath, "cloud")
    this.settingsPath = path.join(root, "settings.json")
    this.sessionPath = path.join(root, "session.enc")
    this.alphaCredentialsPath = path.join(root, "alpha-test-credentials.json")
    this.audioCacheRoot = path.join(root, "audio")
    this.exportAudioCacheRoot = path.join(root, "activity-audio")
    this.authStorage = new EncryptedAuthStorage(this.sessionPath)
    this.exportOutbox = new CloudExportOutbox(path.join(root, "export-outbox.sqlite3"))
    this.exportOutbox.resetInterrupted()
    this.settings = this.loadSettings()
  }

  onSync(listener: SyncListener): () => void {
    this.syncListeners.add(listener)
    return () => this.syncListeners.delete(listener)
  }

  private emitSync(event: CloudSyncEvent): void {
    for (const listener of this.syncListeners) listener(event)
  }

  private bindingForSession(session: Session): CloudExportOutboxBinding {
    const projectUrl = this.settings.projectUrl?.trim().replace(/\/+$/, "") ?? ""
    if (!projectUrl) throw new Error("Connect a Supabase project before using Cloud.")
    return { projectUrl, userId: session.user.id }
  }

  private activateExportBinding(session: Session): CloudExportOutboxBinding {
    const binding = this.bindingForSession(session)
    if (sameExportBinding(this.activeExportBinding, binding)) return binding
    if (this.exportFlushTimer) clearTimeout(this.exportFlushTimer)
    this.exportFlushTimer = null
    this.exportFlushAt = 0
    this.activeExportBinding = binding
    this.scheduleExportFlush(0)
    void this.cleanupCompletedExportSnapshots(binding)
    return binding
  }

  private deactivateExportBinding(): void {
    if (this.exportFlushTimer) clearTimeout(this.exportFlushTimer)
    this.exportFlushTimer = null
    this.exportFlushAt = 0
    this.activeExportBinding = null
  }

  private requireActiveExportBinding(binding: CloudExportOutboxBinding): void {
    if (!sameExportBinding(this.activeExportBinding, binding)) {
      throw new ExportBindingChangedError("The Cloud account changed before this export could be synchronized.")
    }
  }

  private cleanupCompletedExportSnapshots(binding: CloudExportOutboxBinding): Promise<void> {
    const previous = this.exportSnapshotCleanupPromise ?? Promise.resolve()
    const cleanup = previous.catch(() => undefined).then(async () => {
      for (const entry of this.exportOutbox.completed(binding, 100)) {
        let cleaned = true
        const snapshotPath = entry.request.masterPath
        if (this.exportOutbox.isManagedSnapshot(snapshotPath) && existsSync(snapshotPath)) {
          try {
            await shell.trashItem(snapshotPath)
          } catch {
            cleaned = false
          }
        }
        if (!cleaned) continue
        this.exportOutbox.removeCompleted(binding, entry.clientEventId)
      }
    })
    this.exportSnapshotCleanupPromise = cleanup
    return cleanup.finally(() => {
      if (this.exportSnapshotCleanupPromise === cleanup) this.exportSnapshotCleanupPromise = null
    })
  }

  private purgeExpiredActivityAudioCache(now = Date.now()): Promise<void> {
    const previous = this.activityAudioCachePurgePromise ?? Promise.resolve()
    const purge = previous.catch(() => undefined).then(async () => {
      for (const entry of expiredActivityAudioCacheEntries(this.exportAudioCacheRoot, now)) {
        try {
          if (existsSync(entry.audioPath)) await shell.trashItem(entry.audioPath)
          if (existsSync(entry.sidecarPath)) await shell.trashItem(entry.sidecarPath)
        } catch {
          // Cache cleanup must never make a playable Cloud activity unavailable.
        }
      }
    })
    this.activityAudioCachePurgePromise = purge
    return purge.finally(() => {
      if (this.activityAudioCachePurgePromise === purge) this.activityAudioCachePurgePromise = null
    })
  }

  async dispose(): Promise<void> {
    this.deactivateExportBinding()
    await this.stopRealtime()
    await this.exportFlushPromise?.catch(() => undefined)
    await this.exportSnapshotCleanupPromise?.catch(() => undefined)
    await this.activityAudioCachePurgePromise?.catch(() => undefined)
    this.exportOutbox.close()
  }

  private loadSettings(): CloudLocalSettings {
    let stored: CloudLocalSettings = {}
    try {
      stored = JSON.parse(readFileSync(this.settingsPath, "utf8")) as CloudLocalSettings
    } catch {
      stored = {}
    }
    const storedConfiguration = typeof stored.projectUrl === "string" && typeof stored.publishableKey === "string"
      ? { projectUrl: stored.projectUrl, publishableKey: stored.publishableKey }
      : null
    const configuration = storedConfiguration ?? loadCloudBootstrapConfiguration(this.bootstrapConfigurationPath)
    return {
      ...(configuration ?? {}),
      enabledLibraryIds: Array.isArray(stored.enabledLibraryIds) ? stored.enabledLibraryIds.filter((item): item is string => typeof item === "string") : [],
      pendingProfiles: stored.pendingProfiles && typeof stored.pendingProfiles === "object" ? stored.pendingProfiles : {},
    }
  }

  private saveSettings(): void {
    mkdirSync(path.dirname(this.settingsPath), { recursive: true })
    writeFileSync(this.settingsPath, JSON.stringify(this.settings, null, 2), { mode: 0o600 })
  }

  private supabase(): SupabaseClient {
    if (this.client) return this.client
    if (!this.settings.projectUrl || !this.settings.publishableKey) {
      throw new Error("Connect a Supabase project before using Cloud.")
    }
    this.client = createClient(this.settings.projectUrl, this.settings.publishableKey, {
      auth: {
        storage: this.authStorage,
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: false,
      },
    })
    return this.client
  }

  private clearRealtimeReconnect(): void {
    if (!this.realtimeReconnectTimer) return
    clearTimeout(this.realtimeReconnectTimer)
    this.realtimeReconnectTimer = null
  }

  private serializeRealtime(operation: () => Promise<void>): Promise<void> {
    const pending = this.realtimeOperation.then(operation, operation)
    this.realtimeOperation = pending.catch(() => undefined)
    return pending
  }

  private async removeRealtimeChannel(): Promise<void> {
    const client = this.realtimeClient
    const channel = this.realtimeChannel
    this.realtimeClient = null
    this.realtimeChannel = null
    this.realtimeUserId = ""
    if (channel && client) await client.removeChannel(channel)
  }

  private stopRealtime(): Promise<void> {
    this.clearRealtimeReconnect()
    return this.serializeRealtime(() => this.removeRealtimeChannel())
  }

  private scheduleRealtimeReconnect(binding: CloudExportOutboxBinding): void {
    if (this.realtimeReconnectTimer || !binding.userId) return
    this.realtimeReconnectTimer = setTimeout(() => {
      this.realtimeReconnectTimer = null
      if (!sameExportBinding(this.activeExportBinding, binding) || this.realtimeUserId !== binding.userId) return
      void this.ensureRealtime(binding.userId, true).catch((error) => this.emitSync({
        kind: "activity-error",
        error: cloudErrorMessage(error, "Cloud live updates could not reconnect."),
      }))
    }, 5_000)
  }

  private ensureRealtime(userId: string, replace = false): Promise<void> {
    if (!userId) return Promise.resolve()
    return this.serializeRealtime(async () => {
      const binding = this.activeExportBinding
      if (!binding || binding.userId !== userId) return
      if (!replace && this.realtimeChannel && this.realtimeUserId === userId) return
      this.clearRealtimeReconnect()
      await this.removeRealtimeChannel()
      if (!sameExportBinding(this.activeExportBinding, binding)) return

      const client = this.supabase()
      const channel = client
        .channel(`slicer-cloud-${userId}`)
        .on(
          "postgres_changes",
          { event: "INSERT", schema: "public", table: "cloud_export_recipients", filter: `recipient_id=eq.${userId}` },
          (payload) => this.emitSync({ kind: "activity", activityId: String((payload.new as { event_id?: unknown }).event_id ?? "") || undefined }),
        )
        .on(
          "postgres_changes",
          { event: "UPDATE", schema: "public", table: "cloud_export_events" },
          (payload) => this.emitSync({ kind: "activity-audio", activityId: String((payload.new as { id?: unknown }).id ?? "") || undefined }),
        )

      this.realtimeClient = client
      this.realtimeUserId = userId
      this.realtimeChannel = channel
      channel.subscribe((status) => {
        if (
          this.realtimeChannel !== channel
          || this.realtimeUserId !== userId
          || !sameExportBinding(this.activeExportBinding, binding)
        ) return
        if (status === "SUBSCRIBED") {
          this.clearRealtimeReconnect()
          this.emitSync({ kind: "activity" })
          void this.flushExportOutbox()
        } else if (status === "CHANNEL_ERROR" || status === "TIMED_OUT" || status === "CLOSED") {
          this.scheduleRealtimeReconnect(binding)
        }
      })
    })
  }

  private alphaCredentials(): AlphaCredentialsFile | null {
    if (!this.settings.projectUrl || !existsSync(this.alphaCredentialsPath)) return null
    try {
      const credentials = JSON.parse(readFileSync(this.alphaCredentialsPath, "utf8")) as AlphaCredentialsFile
      const projectRef = new URL(this.settings.projectUrl).hostname.split(".")[0]
      return credentials.projectRef === projectRef ? credentials : null
    } catch {
      return null
    }
  }

  private cloudProfile(row: ProfileRow): CloudProfile {
    const publicUrl = row.avatar_path
      ? this.supabase().storage.from(PROFILE_AVATAR_BUCKET).getPublicUrl(row.avatar_path).data.publicUrl
      : undefined
    const avatarUrl = publicUrl
      ? `${publicUrl}?revision=${encodeURIComponent(row.updated_at)}`
      : undefined
    return profileFromRow(row, avatarUrl)
  }

  private testAccounts(): CloudTestAccount[] {
    const accounts = this.alphaCredentials()?.accounts ?? {}
    return Object.entries(accounts).flatMap(([id, account]) => (
      typeof account.email === "string"
      && typeof account.password === "string"
      && typeof account.handle === "string"
      && typeof account.displayName === "string"
        ? [{ id, handle: account.handle, displayName: account.displayName }]
        : []
    ))
  }

  async configure(request: ConfigureCloudRequest): Promise<CloudState> {
    const configuration = validateConfiguration(request)
    this.deactivateExportBinding()
    await this.stopRealtime()
    this.settings = { ...this.settings, ...configuration }
    this.saveSettings()
    this.client = null
    return this.getState()
  }

  private async currentSession(): Promise<Session> {
    const { data, error } = await this.supabase().auth.getSession()
    if (error) throw error
    if (!data.session) throw new Error("Sign in to Cloud first.")
    this.activateExportBinding(data.session)
    return data.session
  }

  async refreshSession(): Promise<void> {
    const { error } = await this.supabase().auth.refreshSession()
    if (error) throw error
  }

  private async ensureProfile(session: Session, requested?: { handle: string; displayName: string }): Promise<CloudProfile> {
    const client = this.supabase()
    const existing = await client
      .from("profiles")
      .select(PROFILE_COLUMNS)
      .eq("id", session.user.id)
      .maybeSingle<ProfileRow>()
    if (existing.error) throw existing.error
    if (existing.data) return this.cloudProfile(existing.data)

    const email = session.user.email?.toLowerCase() ?? ""
    const pending = requested ?? this.settings.pendingProfiles?.[email]
    const fallbackHandle = normalizeCloudHandle(email.split("@")[0] || `producer-${session.user.id.slice(0, 8)}`)
    const handle = normalizeCloudHandle(pending?.handle || fallbackHandle).slice(0, 32)
    assertValidCloudHandle(handle)
    const displayName = (pending?.displayName || handle).trim().slice(0, 64)
    const inserted = await client
      .from("profiles")
      .insert({ id: session.user.id, handle, display_name: displayName })
      .select(PROFILE_COLUMNS)
      .single<ProfileRow>()
    if (inserted.error) throw inserted.error
    return this.cloudProfile(inserted.data)
  }

  async signUp(request: CloudSignUpRequest): Promise<CloudState> {
    const email = request.email.trim().toLowerCase()
    const handle = normalizeCloudHandle(request.handle)
    const displayName = request.displayName.trim()
    assertValidCloudHandle(handle)
    if (!displayName) throw new Error("Enter the producer name shown to collaborators.")
    this.settings.pendingProfiles = {
      ...(this.settings.pendingProfiles ?? {}),
      [email]: { handle, displayName },
    }
    this.saveSettings()
    const { data, error } = await this.supabase().auth.signUp({
      email,
      password: request.password,
      options: { data: { handle, display_name: displayName } },
    })
    if (error) throw error
    if (data.session) await this.ensureProfile(data.session, { handle, displayName })
    const state = await this.getState()
    return data.session ? state : {
      ...state,
      message: "Account created. Confirm the email, then sign in.",
    }
  }

  async signIn(request: CloudCredentialsRequest): Promise<CloudState> {
    this.deactivateExportBinding()
    await this.stopRealtime()
    const { data, error } = await this.supabase().auth.signInWithPassword({
      email: request.email.trim().toLowerCase(),
      password: request.password,
    })
    if (error) throw error
    await this.ensureProfile(data.session)
    return this.getState()
  }

  async signInTestAccount(accountId: string): Promise<CloudState> {
    const account = this.alphaCredentials()?.accounts?.[accountId]
    if (!account || typeof account.email !== "string" || typeof account.password !== "string") {
      throw new Error("This local alpha account is unavailable.")
    }
    return this.signIn({ email: account.email, password: account.password })
  }

  async signOut(): Promise<CloudState> {
    this.deactivateExportBinding()
    await this.stopRealtime()
    if (this.client) {
      const { error } = await this.client.auth.signOut({ scope: "local" })
      if (error) throw error
    }
    return this.getState()
  }

  async updateProfile(request: CloudProfileUpdateRequest): Promise<CloudState> {
    const session = await this.currentSession()
    const handle = normalizeCloudHandle(request.handle)
    const displayName = request.displayName.trim().replace(/\s+/g, " ")
    const bio = request.bio.trim().replace(/\s+/g, " ")
    const instagramHandle = normalizeInstagramHandle(request.instagramHandle)
    const aliases = normalizeAliases(request.aliases)

    assertValidCloudHandle(handle)
    if (!displayName || displayName.length > 64) throw new Error("Use a producer name between 1 and 64 characters.")
    if (bio.length > 280) throw new Error("Keep the profile bio within 280 characters.")

    let avatarPath: string | undefined
    if (request.avatarFilePath) {
      const sourceBytes = await readFile(request.avatarFilePath)
      if (sourceBytes.length === 0 || sourceBytes.length > PROFILE_AVATAR_SOURCE_LIMIT) {
        throw new Error("Choose a profile image smaller than 25 MB.")
      }
      const sourceImage = nativeImage.createFromPath(request.avatarFilePath)
      if (sourceImage.isEmpty()) throw new Error("Slicer could not read this profile image.")
      const sourceSize = sourceImage.getSize()
      const avatarBytes = sourceImage
        .crop(profileAvatarCropRect(sourceSize.width, sourceSize.height))
        .resize({ width: PROFILE_AVATAR_EDGE, height: PROFILE_AVATAR_EDGE, quality: "best" })
        .toPNG()
      if (avatarBytes.length === 0 || avatarBytes.length > PROFILE_AVATAR_UPLOAD_LIMIT) {
        throw new Error("Slicer could not prepare this profile image for Cloud upload.")
      }
      avatarPath = `${session.user.id}/avatar.png`
      const uploaded = await this.supabase().storage
        .from(PROFILE_AVATAR_BUCKET)
        .upload(avatarPath, avatarBytes, {
          cacheControl: "3600",
          contentType: "image/png",
          upsert: true,
        })
      if (uploaded.error) throw uploaded.error
    }

    const update: Record<string, unknown> = {
      handle,
      display_name: displayName,
      bio: bio || null,
      instagram_handle: instagramHandle || null,
      aliases,
    }
    if (avatarPath) update.avatar_path = avatarPath

    const updated = await this.supabase()
      .from("profiles")
      .update(update)
      .eq("id", session.user.id)
      .select(PROFILE_COLUMNS)
      .single<ProfileRow>()
    if (updated.error) throw updated.error
    return {
      ...(await this.getState()),
      profile: this.cloudProfile(updated.data),
      message: "Cloud profile saved.",
    }
  }

  async connect(handleValue: string): Promise<CloudState> {
    const session = await this.currentSession()
    const handle = normalizeCloudHandle(handleValue)
    const target = await this.supabase()
      .from("profiles")
      .select(PROFILE_COLUMNS)
      .eq("handle", handle)
      .maybeSingle<ProfileRow>()
    if (target.error) throw target.error
    if (!target.data) throw new Error(`No Cloud profile uses @${handle}.`)
    if (target.data.id === session.user.id) throw new Error("You cannot connect your profile to itself.")
    const inserted = await this.supabase().from("connections").insert({
      requester_id: session.user.id,
      addressee_id: target.data.id,
      status: "pending",
    })
    if (inserted.error) throw inserted.error
    return this.getState()
  }

  async acceptConnection(connectionId: string): Promise<CloudState> {
    await this.currentSession()
    const updated = await this.supabase()
      .from("connections")
      .update({ status: "accepted" })
      .eq("id", connectionId)
    if (updated.error) throw updated.error
    return this.getState()
  }

  async removeConnection(connectionId: string): Promise<CloudState> {
    const session = await this.currentSession()
    const connectionResponse = await this.supabase()
      .from("connections")
      .select("id,requester_id,addressee_id,status,created_at")
      .eq("id", connectionId)
      .maybeSingle<ConnectionRow>()
    if (connectionResponse.error) throw connectionResponse.error
    const connection = connectionResponse.data
    if (!connection || (connection.requester_id !== session.user.id && connection.addressee_id !== session.user.id)) {
      throw new Error("This trusted producer connection is unavailable.")
    }
    const otherProducerId = connection.requester_id === session.user.id
      ? connection.addressee_id
      : connection.requester_id
    const remoteLibraries = await this.supabase()
      .from("cloud_libraries")
      .select("id")
      .eq("owner_id", otherProducerId)
    if (remoteLibraries.error) throw remoteLibraries.error
    const clearedBlocks = await this.supabase()
      .from("cloud_library_blocks")
      .delete()
      .eq("producer_id", otherProducerId)
    if (clearedBlocks.error) throw clearedBlocks.error
    const deleted = await this.supabase()
      .from("connections")
      .delete()
      .eq("id", connection.id)
      .select("id")
      .maybeSingle<{ id: string }>()
    if (deleted.error) throw deleted.error
    if (!deleted.data) throw new Error("The trusted producer connection could not be removed.")

    const enabledIds = new Set(this.settings.enabledLibraryIds ?? [])
    for (const library of remoteLibraries.data as Array<{ id: string }>) enabledIds.delete(library.id)
    this.settings.enabledLibraryIds = [...enabledIds]
    this.saveSettings()
    return {
      ...(await this.getState()),
      message: "Trusted producer removed. Shared libraries are no longer available.",
    }
  }

  async setLibraryEnabled(libraryId: string, enabled: boolean): Promise<CloudState> {
    const ids = new Set(this.settings.enabledLibraryIds ?? [])
    if (enabled) ids.add(libraryId)
    else ids.delete(libraryId)
    this.settings.enabledLibraryIds = [...ids]
    this.saveSettings()
    return this.getState()
  }

  private async ownedLibrary(libraryId: string, ownerId: string): Promise<LibraryRow> {
    const response = await this.supabase()
      .from("cloud_libraries")
      .select("id,owner_id,name,status,layer_count,loop_count,total_bytes,updated_at")
      .eq("id", libraryId)
      .eq("owner_id", ownerId)
      .maybeSingle<LibraryRow>()
    if (response.error) throw response.error
    if (!response.data) throw new Error("This Cloud library is unavailable or belongs to another producer.")
    return response.data
  }

  async setLibrarySharing(libraryId: string, sharing: boolean): Promise<CloudState> {
    const session = await this.currentSession()
    const library = await this.ownedLibrary(libraryId, session.user.id)
    const nextStatus = sharing ? "ready" : "archived"
    if (library.status === nextStatus) {
      return {
        ...(await this.getState()),
        message: sharing ? `${library.name} is already shared.` : `${library.name} sharing is already paused.`,
      }
    }
    const expectedStatus = sharing ? "archived" : "ready"
    if (library.status !== expectedStatus) {
      throw new Error(sharing
        ? "Only a paused Cloud library can resume sharing."
        : "Wait for this Cloud library to finish publishing before pausing sharing.")
    }
    const updated = await this.supabase()
      .from("cloud_libraries")
      .update({ status: nextStatus })
      .eq("id", library.id)
      .eq("owner_id", session.user.id)
      .eq("status", expectedStatus)
      .select("id")
      .maybeSingle<{ id: string }>()
    if (updated.error) throw updated.error
    if (!updated.data) throw new Error("The Cloud library changed before sharing could be updated. Refresh and try again.")
    return {
      ...(await this.getState()),
      message: sharing
        ? `${library.name} is available to connected producers again.`
        : `${library.name} sharing is paused. Cloud files remain stored.`,
    }
  }

  async setLibraryProducerAccess(libraryId: string, producerId: string, allowed: boolean): Promise<CloudState> {
    const session = await this.currentSession()
    const library = await this.ownedLibrary(libraryId, session.user.id)
    if (producerId === session.user.id) throw new Error("The library owner always has access.")
    const connections = await this.supabase()
      .from("connections")
      .select("requester_id,addressee_id,status")
      .eq("status", "accepted")
    if (connections.error) throw connections.error
    const connected = (connections.data as Array<Pick<ConnectionRow, "requester_id" | "addressee_id" | "status">>).some((connection) => (
      (connection.requester_id === session.user.id && connection.addressee_id === producerId)
      || (connection.requester_id === producerId && connection.addressee_id === session.user.id)
    ))
    if (!connected) throw new Error("Only trusted producers can receive library access.")

    if (allowed) {
      const removed = await this.supabase()
        .from("cloud_library_blocks")
        .delete()
        .eq("library_id", library.id)
        .eq("producer_id", producerId)
      if (removed.error) throw removed.error
    } else {
      const blocked = await this.supabase()
        .from("cloud_library_blocks")
        .insert({ library_id: library.id, producer_id: producerId })
      if (blocked.error && blocked.error.code !== "23505") throw blocked.error
    }
    return {
      ...(await this.getState()),
      message: allowed
        ? `${library.name} is available to this producer.`
        : `${library.name} is hidden from this producer.`,
    }
  }

  private async cataloguedLibraryObjectPaths(libraryId: string): Promise<string[]> {
    const paths: string[] = []
    for (let start = 0; ; start += CATALOG_PAGE_SIZE) {
      const response = await this.supabase()
        .from("cloud_layers")
        .select("object_path")
        .eq("library_id", libraryId)
        .order("object_path")
        .range(start, start + CATALOG_PAGE_SIZE - 1)
      if (response.error) throw response.error
      const page = response.data as Array<{ object_path: string }>
      paths.push(...page.map((row) => row.object_path))
      if (page.length < CATALOG_PAGE_SIZE) break
    }
    return paths
  }

  private async storedLibraryObjectPaths(libraryId: string, ownerId: string): Promise<string[]> {
    const prefix = `${ownerId}/${libraryId}`
    const paths: string[] = []
    for (let offset = 0; ; offset += STORAGE_LIST_PAGE_SIZE) {
      const response = await this.supabase().storage.from(CLOUD_BUCKET).list(prefix, {
        limit: STORAGE_LIST_PAGE_SIZE,
        offset,
        sortBy: { column: "name", order: "asc" },
      })
      if (response.error) throw response.error
      paths.push(...response.data
        .filter((object) => object.name !== ".emptyFolderPlaceholder")
        .map((object) => `${prefix}/${object.name}`))
      if (response.data.length < STORAGE_LIST_PAGE_SIZE) break
    }
    return paths
  }

  private async libraryObjectPaths(libraryId: string, ownerId: string): Promise<string[]> {
    const [catalogued, stored] = await Promise.all([
      this.cataloguedLibraryObjectPaths(libraryId),
      this.storedLibraryObjectPaths(libraryId, ownerId),
    ])
    return [...new Set([...catalogued, ...stored])]
  }

  async removeLibrary(libraryId: string): Promise<CloudState> {
    const session = await this.currentSession()
    const library = await this.ownedLibrary(libraryId, session.user.id)
    if (library.status === "uploading") {
      throw new Error("Wait for this Cloud library to finish publishing before removing it.")
    }
    if (library.status !== "archived") {
      const paused = await this.supabase()
        .from("cloud_libraries")
        .update({ status: "archived" })
        .eq("id", library.id)
        .eq("owner_id", session.user.id)
      if (paused.error) throw paused.error
    }
    try {
      const objectPaths = await this.libraryObjectPaths(library.id, session.user.id)
      for (const batch of chunkCloudObjectPaths(objectPaths)) {
        const removed = await this.supabase().storage.from(CLOUD_BUCKET).remove(batch)
        if (removed.error) throw removed.error
      }
      const deleted = await this.supabase()
        .from("cloud_libraries")
        .delete()
        .eq("id", library.id)
        .eq("owner_id", session.user.id)
        .select("id")
        .maybeSingle<{ id: string }>()
      if (deleted.error) throw deleted.error
      if (!deleted.data) throw new Error("The Cloud library could not be removed.")
    } catch (error) {
      throw new Error(`Sharing was paused, but Cloud removal did not finish. Try again. ${cloudErrorMessage(error)}`)
    }
    const enabledIds = new Set(this.settings.enabledLibraryIds ?? [])
    enabledIds.delete(library.id)
    this.settings.enabledLibraryIds = [...enabledIds]
    this.saveSettings()
    return {
      ...(await this.getState()),
      message: `${library.name} was removed from Cloud. The local folder is unchanged.`,
    }
  }

  private async profileRows(ids: string[]): Promise<Map<string, CloudProfile>> {
    if (ids.length === 0) return new Map()
    const response = await this.supabase()
      .from("profiles")
      .select(PROFILE_COLUMNS)
      .in("id", [...new Set(ids)])
    if (response.error) throw response.error
    return new Map((response.data as ProfileRow[]).map((row) => [row.id, this.cloudProfile(row)]))
  }

  queueTrackedExport(request: CloudTrackedDragRequest): string | undefined {
    const hasRecipient = request.layers.some((layer) => layer.triggered && layer.sourceOrigin === "cloud" && layer.cloudLayerId)
    if (!hasRecipient) return undefined
    const binding = this.activeExportBinding
    if (!binding) throw new Error("Sign in to Cloud before tracking this export.")
    if (!existsSync(request.masterPath) || !statSync(request.masterPath).isFile()) {
      throw new Error("The rendered master for this Cloud activity is unavailable.")
    }
    const clientEventId = this.exportOutbox.enqueue(binding, request)
    this.scheduleExportFlush(0)
    return clientEventId
  }

  private scheduleExportFlush(delayMs: number): void {
    if (!this.activeExportBinding) return
    const scheduledAt = Date.now() + Math.max(0, delayMs)
    if (this.exportFlushTimer && this.exportFlushAt <= scheduledAt) return
    if (this.exportFlushTimer) clearTimeout(this.exportFlushTimer)
    this.exportFlushAt = scheduledAt
    this.exportFlushTimer = setTimeout(() => {
      this.exportFlushTimer = null
      this.exportFlushAt = 0
      void this.flushExportOutbox()
    }, Math.max(0, scheduledAt - Date.now()))
  }

  async flushExportOutbox(): Promise<void> {
    if (this.exportFlushPromise) return this.exportFlushPromise
    const binding = this.activeExportBinding
    if (!binding) return
    const pending = (async () => {
      const items = this.exportOutbox.pending(binding, Date.now(), 8)
      for (const item of items) {
        if (!sameExportBinding(this.activeExportBinding, binding)) break
        this.exportOutbox.markSending(binding, item.clientEventId)
        try {
          await this.sendTrackedExport(binding, item.clientEventId, item.request)
          this.exportOutbox.markComplete(binding, item.clientEventId)
        } catch (error) {
          const message = cloudErrorMessage(error, "Cloud could not preserve this export yet.")
          const attempt = item.attempts + 1
          const retryDelay = Math.min(CLOUD_EXPORT_RETRY_MAX_MS, CLOUD_EXPORT_RETRY_BASE_MS * (2 ** Math.min(attempt, 6)))
          this.exportOutbox.markRetry(binding, item.clientEventId, message, Date.now() + retryDelay)
          if (!sameExportBinding(this.activeExportBinding, binding)) break
          this.emitSync({ kind: "activity-error", activityId: item.clientEventId, error: message })
          this.scheduleExportFlush(retryDelay)
          if (/Sign in to Cloud first/i.test(message)) break
        }
      }
    })()
    this.exportFlushPromise = pending
    try {
      await pending
    } finally {
      if (this.exportFlushPromise === pending) this.exportFlushPromise = null
      await this.cleanupCompletedExportSnapshots(binding)
      const activeBinding = this.activeExportBinding
      if (activeBinding) {
        const nextPendingAt = this.exportOutbox.nextPendingAt(activeBinding)
        if (nextPendingAt !== undefined) this.scheduleExportFlush(Math.max(0, nextPendingAt - Date.now()))
      }
    }
  }

  private async sendTrackedExport(
    binding: CloudExportOutboxBinding,
    clientEventId: string,
    request: CloudTrackedDragRequest,
  ): Promise<void> {
    this.requireActiveExportBinding(binding)
    const client = this.supabase()
    const sessionResponse = await client.auth.getSession()
    if (sessionResponse.error) throw sessionResponse.error
    const session = sessionResponse.data.session
    if (!session || session.user.id !== binding.userId || this.settings.projectUrl !== binding.projectUrl) {
      throw new Error("The queued Cloud export belongs to a different account or project.")
    }
    await this.ensureRealtime(session.user.id)
    this.requireActiveExportBinding(binding)
    const masterSha256 = await sha256File(request.masterPath)
    const fileStats = statSync(request.masterPath)
    const extension = path.extname(request.masterPath).toLocaleLowerCase()
    const mimeType = audioMimeType(request.masterPath)
    if (extension !== ".mp3" || mimeType !== "audio/mpeg") {
      throw new Error("Cloud activity requires the generated MP3 master.")
    }
    const proposedAssetId = randomUUID()
    const preparedAsset = await client.rpc("prepare_cloud_export_asset", {
      payload: {
        assetId: proposedAssetId,
        sha256: masterSha256,
        fileName: path.basename(request.masterPath),
        durationSeconds: Math.max(0, request.durationSeconds),
      },
    })
    if (preparedAsset.error) throw preparedAsset.error
    const assetResponse = await client
      .from("cloud_export_assets")
      .select("id,owner_id,sha256,object_path,mime_type,byte_size,duration_seconds,status,retain_until,error_message")
      .eq("id", String(preparedAsset.data))
      .single<CloudExportAssetRow>()
    if (assetResponse.error) throw assetResponse.error
    const asset = assetResponse.data

    const recorded = await client.rpc("record_cloud_export_event", {
      payload: {
        clientEventId,
        exportKind: request.exportKind,
        generatedLoopName: request.generatedLoopName,
        generationSeed: Math.trunc(request.generationSeed),
        targetBpm: Math.round(request.targetBpm),
        targetKey: request.targetKey,
        durationSeconds: Math.max(0, request.durationSeconds),
        layerCount: request.layers.length,
        assetId: asset.id,
        layers: request.layers.map((layer) => ({
          slotIndex: layer.slotIndex,
          sourceOrigin: layer.sourceOrigin,
          cloudLayerId: layer.cloudLayerId,
          sourceSha256: layer.sourceSha256,
          sourceLayerName: layer.sourceLayerName,
          sourceLoopId: layer.sourceLoopId,
          sourceLoopName: layer.sourceLoopName,
          category: layer.category,
          triggered: layer.triggered,
        })),
      },
    })
    if (recorded.error) throw recorded.error
    if (!recorded.data) return
    const activityId = String(recorded.data)
    this.emitSync({ kind: "activity", activityId })

    if (asset.status !== "available" || new Date(asset.retain_until).getTime() <= Date.now()) {
      try {
        this.requireActiveExportBinding(binding)
        const audio = await readFile(request.masterPath)
        this.requireActiveExportBinding(binding)
        const uploaded = await client.storage.from(CLOUD_EXPORT_BUCKET).upload(asset.object_path, audio, {
          contentType: mimeType,
          cacheControl: "3600",
          upsert: true,
        })
        if (uploaded.error) throw uploaded.error
        const completed = await client.rpc("complete_cloud_export_asset", {
          p_asset_id: asset.id,
          p_byte_size: fileStats.size,
          p_mime_type: mimeType,
        })
        if (completed.error) throw completed.error
      } catch (error) {
        if (error instanceof ExportBindingChangedError) throw error
        const message = cloudErrorMessage(error, "The generated master could not be uploaded.")
        const failed = await client.rpc("fail_cloud_export_asset", { p_asset_id: asset.id, p_error: message })
        if (failed.error) throw failed.error
        throw new Error(message, { cause: error })
      }
    }
    this.emitSync({ kind: "activity-audio", activityId })
  }

  async exportActivity(offset = 0): Promise<CloudExportActivity[]> {
    if (!Number.isSafeInteger(offset) || offset < 0) throw new Error("The Cloud activity page is invalid.")
    const session = await this.currentSession()
    await this.ensureRealtime(session.user.id)
    const recipientsResponse = await this.supabase()
      .from("cloud_export_recipients")
      .select("event_id,recipient_id,read_at")
      .eq("recipient_id", session.user.id)
      .order("created_at", { ascending: false })
      .range(offset, offset + CLOUD_EXPORT_ACTIVITY_LIMIT - 1)
    if (recipientsResponse.error) throw recipientsResponse.error
    const recipients = recipientsResponse.data as CloudExportRecipientRow[]
    if (recipients.length === 0) return []
    const recipientEventIds = recipients.map((recipient) => recipient.event_id)
    const eventsResponse = await this.supabase()
      .from("cloud_export_events")
      .select("id,client_event_id,created_by,creator_handle_snapshot,creator_display_name_snapshot,export_kind,generated_loop_name,generation_seed,target_bpm,target_key,layer_count,duration_seconds,asset_id,audio_status,audio_expires_at,audio_error,created_at")
      .in("id", recipientEventIds)
      .order("created_at", { ascending: false })
    if (eventsResponse.error) throw eventsResponse.error
    const events = eventsResponse.data as CloudExportEventRow[]
    if (events.length === 0) return []
    const eventIds = events.map((event) => event.id)
    const [sourcesResponse, assetsResponse] = await Promise.all([
      this.supabase().from("cloud_export_sources").select("event_id,slot_index,source_origin,source_owner_id,source_owner_handle_snapshot,source_owner_display_name_snapshot,source_sha256,source_layer_name,source_loop_id,source_loop_name,category,triggered").in("event_id", eventIds).order("slot_index", { ascending: true }),
      this.supabase().from("cloud_export_assets").select("id,owner_id,sha256,object_path,mime_type,byte_size,duration_seconds,status,retain_until,error_message").in("id", events.flatMap((event) => event.asset_id ? [event.asset_id] : [])),
    ])
    if (sourcesResponse.error) throw sourcesResponse.error
    if (assetsResponse.error) throw assetsResponse.error
    const sources = sourcesResponse.data as CloudExportSourceRow[]
    const assets = new Map((assetsResponse.data as CloudExportAssetRow[]).map((asset) => [asset.id, asset]))
    const profiles = await this.profileRows([
      ...events.map((event) => event.created_by),
      ...sources.flatMap((source) => source.source_owner_id ? [source.source_owner_id] : []),
    ])
    return events.map((event) => {
      const asset = event.asset_id ? assets.get(event.asset_id) : undefined
      const expired = Boolean(event.audio_expires_at && new Date(event.audio_expires_at).getTime() <= Date.now())
      const eventSources: CloudExportActivitySource[] = sources.filter((source) => source.event_id === event.id).map((source) => ({
        slotIndex: Number(source.slot_index),
        category: source.category,
        sourceLayerName: source.source_layer_name,
        sourceLoopId: source.source_loop_id,
        sourceLoopName: source.source_loop_name,
        sourceOrigin: source.source_origin,
        sourceOwner: source.source_owner_id
          ? profiles.get(source.source_owner_id)
            ?? snapshotProfile(source.source_owner_id, source.source_owner_handle_snapshot, source.source_owner_display_name_snapshot)
          : undefined,
        sourceSha256: source.source_sha256 || undefined,
        triggered: Boolean(source.triggered),
      }))
      const ownReceipt = recipients.find((recipient) => recipient.event_id === event.id && recipient.recipient_id === session.user.id)
      return {
        id: event.id,
        clientEventId: event.client_event_id,
        createdBy: profiles.get(event.created_by)
          ?? snapshotProfile(event.created_by, event.creator_handle_snapshot, event.creator_display_name_snapshot),
        exportKind: event.export_kind,
        generatedLoopName: event.generated_loop_name,
        generationSeed: Number(event.generation_seed),
        targetBpm: Number(event.target_bpm),
        targetKey: event.target_key,
        layerCount: Number(event.layer_count),
        recipientLayerCount: eventSources.filter((source) => source.triggered && source.sourceOwner?.id === session.user.id).length,
        createdAt: event.created_at,
        unread: Boolean(ownReceipt && !ownReceipt.read_at),
        audioStatus: expired ? "expired" : event.audio_status,
        audioExpiresAt: event.audio_expires_at || undefined,
        audioError: event.audio_error || asset?.error_message || undefined,
        masterSha256: asset?.sha256,
        durationSeconds: Number(event.duration_seconds || asset?.duration_seconds || 0),
        sources: eventSources,
      }
    })
  }

  async unreadExportActivityCount(): Promise<number> {
    const session = await this.currentSession()
    const response = await this.supabase().from("cloud_export_recipients").select("event_id", { count: "exact", head: true }).eq("recipient_id", session.user.id).is("read_at", null)
    if (response.error) throw response.error
    return response.count ?? 0
  }

  async markExportActivityRead(activityIds?: string[]): Promise<number> {
    const session = await this.currentSession()
    let request = this.supabase()
      .from("cloud_export_recipients")
      .update({ read_at: new Date().toISOString() })
      .eq("recipient_id", session.user.id)
      .is("read_at", null)
    if (activityIds && activityIds.length > 0) request = request.in("event_id", activityIds)
    const response = await request.select("event_id")
    if (response.error) throw response.error
    this.emitSync({ kind: "activity" })
    return this.unreadExportActivityCount()
  }

  async prepareExportActivityAudio(activityId: string): Promise<CloudActivityAudio> {
    await this.purgeExpiredActivityAudioCache()
    await this.currentSession()
    const eventResponse = await this.supabase()
      .from("cloud_export_events")
      .select("id,generated_loop_name,target_bpm,target_key,layer_count,duration_seconds,asset_id,audio_status,audio_expires_at")
      .eq("id", activityId)
      .single<Pick<CloudExportEventRow, "id" | "generated_loop_name" | "target_bpm" | "target_key" | "layer_count" | "duration_seconds" | "asset_id" | "audio_status" | "audio_expires_at">>()
    if (eventResponse.error) throw eventResponse.error
    const event = eventResponse.data
    if (!event.asset_id || event.audio_status !== "available") throw new Error("This activity audio is not available yet.")
    if (event.audio_expires_at && new Date(event.audio_expires_at).getTime() <= Date.now()) throw new Error("This activity audio has expired.")
    const assetResponse = await this.supabase()
      .from("cloud_export_assets")
      .select("id,owner_id,sha256,object_path,mime_type,byte_size,duration_seconds,status,retain_until,error_message")
      .eq("id", event.asset_id)
      .single<CloudExportAssetRow>()
    if (assetResponse.error) throw assetResponse.error
    const asset = assetResponse.data
    const extension = path.extname(asset.object_path) || ".wav"
    const cachedPath = path.join(this.exportAudioCacheRoot, `${asset.sha256}${extension}`)
    let cacheValid = false
    if (existsSync(cachedPath) && statSync(cachedPath).isFile() && statSync(cachedPath).size === Number(asset.byte_size)) {
      cacheValid = await sha256File(cachedPath) === asset.sha256
    }
    if (!cacheValid) {
      const downloaded = await this.supabase().storage.from(CLOUD_EXPORT_BUCKET).download(asset.object_path)
      if (downloaded.error) throw downloaded.error
      const bytes = Buffer.from(await downloaded.data.arrayBuffer())
      if (bytes.byteLength !== Number(asset.byte_size) || createHash("sha256").update(bytes).digest("hex") !== asset.sha256) {
        throw new Error("The Cloud activity audio failed its integrity check.")
      }
      mkdirSync(this.exportAudioCacheRoot, { recursive: true })
      writeFileSync(cachedPath, bytes, { mode: 0o600 })
    }
    writeActivityAudioCacheSidecar(cachedPath, asset.sha256, event.audio_expires_at || asset.retain_until)
    return {
      activityId: event.id,
      path: cachedPath,
      fileName: safeObjectFileName(`${event.generated_loop_name}${extension}`),
      durationSeconds: Number(event.duration_seconds || asset.duration_seconds || 0),
      targetBpm: Number(event.target_bpm),
      targetKey: event.target_key,
      layerCount: Number(event.layer_count),
      expiresAt: event.audio_expires_at || undefined,
    }
  }

  async getState(): Promise<CloudState> {
    const configured = Boolean(this.settings.projectUrl && this.settings.publishableKey)
    const testAccounts = this.testAccounts()
    if (!configured) {
      this.deactivateExportBinding()
      return { configured: false, projectUrl: "", authenticated: false, connections: [], libraries: [], testAccounts }
    }
    const sessionResponse = await this.supabase().auth.getSession()
    if (sessionResponse.error) {
      if (!isInvalidRefreshSession(sessionResponse.error)) throw sessionResponse.error
      this.deactivateExportBinding()
      await this.stopRealtime()
      await this.authStorage.clear()
      this.client = null
      return {
        configured: true,
        projectUrl: this.settings.projectUrl ?? "",
        authenticated: false,
        connections: [],
        libraries: [],
        testAccounts,
        message: "Your Cloud session ended. Sign in again to reconnect shared libraries.",
      }
    }
    const session = sessionResponse.data.session
    if (!session) {
      this.deactivateExportBinding()
      await this.stopRealtime()
      return {
        configured: true,
        projectUrl: this.settings.projectUrl ?? "",
        authenticated: false,
        connections: [],
        libraries: [],
        testAccounts,
      }
    }
    this.activateExportBinding(session)
    await this.ensureRealtime(session.user.id)
    void this.flushExportOutbox()
    void this.purgeExpiredActivityAudioCache()
    const profile = await this.ensureProfile(session)
    const [connectionsResponse, librariesResponse, accessBlocksResponse] = await Promise.all([
      this.supabase().from("connections").select("id,requester_id,addressee_id,status,created_at").order("created_at", { ascending: false }),
      this.supabase().from("cloud_libraries").select("id,owner_id,name,status,layer_count,loop_count,total_bytes,updated_at").order("updated_at", { ascending: false }),
      this.supabase().from("cloud_library_blocks").select("library_id,producer_id"),
    ])
    if (connectionsResponse.error) throw connectionsResponse.error
    if (librariesResponse.error) throw librariesResponse.error
    if (accessBlocksResponse.error) throw accessBlocksResponse.error
    const connectionRows = connectionsResponse.data as ConnectionRow[]
    const libraryRows = librariesResponse.data as LibraryRow[]
    const accessBlockRows = accessBlocksResponse.data as LibraryAccessBlockRow[]
    const relatedProfiles = await this.profileRows([
      ...connectionRows.flatMap((row) => [row.requester_id, row.addressee_id]),
      ...libraryRows.map((row) => row.owner_id),
    ])
    relatedProfiles.set(profile.id, profile)
    const connections: CloudConnection[] = connectionRows.map((row) => {
      const incoming = row.addressee_id === profile.id
      const otherId = incoming ? row.requester_id : row.addressee_id
      return {
        id: row.id,
        status: row.status,
        direction: incoming ? "incoming" : "outgoing",
        profile: relatedProfiles.get(otherId) ?? fallbackProfile(otherId),
        createdAt: row.created_at,
      }
    })
    const enabled = new Set(this.settings.enabledLibraryIds ?? [])
    const libraryCategories = await this.remoteLibraryCategories(libraryRows.filter((row) => (
      row.owner_id !== profile.id && row.status === "ready" && enabled.has(row.id)
    )))
    const libraries: CloudLibrarySummary[] = libraryRows.map((row) => ({
      id: row.id,
      name: row.name,
      owner: relatedProfiles.get(row.owner_id) ?? fallbackProfile(row.owner_id),
      status: row.status,
      layerCount: Number(row.layer_count),
      loopCount: Number(row.loop_count),
      totalBytes: Number(row.total_bytes),
      own: row.owner_id === profile.id,
      enabledForGenerate: row.owner_id !== profile.id && row.status === "ready" && enabled.has(row.id),
      blockedProducerIds: accessBlockRows.filter((block) => block.library_id === row.id).map((block) => block.producer_id),
      updatedAt: row.updated_at,
      categories: libraryCategories.get(row.id) ?? [],
    }))
    return {
      configured: true,
      projectUrl: this.settings.projectUrl ?? "",
      authenticated: true,
      userEmail: session.user.email,
      profile,
      connections,
      libraries,
      testAccounts,
    }
  }

  publishLibrary(libraryRoot: string, listener: PublishListener): CloudPublishStart {
    const jobId = randomUUID()
    void this.runPublish(jobId, libraryRoot, listener).catch((error) => {
      listener({
        jobId,
        type: "failed",
        message: "Cloud library upload failed.",
        error: cloudErrorMessage(error),
      })
    })
    return { jobId }
  }

  private async runPublish(jobId: string, libraryRoot: string, listener: PublishListener): Promise<void> {
    const session = await this.currentSession()
    const profile = await this.ensureProfile(session)
    const databasePath = path.join(this.acceptedCachePath, "generate", "library.sqlite3")
    listener({ jobId, type: "progress", message: "Reading the indexed local library…", percent: 1 })
    const manifest = readLocalCloudManifest(databasePath, libraryRoot, profile.displayName)
    const oversized = manifest.layers.find((layer) => layer.byteSize > FREE_PROJECT_OBJECT_LIMIT)
    if (oversized) {
      throw new Error(`${oversized.fileName} exceeds the 50 MB object limit of a free Supabase project.`)
    }
    const reusable = await this.supabase()
      .from("cloud_libraries")
      .select("id,owner_id,name,status,layer_count,loop_count,total_bytes,updated_at")
      .eq("owner_id", profile.id)
      .eq("source_fingerprint", manifest.fingerprint)
      .in("status", ["failed", "uploading"])
      .order("updated_at", { ascending: false })
      .limit(1)
      .maybeSingle<LibraryRow>()
    if (reusable.error) throw reusable.error
    const libraryResponse = reusable.data
      ? await this.supabase()
        .from("cloud_libraries")
        .update({
          name: manifest.name,
          status: "uploading",
          layer_count: manifest.layers.length,
          loop_count: manifest.loopCount,
          total_bytes: manifest.totalBytes,
        })
        .eq("id", reusable.data.id)
        .eq("owner_id", profile.id)
        .select("id,owner_id,name,status,layer_count,loop_count,total_bytes,updated_at")
        .single<LibraryRow>()
      : await this.supabase()
        .from("cloud_libraries")
        .insert({
          owner_id: profile.id,
          name: manifest.name,
          source_fingerprint: manifest.fingerprint,
          status: "uploading",
          layer_count: manifest.layers.length,
          loop_count: manifest.loopCount,
          total_bytes: manifest.totalBytes,
        })
      .select("id,owner_id,name,status,layer_count,loop_count,total_bytes,updated_at")
      .single<LibraryRow>()
    if (libraryResponse.error) throw libraryResponse.error
    const library = libraryResponse.data
    const preparedLayers = manifest.layers.map((layer, index) => {
      const fileName = safeObjectFileName(layer.fileName)
      const objectPath = `${profile.id}/${library.id}/${String(index + 1).padStart(5, "0")}-${layer.sha256.slice(0, 12)}-${fileName}`
      return {
        layer,
        objectPath,
        row: {
          library_id: library.id,
          owner_id: profile.id,
          object_path: objectPath,
          file_name: layer.fileName,
          relative_path: layer.relativePath,
          sha256: layer.sha256,
          byte_size: layer.byteSize,
          metadata: layer.metadata,
        },
      }
    })
    const storedPaths = new Set(await this.storedLibraryObjectPaths(library.id, profile.id))
    const resumableCount = preparedLayers.reduce((total, item) => total + Number(storedPaths.has(item.objectPath)), 0)
    const pendingLayers = preparedLayers.filter((item) => !storedPaths.has(item.objectPath))
    let completed = resumableCount
    if (resumableCount > 0) {
      listener({
        jobId,
        type: "progress",
        message: `Resuming Cloud upload · ${resumableCount}/${manifest.layers.length} layers already stored…`,
        current: resumableCount,
        total: manifest.layers.length,
        percent: Math.max(2, Math.min(88, Math.round((resumableCount / manifest.layers.length) * 88))),
      })
    }
    try {
      const uploadConcurrency = cloudUploadConcurrency(pendingLayers.map(({ layer }) => layer.byteSize))
      await parallelMap(pendingLayers, uploadConcurrency, async ({ layer, objectPath }) => {
        let body: Buffer
        try {
          body = await readFile(layer.path)
        } catch (error) {
          throw new Error(`Unable to read ${layer.fileName}. ${cloudErrorMessage(error, "Check that the local file is still available, then retry the library.")}`)
        }
        const upload = await this.supabase().storage.from(CLOUD_BUCKET).upload(objectPath, body, {
          contentType: audioMimeType(layer.fileName),
          cacheControl: "3600",
          upsert: false,
        })
        if (upload.error) {
          throw new Error(`Unable to upload ${layer.fileName}. ${cloudErrorMessage(
            upload.error,
            "Supabase Storage returned no reason. Check your connection, then retry the library.",
          )}`)
        }
        completed += 1
        listener({
          jobId,
          type: "progress",
          message: `Uploading ${completed}/${manifest.layers.length} layers…`,
          current: completed,
          total: manifest.layers.length,
          percent: Math.max(2, Math.min(88, Math.round((completed / manifest.layers.length) * 88))),
        })
      })
      const layerRows = preparedLayers.map((item) => item.row)
      for (let index = 0; index < layerRows.length; index += INSERT_BATCH_SIZE) {
        const batch = layerRows.slice(index, index + INSERT_BATCH_SIZE)
        const inserted = await this.supabase().from("cloud_layers").upsert(batch, { onConflict: "object_path" })
        if (inserted.error) throw inserted.error
        listener({
          jobId,
          type: "progress",
          message: `Publishing Cloud catalogue ${Math.min(index + batch.length, layerRows.length)}/${layerRows.length}…`,
          current: Math.min(index + batch.length, layerRows.length),
          total: layerRows.length,
          percent: 90 + Math.round((Math.min(index + batch.length, layerRows.length) / layerRows.length) * 8),
        })
      }
      const ready = await this.supabase()
        .from("cloud_libraries")
        .update({ status: "ready" })
        .eq("id", library.id)
        .select("id,owner_id,name,status,layer_count,loop_count,total_bytes,updated_at")
        .single<LibraryRow>()
      if (ready.error) throw ready.error
      listener({
        jobId,
        type: "completed",
        message: `${manifest.name} is ready for connected producers.`,
        percent: 100,
        library: {
          id: ready.data.id,
          name: ready.data.name,
          owner: profile,
          status: ready.data.status,
          layerCount: Number(ready.data.layer_count),
          loopCount: Number(ready.data.loop_count),
          totalBytes: Number(ready.data.total_bytes),
          own: true,
          enabledForGenerate: false,
          blockedProducerIds: [],
          updatedAt: ready.data.updated_at,
        },
      })
    } catch (error) {
      await this.supabase().from("cloud_libraries").update({ status: "failed" }).eq("id", library.id)
      throw new Error(`${cloudErrorMessage(error)} Uploaded layers were kept so Retry upload can continue instead of starting over.`)
    }
  }

  private async remoteLayerRows(libraries: LibraryRow[]): Promise<RemoteLayerRow[]> {
    const missing = libraries.filter((library) => {
      const signature = `${library.updated_at}:${library.layer_count}`
      return this.remoteLayerCache.get(library.id)?.signature !== signature
    })
    if (missing.length > 0) {
      const fetched: RemoteLayerRow[] = []
      const missingIds = missing.map((library) => library.id)
      for (let start = 0; ; start += CATALOG_PAGE_SIZE) {
        const response = await this.supabase()
          .from("cloud_layers")
          .select("id,library_id,owner_id,object_path,file_name,relative_path,sha256,byte_size,metadata")
          .in("library_id", missingIds)
          .range(start, start + CATALOG_PAGE_SIZE - 1)
        if (response.error) throw response.error
        const page = response.data as RemoteLayerRow[]
        fetched.push(...page)
        if (page.length < CATALOG_PAGE_SIZE) break
      }
      for (const library of missing) {
        this.remoteLayerCache.set(library.id, {
          signature: `${library.updated_at}:${library.layer_count}`,
          rows: fetched.filter((row) => row.library_id === library.id),
        })
      }
    }
    return libraries.flatMap((library) => this.remoteLayerCache.get(library.id)?.rows ?? [])
  }

  private async remoteLibraryCategories(libraries: LibraryRow[]): Promise<Map<string, Array<{ name: string; count: number }>>> {
    const result = new Map<string, Array<{ name: string; count: number }>>()
    const missing: LibraryRow[] = []
    for (const library of libraries) {
      const signature = `${library.updated_at}:${library.layer_count}`
      const cached = this.libraryCategoryCache.get(library.id)
      if (cached?.signature === signature) result.set(library.id, cached.categories)
      else missing.push(library)
    }
    if (missing.length === 0) return result

    const counts = new Map<string, Map<string, number>>()
    const missingIds = missing.map((library) => library.id)
    for (let start = 0; ; start += CATALOG_PAGE_SIZE) {
      const response = await this.supabase()
        .from("cloud_layers")
        .select("library_id,metadata")
        .in("library_id", missingIds)
        .range(start, start + CATALOG_PAGE_SIZE - 1)
      if (response.error) throw response.error
      const page = response.data as Array<{ library_id: string; metadata: Record<string, unknown> }>
      for (const row of page) {
        const category = typeof row.metadata?.category === "string" && row.metadata.category.trim()
          ? row.metadata.category.trim()
          : "Unknown"
        const libraryCounts = counts.get(row.library_id) ?? new Map<string, number>()
        libraryCounts.set(category, (libraryCounts.get(category) ?? 0) + 1)
        counts.set(row.library_id, libraryCounts)
      }
      if (page.length < CATALOG_PAGE_SIZE) break
    }

    for (const library of missing) {
      const categories = [...(counts.get(library.id) ?? new Map<string, number>())]
        .map(([name, count]) => ({ name, count }))
        .sort((left, right) => right.count - left.count || left.name.localeCompare(right.name))
      const signature = `${library.updated_at}:${library.layer_count}`
      this.libraryCategoryCache.set(library.id, { signature, categories })
      result.set(library.id, categories)
    }
    return result
  }

  async enrichGenerateRequest(request: GenerateJobRequest): Promise<CloudGenerateJobRequest> {
    // A local-only generation must never depend on Cloud configuration or auth.
    // Keep this guard before every access to persisted Cloud state so a stale or
    // signed-out session cannot block the local engine.
    if (request.sourcePool === "local-only") return request
    if (!this.settings.projectUrl || !this.settings.publishableKey || !(this.settings.enabledLibraryIds?.length)) {
      return request
    }
    let session: Session
    try {
      session = await this.currentSession()
    } catch (error) {
      // "PC + Cloud" is deliberately opportunistic: when Cloud is unavailable,
      // the selected PC libraries must remain usable. "Cloud only" still reports
      // the authentication error because it has no valid local fallback.
      if (request.sourcePool === "mixed") return request
      throw error
    }
    const enabledIds = new Set(this.settings.enabledLibraryIds)
    const librariesResponse = await this.supabase()
      .from("cloud_libraries")
      .select("id,owner_id,name,status,layer_count,loop_count,total_bytes,updated_at")
      .in("id", [...enabledIds])
      .eq("status", "ready")
    if (librariesResponse.error) throw librariesResponse.error
    const remoteLibraries = (librariesResponse.data as LibraryRow[]).filter((library) => library.owner_id !== session.user.id)
    if (remoteLibraries.length === 0) return request
    const ownerProfiles = await this.profileRows(remoteLibraries.map((library) => library.owner_id))
    const rows = await this.remoteLayerRows(remoteLibraries)
    const cloudLayers = rows.map((row) => {
      const metadata = row.metadata && typeof row.metadata === "object" ? row.metadata : {}
      const owner = ownerProfiles.get(row.owner_id)
      const rawProducers = Array.isArray(metadata.producers)
        ? metadata.producers.filter((item): item is string => typeof item === "string")
        : owner ? [owner.displayName] : []
      const producers = canonicalizeCloudProducerCredits(rawProducers, owner)
      return {
        ...metadata,
        identity: `cloud:${row.id}`,
        path: cloudCachePath(this.audioCacheRoot, row.owner_id, row.library_id, row.sha256, row.file_name),
        filename: row.file_name,
        relative_path: row.relative_path,
        source_loop_id: `cloud:${row.owner_id}:${String(metadata.source_loop_id || row.id)}`,
        library_root: `cloud://${row.owner_id}/${row.library_id}`,
        sha256: row.sha256,
        byte_size: Number(row.byte_size),
        producers,
        cloud_object_path: row.object_path,
        cloud_layer_id: row.id,
        cloud_owner_id: row.owner_id,
      }
    })
    return {
      ...request,
      cloudLayers,
      cloudAuth: {
        projectUrl: this.settings.projectUrl,
        publishableKey: this.settings.publishableKey,
        accessToken: session.access_token,
        bucket: CLOUD_BUCKET,
        cacheRoot: this.audioCacheRoot,
      },
    }
  }
}
