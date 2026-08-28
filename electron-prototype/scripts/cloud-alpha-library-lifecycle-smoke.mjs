import { Buffer } from "node:buffer"
import { createHash, randomUUID } from "node:crypto"
import { readFile } from "node:fs/promises"
import { homedir } from "node:os"
import path from "node:path"
import { performance } from "node:perf_hooks"
import process from "node:process"

import { createClient } from "@supabase/supabase-js"

const BUCKET = "cloud-layers"
const OBJECT_COUNT = 3
const cloudRoot = path.join(homedir(), "Library", "Caches", "Stem Slicer", "electron-prototype", "cloud")
const settings = JSON.parse(await readFile(path.join(cloudRoot, "settings.json"), "utf8"))
const credentials = JSON.parse(await readFile(path.join(cloudRoot, "alpha-test-credentials.json"), "utf8"))
const libraryName = `SLICER LIFECYCLE SMOKE ${new Date().toISOString().replace(/[:.]/g, "-")}`

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

async function timed(action) {
  const startedAt = performance.now()
  const value = await action()
  return { value, milliseconds: Math.round((performance.now() - startedAt) * 10) / 10 }
}

const owner = await signIn(credentials.accounts.xt)
const viewer = await signIn(credentials.accounts.nrgy)
const objectPaths = []
let libraryId = ""
let completed = false

