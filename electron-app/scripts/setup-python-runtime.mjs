import { existsSync } from "node:fs"
import path from "node:path"
import { spawnSync } from "node:child_process"
import process from "node:process"

const electronRoot = process.cwd()
const runtimeRoot = path.join(electronRoot, ".runtime", "python")
const requestedBase = process.env.SLICER_BOOTSTRAP_PYTHON?.trim() || "python3.12"

if (!new Set(["darwin", "win32"]).has(process.platform)) {
  throw new Error(`Slicer runtime setup is not validated on ${process.platform}.`)
}

function capture(command, args) {
  const completed = spawnSync(command, args, { encoding: "utf8" })
  if (completed.error) throw completed.error
  if (completed.status !== 0) {
    throw new Error(completed.stderr.trim() || `${command} exited with ${completed.status}`)
  }
  return completed.stdout.trim()
}

function run(command, args) {
  const completed = spawnSync(command, args, { cwd: electronRoot, stdio: "inherit" })
  if (completed.error) throw completed.error
  if (completed.status !== 0) process.exit(completed.status ?? 1)
}

if (existsSync(runtimeRoot)) {
  throw new Error(
    `A runtime already exists at ${runtimeRoot}. Move it to the Trash before requesting a fresh setup.`,
  )
}

const identity = JSON.parse(capture(requestedBase, [
  "-c",
  "import json, platform, sys; print(json.dumps({'version': list(sys.version_info[:3]), 'architecture': platform.machine()}))",
]))
const expectedVersion = process.platform === "win32" ? [3, 12, 10] : [3, 12, 13]
const expectedArchitecture = process.platform === "win32" ? new Set(["AMD64", "x86_64"]) : new Set(["arm64"])

if (JSON.stringify(identity.version) !== JSON.stringify(expectedVersion)) {
  throw new Error(`Expected Python ${expectedVersion.join(".")}, received ${identity.version.join(".")}.`)
}
if (!expectedArchitecture.has(identity.architecture)) {
  throw new Error(`Unexpected Python architecture: ${identity.architecture}.`)
}

run(requestedBase, ["-m", "venv", runtimeRoot])
const python = process.platform === "win32"
  ? path.join(runtimeRoot, "Scripts", "python.exe")
  : path.join(runtimeRoot, "bin", "python3.12")
run(python, ["-m", "pip", "install", "--upgrade", "pip"])
if (process.platform === "win32") {
  run(python, [
    "-m", "pip", "install",
    "--index-url", "https://download.pytorch.org/whl/cpu",
    "torch==2.5.1", "torchaudio==2.5.1",
  ])
}
run(python, ["-m", "pip", "install", "-r", path.join(electronRoot, "python", "requirements-runtime.txt")])
run(python, ["-m", "pip", "check"])
run(python, [
  "-c",
  "import joblib, soundfile, torch; print(f'Runtime ready: torch={torch.__version__} joblib={joblib.__version__} soundfile={soundfile.__version__}')",
])
