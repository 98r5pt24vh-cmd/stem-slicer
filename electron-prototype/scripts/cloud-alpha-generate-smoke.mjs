import { spawn } from "node:child_process"
import { readFile } from "node:fs/promises"
import { homedir } from "node:os"
import path from "node:path"
import process from "node:process"

import { createClient } from "@supabase/supabase-js"

const cloudRoot = path.join(homedir(), "Library", "Caches", "Stem Slicer", "electron-prototype", "cloud")
const settings = JSON.parse(await readFile(path.join(cloudRoot, "settings.json"), "utf8"))
const credentials = JSON.parse(await readFile(path.join(cloudRoot, "alpha-test-credentials.json"), "utf8"))
const supabase = createClient(settings.projectUrl, settings.publishableKey, {
  auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false },
})
const auth = await supabase.auth.signInWithPassword({
  email: credentials.accounts.nrgy.email,
  password: credentials.accounts.nrgy.password,
})
if (auth.error) throw auth.error
if (!auth.data.session) throw new Error("The +NRGY alpha session is unavailable")

const library = await supabase
  .from("cloud_libraries")
  .select("id,owner_id,name,status")
  .eq("name", "XT Real Five Loops Test")
  .eq("status", "ready")
  .single()
if (library.error) throw library.error
const remote = await supabase
  .from("cloud_layers")
  .select("id,library_id,owner_id,object_path,file_name,relative_path,sha256,byte_size,metadata")
  .eq("library_id", library.data.id)
  .order("file_name")
if (remote.error) throw remote.error

const audioCacheRoot = path.join(cloudRoot, "audio")
const cloudLayers = remote.data.map((row) => {
  const metadata = row.metadata && typeof row.metadata === "object" ? row.metadata : {}
  const extension = path.extname(row.file_name).toLowerCase() || ".mp3"
  return {
    ...metadata,
    identity: `cloud:${row.id}`,
    path: path.join(audioCacheRoot, row.owner_id, row.library_id, `${row.sha256}${extension}`),
    filename: row.file_name,
    relative_path: row.relative_path,
    source_loop_id: `cloud:${row.owner_id}:${String(metadata.source_loop_id || row.id)}`,
    library_root: `cloud://${row.owner_id}/${row.library_id}`,
    sha256: row.sha256,
    byte_size: Number(row.byte_size),
    producers: Array.isArray(metadata.producers) ? metadata.producers : ["XT"],
    cloud_object_path: row.object_path,
    cloud_layer_id: row.id,
    cloud_owner_id: row.owner_id,
  }
})

const request = {
  databasePath: path.join(homedir(), "Library", "Caches", "Stem Slicer", "1.9", "generate", "library.sqlite3"),
  libraryRoots: [],
  categories: ["Bass", "Chords", "Lead", "Counter", "Pluck"],
  targetBpm: 140,
  targetKey: "F minor",
  seed: 820260828,
  generationNumber: 9999,
  bars: 8,
  sourcePool: "cloud-only",
  allowedProducers: ["+NRGY", "XT"],
  allowedCreditCounts: [2],
  requiredProducers: ["XT"],
  requiredContributionPercent: 100,
  cloudLayers,
  cloudAuth: {
    projectUrl: settings.projectUrl,
    publishableKey: settings.publishableKey,
    accessToken: auth.data.session.access_token,
    bucket: "cloud-layers",
    cacheRoot: audioCacheRoot,
  },
}

const python = path.join(process.cwd(), ".runtime", "python", "bin", "python3.12")
const bridge = spawn(python, ["-u", path.join(process.cwd(), "python", "engine_bridge.py")], {
  cwd: process.cwd(),
  stdio: ["pipe", "pipe", "pipe"],
})
let stderr = ""
bridge.stderr.setEncoding("utf8")
bridge.stderr.on("data", (chunk) => { stderr += chunk })

const result = await new Promise((resolve, reject) => {
  let buffer = ""
  const fail = (error) => {
    bridge.stdin.end(`${JSON.stringify({ type: "shutdown" })}\n`)
    reject(error)
  }
  bridge.once("error", fail)
  bridge.stdout.setEncoding("utf8")
  bridge.stdout.on("data", (chunk) => {
    buffer += chunk
    for (;;) {
      const newline = buffer.indexOf("\n")
      if (newline < 0) break
      const line = buffer.slice(0, newline).trim()
      buffer = buffer.slice(newline + 1)
      if (!line) continue
      const event = JSON.parse(line)
      if (event.type === "ready") {
        bridge.stdin.write(`${JSON.stringify({ id: "cloud-only-smoke", kind: "generate", payload: request })}\n`)
      } else if (event.id === "cloud-only-smoke" && event.type === "error") {
        fail(new Error(`${event.error}${stderr ? `\n${stderr}` : ""}`))
      } else if (event.id === "cloud-only-smoke" && event.type === "result") {
        bridge.stdin.end(`${JSON.stringify({ type: "shutdown" })}\n`)
        resolve(event.result)
      }
    }
  })
})

await supabase.auth.signOut()
process.stdout.write(`${JSON.stringify({
  ok: true,
  outputDirectory: result.outputDirectory,
  displayName: result.displayName,
  sourceOrigins: result.layers.map((layer) => layer.sourceOrigin),
  sourceLoopIds: result.layers.map((layer) => layer.sourceLoopId),
}, null, 2)}\n`)
