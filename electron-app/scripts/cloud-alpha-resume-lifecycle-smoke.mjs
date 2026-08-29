import { createHash } from "node:crypto"
import { existsSync } from "node:fs"
import { readFile } from "node:fs/promises"
import { homedir } from "node:os"
import path from "node:path"
import { performance } from "node:perf_hooks"
import process from "node:process"
import { DatabaseSync } from "node:sqlite"

import { createClient } from "@supabase/supabase-js"

const BUCKET = "cloud-layers"
const PAGE_SIZE = 1_000
const RESUME_GAP = 5
const libraryRoot = path.resolve(process.argv[2] || "")
const cacheRoot = path.join(homedir(), "Library", "Caches", "Stem Slicer")
const databasePath = path.join(cacheRoot, "1.9", "generate", "library.sqlite3")
const cloudRoot = path.join(cacheRoot, "electron-prototype", "cloud")
const settings = JSON.parse(await readFile(path.join(cloudRoot, "settings.json"), "utf8"))
const credentials = JSON.parse(await readFile(path.join(cloudRoot, "alpha-test-credentials.json"), "utf8"))

if (!process.argv[2] || !existsSync(libraryRoot)) {
  throw new Error("Pass an indexed local test-library folder to the resume lifecycle smoke test.")
}

function client() {
  return createClient(settings.projectUrl, settings.publishableKey, {
    auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false },
  })
}

async function signIn(account) {
  const supabase = client()
  const response = await supabase.auth.signInWithPassword({ email: account.email, password: account.password })
  if (response.error) throw response.error
  if (!response.data.user) throw new Error(`No user returned for ${account.displayName}`)
  return { supabase, user: response.data.user }
}

