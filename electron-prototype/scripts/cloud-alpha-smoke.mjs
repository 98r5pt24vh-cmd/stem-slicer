import { createHash } from "node:crypto"
import { chmod, mkdir, readFile, writeFile } from "node:fs/promises"
import { homedir } from "node:os"
import path from "node:path"
import process from "node:process"
import { DatabaseSync } from "node:sqlite"

import { createClient } from "@supabase/supabase-js"

const BUCKET = "cloud-layers"
const LIBRARY_NAME = "XT Real Five Loops Test"
const LEGACY_LIBRARY_NAMES = ["XT Synthetic Alpha", "XT Synthetic Alpha v2", "XT Synthetic Alpha v3"]
const LOOP_COUNT = 5
const TEST_SOURCE_LOOPS = [
  "c#m cocoa 137 +nrgy xt",
  "bm silksong 140 +nrgy xt",
  "gm edm 135 +nrgy xt",
  "f stereo 145 +nrgy xt",
  "em pandora 140 +nrgy xt",
]

const cloudRoot = path.join(
  homedir(),
  "Library",
  "Caches",
  "Stem Slicer",
  "electron-prototype",
  "cloud",
)
const settings = JSON.parse(await readFile(path.join(cloudRoot, "settings.json"), "utf8"))
const credentials = JSON.parse(await readFile(path.join(cloudRoot, "alpha-test-credentials.json"), "utf8"))

function client() {
  return createClient(settings.projectUrl, settings.publishableKey, {
    auth: {
      persistSession: false,
      autoRefreshToken: false,
      detectSessionInUrl: false,
    },
  })
}

async function signIn(account) {
  const supabase = client()
  const auth = await supabase.auth.signInWithPassword({
    email: account.email,
    password: account.password,
  })
  if (auth.error) throw auth.error
  if (!auth.data.user) throw new Error(`No user returned for ${account.displayName}`)
  return { supabase, user: auth.data.user }
}

const acceptedDatabase = path.join(homedir(), "Library", "Caches", "Stem Slicer", "1.9", "generate", "library.sqlite3")
const corpusRoot = path.join(cloudRoot, "fixtures", "XT Real Five Loops Test")
await mkdir(corpusRoot, { recursive: true })
const database = new DatabaseSync(acceptedDatabase, { readOnly: true })
const placeholders = TEST_SOURCE_LOOPS.map(() => "?").join(",")
const rows = database.prepare(`
  SELECT path, filename, source_loop_id, layer_index, bpm, key, mode, duration_seconds,
         predicted_label, prediction_confidence, manual_label, scanned_key, scanned_mode,
         key_confidence_margin, key_confidence_status, key_analyzer_id,
         alternate_scanned_key, alternate_scanned_mode, key_top1_probability,
         key_top2_probability, manual_bpm, manual_key, manual_mode,
         timeline_offset_beats, trim_start_beats, trim_end_beats
  FROM layer_cache
  WHERE COALESCE(manual_excluded, 0) = 0
    AND source_loop_id IN (${placeholders})
  ORDER BY source_loop_id, COALESCE(layer_index, 999), filename
`).all(...TEST_SOURCE_LOOPS)
database.close()

const rowsByLoop = new Map(TEST_SOURCE_LOOPS.map((sourceLoopId) => [sourceLoopId, []]))
for (const row of rows) rowsByLoop.get(row.source_loop_id)?.push(row)
if ([...rowsByLoop.values()].some((items) => items.length === 0)) {
  throw new Error("One of the five real source loops is unavailable in the local Generate catalogue")
}

const fixtures = []
for (let loopIndex = 0; loopIndex < TEST_SOURCE_LOOPS.length; loopIndex += 1) {
  const originalSourceLoopId = TEST_SOURCE_LOOPS[loopIndex]
  const loopNumber = String(loopIndex + 1).padStart(2, "0")
  const sourceLoopId = `slicer-cloud-xt-test-${loopNumber}`
  const sourceLoopName = `SLICER CLOUD XT TEST ${loopNumber}`
  const loopFolder = path.join(corpusRoot, sourceLoopName)
  await mkdir(loopFolder, { recursive: true })
  const loopRows = rowsByLoop.get(originalSourceLoopId)
  for (let layerOffset = 0; layerOffset < loopRows.length; layerOffset += 1) {
    const row = loopRows[layerOffset]
    const layerIndex = Number(row.layer_index || layerOffset + 1)
    const category = String(row.manual_label || row.predicted_label || "Unknown")
    const safeCategory = category.replace(/[^a-z0-9]+/gi, "-").replace(/^-+|-+$/g, "") || "Layer"
    const extension = path.extname(row.filename).toLowerCase() || ".mp3"
    const fileName = `SLICER_CLOUD_XT_TEST_${loopNumber}_L${String(layerIndex).padStart(2, "0")}_${safeCategory}${extension}`
    const body = await readFile(row.path)
    const localTestPath = path.join(loopFolder, fileName)
    await writeFile(localTestPath, body)
    fixtures.push({
      body,
      fileName,
      relativePath: `${sourceLoopName}/${fileName}`,
      sourceLoopId,
      sourceLoopName,
      layerIndex,
      category,
      sha256: createHash("sha256").update(body).digest("hex"),
      bpm: row.bpm,
      key: row.key,
      mode: row.mode,
      durationSeconds: row.duration_seconds,
      predictedLabel: row.predicted_label,
      predictionConfidence: row.prediction_confidence,
      manualLabel: row.manual_label,
      scannedKey: row.scanned_key,
      scannedMode: row.scanned_mode,
      keyConfidenceMargin: row.key_confidence_margin,
      keyConfidenceStatus: row.key_confidence_status,
      keyAnalyzerId: row.key_analyzer_id,
      alternateScannedKey: row.alternate_scanned_key,
      alternateScannedMode: row.alternate_scanned_mode,
      keyTop1Probability: row.key_top1_probability,
      keyTop2Probability: row.key_top2_probability,
      manualBpm: row.manual_bpm,
      manualKey: row.manual_key,
      manualMode: row.manual_mode,
      timelineOffsetBeats: row.timeline_offset_beats,
      trimStartBeats: row.trim_start_beats,
      trimEndBeats: row.trim_end_beats,
    })
  }
}