try {
  const bodies = Array.from({ length: OBJECT_COUNT }, (_, index) => Buffer.from(
    `Slicer Cloud lifecycle smoke object ${index + 1} ${randomUUID()}\n`.repeat(48),
    "utf8",
  ))
  const totalBytes = bodies.reduce((total, body) => total + body.length, 0)

  const publish = await timed(async () => {
    const created = await owner.supabase
      .from("cloud_libraries")
      .insert({
        owner_id: owner.user.id,
        name: libraryName,
        source_fingerprint: createHash("sha256").update(libraryName).digest("hex"),
        status: "uploading",
        layer_count: OBJECT_COUNT,
        loop_count: 1,
        total_bytes: totalBytes,
      })
      .select("id")
      .single()
    if (created.error) throw created.error
    libraryId = created.data.id

    const layerRows = []
    for (let index = 0; index < bodies.length; index += 1) {
      const body = bodies[index]
      const sha256 = createHash("sha256").update(body).digest("hex")
      const fileName = `SLICER_LIFECYCLE_SMOKE_${index + 1}.mp3`
      const objectPath = `${owner.user.id}/${libraryId}/${String(index + 1).padStart(5, "0")}-${sha256.slice(0, 12)}-${fileName}`
      objectPaths.push(objectPath)
      const uploaded = await owner.supabase.storage.from(BUCKET).upload(objectPath, body, {
        contentType: "audio/mpeg",
        cacheControl: "60",
        upsert: false,
      })
      if (uploaded.error) throw uploaded.error
      layerRows.push({
        library_id: libraryId,
        owner_id: owner.user.id,
        object_path: objectPath,
        file_name: fileName,
        relative_path: `SLICER LIFECYCLE SMOKE/${fileName}`,
        sha256,
        byte_size: body.length,
        metadata: {
          source_loop_id: "slicer-lifecycle-smoke-loop",
          source_loop_name: "SLICER LIFECYCLE SMOKE",
          layer_index: index + 1,
          category: ["Bass", "Chords", "Lead"][index] ?? "Layer",
          bpm: 140,
          key: "C",
          mode: "minor",
          producers: ["XT"],
        },
      })
    }
    const inserted = await owner.supabase.from("cloud_layers").insert(layerRows)
    if (inserted.error) throw inserted.error
    const ready = await owner.supabase.from("cloud_libraries").update({ status: "ready" }).eq("id", libraryId)
    if (ready.error) throw ready.error
  })

  const readyVisibility = await timed(async () => {
    const libraries = await viewer.supabase.from("cloud_libraries").select("id,status").eq("id", libraryId)
    if (libraries.error) throw libraries.error
    const layers = await viewer.supabase.from("cloud_layers").select("id").eq("library_id", libraryId)
    if (layers.error) throw layers.error
    if (libraries.data.length !== 1 || layers.data.length !== OBJECT_COUNT) {
      throw new Error("The connected producer cannot see the ready smoke library.")
    }
  })

  const pause = await timed(async () => {
    const response = await owner.supabase.from("cloud_libraries").update({ status: "archived" }).eq("id", libraryId)
    if (response.error) throw response.error
  })
  const pausedVisibility = await timed(async () => {
    const libraries = await viewer.supabase.from("cloud_libraries").select("id").eq("id", libraryId)
    if (libraries.error) throw libraries.error
    const layers = await viewer.supabase.from("cloud_layers").select("id").eq("library_id", libraryId)
    if (layers.error) throw layers.error
    if (libraries.data.length !== 0 || layers.data.length !== 0) {
      throw new Error("The paused smoke library remains visible to the connected producer.")
    }
  })
  const pausedOwnerAccess = await timed(async () => {
    const layers = await owner.supabase
      .from("cloud_layers")
      .select("object_path")
      .eq("library_id", libraryId)
    if (layers.error) throw layers.error
    if (layers.data.length !== OBJECT_COUNT) {
      throw new Error("The owner cannot manage every object while the smoke library is paused.")
    }
    return layers.data.map((layer) => layer.object_path)
  })

  const resume = await timed(async () => {
    const response = await owner.supabase.from("cloud_libraries").update({ status: "ready" }).eq("id", libraryId)
    if (response.error) throw response.error
  })
  const resumedVisibility = await timed(async () => {
    const libraries = await viewer.supabase.from("cloud_libraries").select("id,status").eq("id", libraryId)
    if (libraries.error) throw libraries.error
    const layers = await viewer.supabase.from("cloud_layers").select("id").eq("library_id", libraryId)
    if (layers.error) throw layers.error
    if (libraries.data.length !== 1 || layers.data.length !== OBJECT_COUNT) {
      throw new Error("The resumed smoke library did not return for the connected producer.")
    }
  })

  const remove = await timed(async () => {
    const paused = await owner.supabase.from("cloud_libraries").update({ status: "archived" }).eq("id", libraryId)
    if (paused.error) throw paused.error
    const archivedLayers = await owner.supabase
      .from("cloud_layers")
      .select("object_path")
      .eq("library_id", libraryId)
    if (archivedLayers.error) throw archivedLayers.error
    if (archivedLayers.data.length !== OBJECT_COUNT) {
      throw new Error("The owner cannot resolve every object immediately before removal.")
    }
    const pathsToRemove = archivedLayers.data.map((layer) => layer.object_path)
    const removedObjects = await owner.supabase.storage.from(BUCKET).remove(pathsToRemove)
    if (removedObjects.error) throw removedObjects.error
    if (removedObjects.data.length !== OBJECT_COUNT) {
      throw new Error("Supabase Storage did not confirm removal of every smoke object.")
    }
    const deleted = await owner.supabase.from("cloud_libraries").delete().eq("id", libraryId).select("id").maybeSingle()
    if (deleted.error) throw deleted.error
    if (!deleted.data) throw new Error("The smoke library catalogue was not deleted.")
  })
  const removedVisibility = await timed(async () => {
    const ownerLibrary = await owner.supabase.from("cloud_libraries").select("id").eq("id", libraryId)
    if (ownerLibrary.error) throw ownerLibrary.error
    const viewerLibrary = await viewer.supabase.from("cloud_libraries").select("id").eq("id", libraryId)
    if (viewerLibrary.error) throw viewerLibrary.error
    if (ownerLibrary.data.length !== 0 || viewerLibrary.data.length !== 0) {
      throw new Error("The removed smoke library still exists in the Cloud catalogue.")
    }
  })

  completed = true
  process.stdout.write(`${JSON.stringify({
    libraryName,
    objectCount: OBJECT_COUNT,
    totalBytes,
    verified: {
      readyVisible: true,
      pausedHidden: true,
      pausedOwnerCanManageFiles: pausedOwnerAccess.value.length === OBJECT_COUNT,
      resumedVisible: true,
      storageAndCatalogueRemoved: true,
    },
    milliseconds: {
      publish: publish.milliseconds,
      verifyReady: readyVisibility.milliseconds,
      pause: pause.milliseconds,
      verifyPaused: pausedVisibility.milliseconds,
      verifyPausedOwnerAccess: pausedOwnerAccess.milliseconds,
      resume: resume.milliseconds,
      verifyResumed: resumedVisibility.milliseconds,
      remove: remove.milliseconds,
      verifyRemoved: removedVisibility.milliseconds,
    },
  }, null, 2)}\n`)
} finally {
  if (!completed && libraryId) {
    await owner.supabase.from("cloud_libraries").update({ status: "archived" }).eq("id", libraryId)
    if (objectPaths.length > 0) await owner.supabase.storage.from(BUCKET).remove(objectPaths)
    await owner.supabase.from("cloud_libraries").delete().eq("id", libraryId)
  }
  await Promise.all([
    owner.supabase.auth.signOut({ scope: "local" }),
    viewer.supabase.auth.signOut({ scope: "local" }),
  ])
}