function safeObjectFileName(fileName) {
  const extension = path.extname(fileName).toLowerCase()
  const stem = path.basename(fileName, path.extname(fileName))
    .normalize("NFKD")
    .replace(/[^a-zA-Z0-9._,'!&$@=;:+?() -]+/g, "-")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 120)
  return `${stem || "layer"}${extension || ".mp3"}`
}

function mimeType(fileName) {
  return path.extname(fileName).toLowerCase() === ".mp3" ? "audio/mpeg" : "application/octet-stream"
}

function readManifest() {
  const database = new DatabaseSync(databasePath, { readOnly: true })
  try {
    const rows = database.prepare(`
      SELECT path, relative_path, filename, source_loop_id, sha256, byte_size,
        bpm, key, mode, predicted_label, manual_label
      FROM layer_cache
      WHERE library_root = ? AND COALESCE(manual_excluded, 0) = 0
      ORDER BY relative_path COLLATE NOCASE
    `).all(libraryRoot)
    if (rows.length <= RESUME_GAP) throw new Error("The indexed test library is too small for a resume test.")
    return rows.map((row) => ({
      ...row,
      path: String(row.path),
      relative_path: String(row.relative_path),
      filename: String(row.filename),
      source_loop_id: String(row.source_loop_id),
      sha256: String(row.sha256),
      byte_size: Number(row.byte_size),
    }))
  } finally {
    database.close()
  }
}

async function timed(action) {
  const startedAt = performance.now()
  const value = await action()
  return { value, milliseconds: Math.round((performance.now() - startedAt) * 10) / 10 }
}

async function parallel(items, concurrency, action) {
  let nextIndex = 0
  const workers = Array.from({ length: Math.min(concurrency, items.length) }, async () => {
    while (nextIndex < items.length) {
      const index = nextIndex
      nextIndex += 1
      await action(items[index])
    }
  })
  await Promise.all(workers)
}

async function storedPaths(supabase, ownerId, libraryId) {
  const prefix = `${ownerId}/${libraryId}`
  const paths = []
  for (let offset = 0; ; offset += PAGE_SIZE) {
    const response = await supabase.storage.from(BUCKET).list(prefix, {
      limit: PAGE_SIZE,
      offset,
      sortBy: { column: "name", order: "asc" },
    })
    if (response.error) throw response.error
    paths.push(...response.data
      .filter((object) => object.name !== ".emptyFolderPlaceholder")
      .map((object) => `${prefix}/${object.name}`))
    if (response.data.length < PAGE_SIZE) break
  }
  return paths
}

async function removeObjects(supabase, paths) {
  for (let index = 0; index < paths.length; index += PAGE_SIZE) {
    const response = await supabase.storage.from(BUCKET).remove(paths.slice(index, index + PAGE_SIZE))
    if (response.error) throw response.error
  }
}

const manifest = readManifest()
const owner = await signIn(credentials.accounts.nrgy)
const viewer = await signIn(credentials.accounts.xt)
const libraryName = `SLICER RESUME TEST ${new Date().toISOString().replace(/[:.]/g, "-")}`
const totalBytes = manifest.reduce((total, layer) => total + layer.byte_size, 0)
const loopCount = new Set(manifest.map((layer) => layer.source_loop_id)).size
const fingerprint = createHash("sha256")
  .update(manifest.map((layer) => `${layer.relative_path}\0${layer.sha256}`).join("\0"))
  .digest("hex")
let libraryId = ""
let completed = false

try {
  const created = await owner.supabase.from("cloud_libraries").insert({
    owner_id: owner.user.id,
    name: libraryName,
    source_fingerprint: fingerprint,
    status: "uploading",
    layer_count: manifest.length,
    loop_count: loopCount,
    total_bytes: totalBytes,
  }).select("id").single()
  if (created.error) throw created.error
  libraryId = created.data.id

  const prepared = manifest.map((layer, index) => {
    const objectPath = `${owner.user.id}/${libraryId}/${String(index + 1).padStart(5, "0")}-${layer.sha256.slice(0, 12)}-${safeObjectFileName(layer.filename)}`
    return {
      layer,
      objectPath,
      row: {
        library_id: libraryId,
        owner_id: owner.user.id,
        object_path: objectPath,
        file_name: layer.filename,
        relative_path: layer.relative_path,
        sha256: layer.sha256,
        byte_size: layer.byte_size,
        metadata: {
          source_loop_id: layer.source_loop_id,
          category: layer.manual_label || layer.predicted_label || "Unknown",
          bpm: layer.bpm,
          key: layer.key,
          mode: layer.mode,
          producers: ["+NRGY"],
        },
      },
    }
  })

  const interruptedUpload = await timed(async () => {
    await parallel(prepared.slice(0, -RESUME_GAP), 3, async ({ layer, objectPath }) => {
      const body = await readFile(layer.path)
      const uploaded = await owner.supabase.storage.from(BUCKET).upload(objectPath, body, {
        contentType: mimeType(layer.filename),
        cacheControl: "60",
        upsert: false,
      })
      if (uploaded.error) throw uploaded.error
    })
    const failed = await owner.supabase.from("cloud_libraries").update({ status: "failed" }).eq("id", libraryId)
    if (failed.error) throw failed.error
  })

  const resume = await timed(async () => {
    const uploading = await owner.supabase.from("cloud_libraries").update({ status: "uploading" }).eq("id", libraryId)
    if (uploading.error) throw uploading.error
    const existing = new Set(await storedPaths(owner.supabase, owner.user.id, libraryId))
    if (existing.size !== manifest.length - RESUME_GAP) {
      throw new Error(`Expected ${manifest.length - RESUME_GAP} resumable objects, found ${existing.size}.`)
    }
    const missing = prepared.filter((item) => !existing.has(item.objectPath))
    await parallel(missing, 3, async ({ layer, objectPath }) => {
      const body = await readFile(layer.path)
      const uploaded = await owner.supabase.storage.from(BUCKET).upload(objectPath, body, {
        contentType: mimeType(layer.filename),
        cacheControl: "60",
        upsert: false,
      })
      if (uploaded.error) throw uploaded.error
    })
    const catalogued = await owner.supabase.from("cloud_layers").upsert(prepared.map((item) => item.row), {
      onConflict: "object_path",
    })
    if (catalogued.error) throw catalogued.error
    const ready = await owner.supabase.from("cloud_libraries").update({ status: "ready" }).eq("id", libraryId)
    if (ready.error) throw ready.error
    return { reused: existing.size, uploaded: missing.length }
  })

  const verifyReady = await timed(async () => {
    const libraries = await viewer.supabase.from("cloud_libraries").select("id").eq("id", libraryId)
    if (libraries.error) throw libraries.error
    const layers = await viewer.supabase.from("cloud_layers").select("id", { count: "exact", head: true }).eq("library_id", libraryId)
    if (layers.error) throw layers.error
    if (libraries.data.length !== 1 || layers.count !== manifest.length) throw new Error("The resumed library is incomplete for the connected producer.")
  })

  const pause = await timed(async () => {
    const response = await owner.supabase.from("cloud_libraries").update({ status: "archived" }).eq("id", libraryId)
    if (response.error) throw response.error
  })
  const verifyPaused = await timed(async () => {
    const viewerLibrary = await viewer.supabase.from("cloud_libraries").select("id").eq("id", libraryId)
    if (viewerLibrary.error) throw viewerLibrary.error
    const ownerLayers = await owner.supabase.from("cloud_layers").select("id", { count: "exact", head: true }).eq("library_id", libraryId)
    if (ownerLayers.error) throw ownerLayers.error
    if (viewerLibrary.data.length !== 0 || ownerLayers.count !== manifest.length) throw new Error("Paused-library visibility is incorrect.")
  })

  const resumeSharing = await timed(async () => {
    const response = await owner.supabase.from("cloud_libraries").update({ status: "ready" }).eq("id", libraryId)
    if (response.error) throw response.error
  })

  const remove = await timed(async () => {
    const paused = await owner.supabase.from("cloud_libraries").update({ status: "archived" }).eq("id", libraryId)
    if (paused.error) throw paused.error
    const paths = await storedPaths(owner.supabase, owner.user.id, libraryId)
    await removeObjects(owner.supabase, paths)
    const deleted = await owner.supabase.from("cloud_libraries").delete().eq("id", libraryId).select("id").maybeSingle()
    if (deleted.error) throw deleted.error
    if (!deleted.data) throw new Error("The lifecycle test library was not deleted.")
  })

  const verifyRemoved = await timed(async () => {
    const paths = await storedPaths(owner.supabase, owner.user.id, libraryId)
    const row = await owner.supabase.from("cloud_libraries").select("id").eq("id", libraryId)
    if (row.error) throw row.error
    if (paths.length !== 0 || row.data.length !== 0) throw new Error("The lifecycle test left Cloud residue.")
  })

  completed = true
  process.stdout.write(`${JSON.stringify({
    libraryRoot,
    layers: manifest.length,
    loops: loopCount,
    totalBytes,
    resume: resume.value,
    verified: {
      partialUploadPreserved: true,
      missingOnlyResume: true,
      connectedProducerVisibility: true,
      pauseAndOwnerAccess: true,
      resumeSharing: true,
      storageAndCatalogueRemoved: true,
    },
    milliseconds: {
      interruptedUpload: interruptedUpload.milliseconds,
      resumeMissingAndPublishCatalogue: resume.milliseconds,
      verifyReady: verifyReady.milliseconds,
      pause: pause.milliseconds,
      verifyPaused: verifyPaused.milliseconds,
      resumeSharing: resumeSharing.milliseconds,
      remove: remove.milliseconds,
      verifyRemoved: verifyRemoved.milliseconds,
    },
  }, null, 2)}\n`)
} finally {
  if (!completed && libraryId) {
    await owner.supabase.from("cloud_libraries").update({ status: "archived" }).eq("id", libraryId)
    await removeObjects(owner.supabase, await storedPaths(owner.supabase, owner.user.id, libraryId))
    await owner.supabase.from("cloud_libraries").delete().eq("id", libraryId)
  }
  await Promise.all([
    owner.supabase.auth.signOut({ scope: "local" }),
    viewer.supabase.auth.signOut({ scope: "local" }),
  ])
}