await writeFile(path.join(corpusRoot, "corpus-manifest.json"), `${JSON.stringify({
  name: LIBRARY_NAME,
  sourceLoops: TEST_SOURCE_LOOPS.map((originalSourceLoopId, index) => ({
    testName: `SLICER CLOUD XT TEST ${String(index + 1).padStart(2, "0")}`,
    originalSourceLoopId,
    layerCount: rowsByLoop.get(originalSourceLoopId).length,
  })),
}, null, 2)}\n`)

async function ensureSyntheticLibrary() {
  const { supabase, user } = await signIn(credentials.accounts.xt)
  const existing = await supabase
    .from("cloud_libraries")
    .select("id,owner_id,name,status,layer_count,loop_count,total_bytes")
    .eq("owner_id", user.id)
    .eq("name", LIBRARY_NAME)
    .eq("status", "ready")
    .maybeSingle()
  if (existing.error) throw existing.error
  if (existing.data) {
    await supabase.auth.signOut()
    return existing.data
  }

  const totalBytes = fixtures.reduce((total, fixture) => total + fixture.body.length, 0)
  const created = await supabase
    .from("cloud_libraries")
    .insert({
      owner_id: user.id,
      name: LIBRARY_NAME,
      source_fingerprint: createHash("sha256").update(fixtures.map((fixture) => fixture.sha256).join(":"), "utf8").digest("hex"),
      status: "uploading",
      layer_count: fixtures.length,
      loop_count: LOOP_COUNT,
      total_bytes: totalBytes,
    })
    .select("id,owner_id,name,status,layer_count,loop_count,total_bytes")
    .single()
  if (created.error) throw created.error

  const layerRows = []
  for (let index = 0; index < fixtures.length; index += 1) {
    const fixture = fixtures[index]
    const objectPath = `${user.id}/${created.data.id}/${String(index + 1).padStart(5, "0")}-${fixture.sha256.slice(0, 12)}-${fixture.fileName}`
    const upload = await supabase.storage.from(BUCKET).upload(objectPath, fixture.body, {
      contentType: fixture.fileName.toLowerCase().endsWith(".mp3") ? "audio/mpeg" : "application/octet-stream",
      cacheControl: "3600",
      upsert: false,
    })
    if (upload.error) throw upload.error
    layerRows.push({
      library_id: created.data.id,
      owner_id: user.id,
      object_path: objectPath,
      file_name: fixture.fileName,
      relative_path: fixture.relativePath,
      sha256: fixture.sha256,
      byte_size: fixture.body.length,
      metadata: {
        source_loop_id: fixture.sourceLoopId,
        source_loop_name: fixture.sourceLoopName,
        layer_index: fixture.layerIndex,
        bpm: fixture.bpm,
        key: fixture.key,
        mode: fixture.mode,
        duration_seconds: fixture.durationSeconds,
        predicted_label: fixture.predictedLabel,
        prediction_confidence: fixture.predictionConfidence,
        manual_label: fixture.manualLabel,
        category: fixture.category,
        scanned_key: fixture.scannedKey,
        scanned_mode: fixture.scannedMode,
        key_confidence_margin: fixture.keyConfidenceMargin,
        key_confidence_status: fixture.keyConfidenceStatus,
        key_analyzer_id: fixture.keyAnalyzerId,
        alternate_scanned_key: fixture.alternateScannedKey,
        alternate_scanned_mode: fixture.alternateScannedMode,
        key_top1_probability: fixture.keyTop1Probability,
        key_top2_probability: fixture.keyTop2Probability,
        manual_bpm: fixture.manualBpm,
        manual_key: fixture.manualKey,
        manual_mode: fixture.manualMode,
        timeline_offset_beats: fixture.timelineOffsetBeats,
        trim_start_beats: fixture.trimStartBeats,
        trim_end_beats: fixture.trimEndBeats,
        producers: ["XT"],
      },
    })
  }
  const inserted = await supabase.from("cloud_layers").insert(layerRows)
  if (inserted.error) throw inserted.error
  const ready = await supabase
    .from("cloud_libraries")
    .update({ status: "ready" })
    .eq("id", created.data.id)
    .select("id,owner_id,name,status,layer_count,loop_count,total_bytes")
    .single()
  if (ready.error) throw ready.error
  await supabase.auth.signOut()
  return ready.data
}

