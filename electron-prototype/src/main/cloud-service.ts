import { randomUUID } from "node:crypto"
import { readFile } from "node:fs/promises"
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs"
import path from "node:path"
import { nativeImage, safeStorage } from "electron"
import { createClient, type Session, type SupabaseClient } from "@supabase/supabase-js"

import type {
  CloudConnection,
  CloudCredentialsRequest,
  CloudGenerationActivity,
  CloudGenerationRecordRequest,
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
const STORAGE_LIST_PAGE_SIZE = 1_000
const STORAGE_DELETE_BATCH_SIZE = 1_000
const PROFILE_AVATAR_SOURCE_LIMIT = 25_000_000
const PROFILE_AVATAR_UPLOAD_LIMIT = 5_000_000
const PROFILE_AVATAR_EDGE = 512

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

interface GenerationRunRow {
  id: string
  created_by: string
  contributor_ids: string[]
  seed: number
  target_bpm: number
  target_key: string
  layer_count: number
  created_at: string
}

interface GenerationSourceRow {
  generation_id: string
  slot_index: number
  source_owner_id: string
  source_loop_id: string
  category: string
}

interface CloudGenerateJobRequest extends GenerateJobRequest {
  cloudLayers?: Array<Record<string, unknown>>
  cloudAuth?: Record<string, unknown>
}

type PublishListener = (event: CloudPublishEvent) => void

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

export class CloudService {
  private readonly settingsPath: string
  private readonly sessionPath: string
  private readonly alphaCredentialsPath: string
  private readonly audioCacheRoot: string
  private readonly authStorage: EncryptedAuthStorage
  private settings: CloudLocalSettings
  private client: SupabaseClient | null = null
  private readonly libraryCategoryCache = new Map<string, { signature: string; categories: Array<{ name: string; count: number }> }>()

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

  async recordGeneration(request: CloudGenerationRecordRequest): Promise<string | undefined> {
    if (!Array.isArray(request.sources) || request.sources.length === 0) return undefined
    const session = await this.currentSession()
    const contributors = [...new Set(request.sources.map((source) => source.cloudOwnerId).filter(Boolean))]
    const insertedRun = await this.supabase()
      .from("generation_runs")
      .insert({
        created_by: session.user.id,
        contributor_ids: contributors,
        seed: Math.trunc(request.seed),
        target_bpm: Math.round(request.targetBpm),
        target_key: String(request.targetKey || "Unknown"),
        layer_count: Math.max(1, Math.round(request.layerCount)),
      })
      .select("id")
      .single<{ id: string }>()
    if (insertedRun.error) throw insertedRun.error

    const sourceRows = request.sources.map((source) => ({
      generation_id: insertedRun.data.id,
      slot_index: Math.max(0, Math.round(source.slotIndex)),
      cloud_layer_id: source.cloudLayerId,
      source_owner_id: source.cloudOwnerId,
      source_sha256: source.sourceSha256,
      source_loop_id: source.sourceLoopId,
      category: source.category,
    }))
    const insertedSources = await this.supabase().from("generation_sources").insert(sourceRows)
    if (insertedSources.error) throw insertedSources.error
    return insertedRun.data.id
  }

  async generationActivity(): Promise<CloudGenerationActivity[]> {
    await this.currentSession()
    const runsResponse = await this.supabase()
      .from("generation_runs")
      .select("id,created_by,contributor_ids,seed,target_bpm,target_key,layer_count,created_at")
      .order("created_at", { ascending: false })
      .limit(60)
    if (runsResponse.error) throw runsResponse.error
    const runs = runsResponse.data as GenerationRunRow[]
    if (runs.length === 0) return []

    const sourcesResponse = await this.supabase()
      .from("generation_sources")
      .select("generation_id,slot_index,source_owner_id,source_loop_id,category")
      .in("generation_id", runs.map((run) => run.id))
      .order("slot_index", { ascending: true })
    if (sourcesResponse.error) throw sourcesResponse.error
    const sources = sourcesResponse.data as GenerationSourceRow[]
    const profiles = await this.profileRows([
      ...runs.flatMap((run) => [run.created_by, ...(run.contributor_ids ?? [])]),
      ...sources.map((source) => source.source_owner_id),
    ])

    return runs.map((run) => ({
      id: run.id,
      createdBy: profiles.get(run.created_by) ?? fallbackProfile(run.created_by),
      contributors: (run.contributor_ids ?? []).map((id) => profiles.get(id) ?? fallbackProfile(id)),
      seed: Number(run.seed),
      targetBpm: Number(run.target_bpm),
      targetKey: run.target_key,
      layerCount: Number(run.layer_count),
      createdAt: run.created_at,
      sources: sources.filter((source) => source.generation_id === run.id).map((source) => ({
        slotIndex: Number(source.slot_index),
        sourceOwner: profiles.get(source.source_owner_id) ?? fallbackProfile(source.source_owner_id),
        sourceLoopId: source.source_loop_id,
        category: source.category,
      })),
    }))
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
      await parallelMap(preparedLayers, UPLOAD_CONCURRENCY, async ({ layer, objectPath }) => {
        if (storedPaths.has(objectPath)) return
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
          updatedAt: ready.data.updated_at,
        },
      })
    } catch (error) {
      await this.supabase().from("cloud_libraries").update({ status: "failed" }).eq("id", library.id)
      throw new Error(`${cloudErrorMessage(error)} Uploaded layers were kept so Retry upload can continue instead of starting over.`)
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
