import { randomUUID } from "node:crypto"
import { readFile } from "node:fs/promises"
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs"
import path from "node:path"
import { safeStorage } from "electron"
import { createClient, type Session, type SupabaseClient } from "@supabase/supabase-js"

import type {
  CloudConnection,
  CloudCredentialsRequest,
  CloudLibrarySummary,
  CloudProfile,
  CloudProfileUpdateRequest,
  CloudPublishEvent,
  CloudPublishStart,
  CloudSignUpRequest,
  CloudState,
  CloudTestAccount,
  ConfigureCloudRequest,
  GenerateJobRequest,
} from "../shared/contracts"
import {
  audioMimeType,
  cloudCachePath,
  readLocalCloudManifest,
  safeObjectFileName,
} from "./cloud-catalog"

const CLOUD_BUCKET = "cloud-layers"
const PROFILE_AVATAR_BUCKET = "profile-avatars"
const FREE_PROJECT_OBJECT_LIMIT = 50_000_000
const UPLOAD_CONCURRENCY = 3
const INSERT_BATCH_SIZE = 200
const CATALOG_PAGE_SIZE = 1_000

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
  open_to_collaborate: boolean | null
  updated_at: string
}

const PROFILE_COLUMNS = "id,handle,display_name,avatar_path,bio,instagram_handle,aliases,open_to_collaborate,updated_at"

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

interface CloudGenerateJobRequest extends GenerateJobRequest {
  cloudLayers?: Array<Record<string, unknown>>
  cloudAuth?: Record<string, unknown>
}

type PublishListener = (event: CloudPublishEvent) => void

function normalizeHandle(value: string): string {
  return value.trim().toLowerCase().replace(/[^a-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "")
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
    openToCollaborate: row.open_to_collaborate === true,
  }
}

function fallbackProfile(id: string): CloudProfile {
  return {
    id,
    handle: "producer",
    displayName: "Producer",
    aliases: [],
    openToCollaborate: false,
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
    const key = alias.toLocaleLowerCase()
    if (!alias || seen.has(key)) continue
    if (alias.length > 64) throw new Error("Each producer alias must contain 64 characters or fewer.")
    seen.add(key)
    aliases.push(alias)
  }
  if (aliases.length > 12) throw new Error("Keep up to 12 producer aliases on one profile.")
  return aliases
}

export function canonicalizeCloudProducerCredits(producers: string[], owner?: CloudProfile): string[] {
  const ownerIdentityKeys = new Set([
    owner?.displayName,
    owner?.handle,
    ...(owner?.aliases ?? []),
  ].filter((item): item is string => Boolean(item)).map((item) => item.toLocaleLowerCase()))
  return [...new Set(producers.map((producer) => (
    owner && ownerIdentityKeys.has(producer.trim().toLocaleLowerCase())
      ? owner.displayName
      : producer.trim()
  )).filter(Boolean))]
}

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message
  if (error && typeof error === "object" && "message" in error) return String(error.message)
  return "The Cloud request failed."
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
  const workers = Array.from({ length: Math.min(concurrency, items.length) }, async () => {
    while (nextIndex < items.length) {
      const index = nextIndex
      nextIndex += 1
      await task(items[index], index)
    }
  })
  await Promise.all(workers)
}

export class CloudService {
  private readonly settingsPath: string
  private readonly sessionPath: string
  private readonly alphaCredentialsPath: string
  private readonly audioCacheRoot: string
  private readonly authStorage: EncryptedAuthStorage
  private settings: CloudLocalSettings
  private client: SupabaseClient | null = null

  constructor(
    private readonly acceptedCachePath: string,
    prototypeCachePath: string,
  ) {
    const root = path.join(prototypeCachePath, "cloud")
    this.settingsPath = path.join(root, "settings.json")
    this.sessionPath = path.join(root, "session.enc")
    this.alphaCredentialsPath = path.join(root, "alpha-test-credentials.json")
    this.audioCacheRoot = path.join(root, "audio")
    this.authStorage = new EncryptedAuthStorage(this.sessionPath)
    this.settings = this.loadSettings()
  }