async function archiveLegacyLibraries() {
  const { supabase, user } = await signIn(credentials.accounts.xt)
  const archived = await supabase
    .from("cloud_libraries")
    .update({ status: "archived" })
    .eq("owner_id", user.id)
    .in("name", LEGACY_LIBRARY_NAMES)
    .eq("status", "ready")
    .select("id")
  if (archived.error) throw archived.error
  await supabase.auth.signOut()
  return archived.data.map((item) => item.id)
}

async function verifyAnonymousCannotRead() {
  const anonymous = client()
  const response = await anonymous.from("cloud_libraries").select("id").limit(1)
  if (!response.error) throw new Error("Anonymous Cloud catalogue access was unexpectedly allowed")
  return true
}

async function connectAccountsAndVerify(library) {
  const nrgy = await signIn(credentials.accounts.nrgy)
  const before = await nrgy.supabase.from("cloud_libraries").select("id").eq("id", library.id)
  if (before.error) throw before.error

  const target = await nrgy.supabase.from("profiles").select("id").eq("handle", "xt-alpha").single()
  if (target.error) throw target.error
  let connection = await nrgy.supabase
    .from("connections")
    .select("id,status,requester_id,addressee_id")
    .or(`and(requester_id.eq.${nrgy.user.id},addressee_id.eq.${target.data.id}),and(requester_id.eq.${target.data.id},addressee_id.eq.${nrgy.user.id})`)
    .maybeSingle()
  if (connection.error) throw connection.error
  if (!connection.data) {
    connection = await nrgy.supabase
      .from("connections")
      .insert({ requester_id: nrgy.user.id, addressee_id: target.data.id, status: "pending" })
      .select("id,status,requester_id,addressee_id")
      .single()
    if (connection.error) throw connection.error
  }
  await nrgy.supabase.auth.signOut()

  if (connection.data.status === "pending") {
    const xt = await signIn(credentials.accounts.xt)
    const accepted = await xt.supabase
      .from("connections")
      .update({ status: "accepted" })
      .eq("id", connection.data.id)
      .select("id,status")
      .single()
    if (accepted.error) throw accepted.error
    await xt.supabase.auth.signOut()
  }

  const connected = await signIn(credentials.accounts.nrgy)
  const visibleLibrary = await connected.supabase
    .from("cloud_libraries")
    .select("id,name,layer_count,total_bytes")
    .eq("id", library.id)
    .single()
  if (visibleLibrary.error) throw visibleLibrary.error
  const layers = await connected.supabase
    .from("cloud_layers")
    .select("id,object_path,metadata")
    .eq("library_id", library.id)
    .order("file_name")
  if (layers.error) throw layers.error
  if (layers.data.length !== fixtures.length) throw new Error(`Expected ${fixtures.length} visible layers, received ${layers.data.length}`)
  const download = await connected.supabase.storage.from(BUCKET).download(layers.data[0].object_path)
  if (download.error) throw download.error
  const downloadedBytes = (await download.data.arrayBuffer()).byteLength
  await connected.supabase.auth.signOut()
  return {
    hiddenBeforeConnection: before.data.length === 0,
    visibleAfterConnection: true,
    visibleLayerCount: layers.data.length,
    downloadedObjectCount: 1,
    downloadedBytes,
  }
}

const anonymousDenied = await verifyAnonymousCannotRead()
const library = await ensureSyntheticLibrary()
const archivedLibraryIds = await archiveLegacyLibraries()
const sharing = await connectAccountsAndVerify(library)
settings.enabledLibraryIds = [
  ...new Set([
    ...(settings.enabledLibraryIds ?? []).filter((id) => !archivedLibraryIds.includes(id)),
    library.id,
  ]),
]
const settingsPath = path.join(cloudRoot, "settings.json")
await writeFile(settingsPath, `${JSON.stringify(settings, null, 2)}\n`, { mode: 0o600 })
await chmod(settingsPath, 0o600)

process.stdout.write(`${JSON.stringify({
  ok: true,
  anonymousDenied,
  archivedLibraryIds,
  library: {
    id: library.id,
    name: library.name,
    layerCount: library.layer_count,
    totalBytes: Number(library.total_bytes),
  },
  sharing,
}, null, 2)}\n`)