  private loadSettings(): CloudLocalSettings {
    try {
      const parsed = JSON.parse(readFileSync(this.settingsPath, "utf8")) as CloudLocalSettings
      return {
        projectUrl: typeof parsed.projectUrl === "string" ? parsed.projectUrl : undefined,
        publishableKey: typeof parsed.publishableKey === "string" ? parsed.publishableKey : undefined,
        enabledLibraryIds: Array.isArray(parsed.enabledLibraryIds) ? parsed.enabledLibraryIds.filter((item): item is string => typeof item === "string") : [],
        pendingProfiles: parsed.pendingProfiles && typeof parsed.pendingProfiles === "object" ? parsed.pendingProfiles : {},
      }
    } catch {
      return { enabledLibraryIds: [], pendingProfiles: {} }
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
    this.settings = { ...this.settings, ...configuration }
    this.saveSettings()
    this.client = null
    return this.getState()
  }

  private async currentSession(): Promise<Session> {
    const { data, error } = await this.supabase().auth.getSession()
    if (error) throw error
    if (!data.session) throw new Error("Sign in to Slicer Cloud first.")
    return data.session
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
    const fallbackHandle = normalizeHandle(email.split("@")[0] || `producer-${session.user.id.slice(0, 8)}`)
    const handle = normalizeHandle(pending?.handle || fallbackHandle).slice(0, 32)
    if (handle.length < 3) throw new Error("The Cloud profile handle must contain at least 3 characters.")
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
    const handle = normalizeHandle(request.handle)
    const displayName = request.displayName.trim()
    if (handle.length < 3) throw new Error("Choose a Cloud handle with at least 3 characters.")
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
    if (this.client) {
      const { error } = await this.client.auth.signOut({ scope: "local" })
      if (error) throw error
    }
    return this.getState()
  }

  async updateProfile(request: CloudProfileUpdateRequest): Promise<CloudState> {
    const session = await this.currentSession()
    const handle = normalizeHandle(request.handle)
    const displayName = request.displayName.trim().replace(/\s+/g, " ")
    const bio = request.bio.trim().replace(/\s+/g, " ")
    const instagramHandle = normalizeInstagramHandle(request.instagramHandle)
    const aliases = normalizeAliases(request.aliases)
      .filter((alias) => alias.toLocaleLowerCase() !== displayName.toLocaleLowerCase())

    if (handle.length < 3) throw new Error("Choose a Cloud handle with at least 3 characters.")
    if (!displayName || displayName.length > 64) throw new Error("Use a producer name between 1 and 64 characters.")
    if (bio.length > 280) throw new Error("Keep the profile bio within 280 characters.")

    let avatarPath: string | undefined
    if (request.avatarFilePath) {
      const avatarBytes = await readFile(request.avatarFilePath)
      if (avatarBytes.length === 0 || avatarBytes.length > 5_000_000) {
        throw new Error("Choose a profile image smaller than 5 MB.")
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
      open_to_collaborate: request.openToCollaborate,
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
    const handle = normalizeHandle(handleValue)
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

  async setLibraryEnabled(libraryId: string, enabled: boolean): Promise<CloudState> {
    const ids = new Set(this.settings.enabledLibraryIds ?? [])
    if (enabled) ids.add(libraryId)
    else ids.delete(libraryId)
    this.settings.enabledLibraryIds = [...ids]
    this.saveSettings()
    return this.getState()
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

  async getState(): Promise<CloudState> {
    const configured = Boolean(this.settings.projectUrl && this.settings.publishableKey)
    const testAccounts = this.testAccounts()
    if (!configured) {
      return { configured: false, projectUrl: "", authenticated: false, connections: [], libraries: [], testAccounts }
    }
    const sessionResponse = await this.supabase().auth.getSession()
    if (sessionResponse.error) {
      if (!isInvalidRefreshSession(sessionResponse.error)) throw sessionResponse.error
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
      return {
        configured: true,
        projectUrl: this.settings.projectUrl ?? "",
        authenticated: false,
        connections: [],
        libraries: [],
        testAccounts,
      }
    }
    const profile = await this.ensureProfile(session)
    const [connectionsResponse, librariesResponse] = await Promise.all([
      this.supabase().from("connections").select("id,requester_id,addressee_id,status,created_at").order("created_at", { ascending: false }),
      this.supabase().from("cloud_libraries").select("id,owner_id,name,status,layer_count,loop_count,total_bytes,updated_at").order("updated_at", { ascending: false }),
    ])
    if (connectionsResponse.error) throw connectionsResponse.error
    if (librariesResponse.error) throw librariesResponse.error
    const connectionRows = connectionsResponse.data as ConnectionRow[]
    const libraryRows = librariesResponse.data as LibraryRow[]
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
      updatedAt: row.updated_at,
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
        error: errorMessage(error),
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
    const created = await this.supabase()
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
    if (created.error) throw created.error
    const library = created.data
    const layerRows = new Array<Record<string, unknown>>(manifest.layers.length)
    let completed = 0
    try {
      await parallelMap(manifest.layers, UPLOAD_CONCURRENCY, async (layer, index) => {
        const fileName = safeObjectFileName(layer.fileName)
        const objectPath = `${profile.id}/${library.id}/${String(index + 1).padStart(5, "0")}-${layer.sha256.slice(0, 12)}-${fileName}`
        const body = await readFile(layer.path)
        const upload = await this.supabase().storage.from(CLOUD_BUCKET).upload(objectPath, body, {
          contentType: audioMimeType(layer.fileName),
          cacheControl: "3600",
          upsert: false,
        })
        if (upload.error) throw upload.error
        layerRows[index] = {
          library_id: library.id,
          owner_id: profile.id,
          object_path: objectPath,
          file_name: layer.fileName,
          relative_path: layer.relativePath,
          sha256: layer.sha256,
          byte_size: layer.byteSize,
          metadata: layer.metadata,
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
      for (let index = 0; index < layerRows.length; index += INSERT_BATCH_SIZE) {
        const batch = layerRows.slice(index, index + INSERT_BATCH_SIZE)
        const inserted = await this.supabase().from("cloud_layers").insert(batch)
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
          updatedAt: ready.data.updated_at,
        },
      })
    } catch (error) {
      await this.supabase().from("cloud_libraries").update({ status: "failed" }).eq("id", library.id)
      throw error
    }
  }

  private async remoteLayerRows(libraryIds: string[]): Promise<RemoteLayerRow[]> {
    const rows: RemoteLayerRow[] = []
    for (let start = 0; ; start += CATALOG_PAGE_SIZE) {
      const response = await this.supabase()
        .from("cloud_layers")
        .select("id,library_id,owner_id,object_path,file_name,relative_path,sha256,byte_size,metadata")
        .in("library_id", libraryIds)
        .range(start, start + CATALOG_PAGE_SIZE - 1)
      if (response.error) throw response.error
      const page = response.data as RemoteLayerRow[]
      rows.push(...page)
      if (page.length < CATALOG_PAGE_SIZE) break
    }
    return rows
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
      // "Mac + Cloud" is deliberately opportunistic: when Cloud is unavailable,
      // the selected Mac libraries must remain usable. "Cloud only" still reports
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
    const rows = await this.remoteLayerRows(remoteLibraries.map((library) => library.id))
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
    const cloudProducerNames = [...new Set(cloudLayers.flatMap((layer) => layer.producers))]
    return {
      ...request,
      allowedProducers: [...new Set([...(request.allowedProducers ?? []), ...cloudProducerNames])],
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
