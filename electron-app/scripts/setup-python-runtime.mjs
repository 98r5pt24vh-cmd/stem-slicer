import { cpSync, existsSync } from "node:fs"
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
  "import json, platform, sys; print(json.dumps({'version': list(sys.version_info[:3]), 'architecture': platform.machine(), 'basePrefix': sys.base_prefix}))",
]))
const expectedVersion = process.platform === "win32" ? [3, 12, 10] : [3, 12, 13]
const expectedArchitecture = process.platform === "win32" ? new Set(["AMD64", "x86_64"]) : new Set(["arm64"])

if (JSON.stringify(identity.version) !== JSON.stringify(expectedVersion)) {
  throw new Error(`Expected Python ${expectedVersion.join(".")}, received ${identity.version.join(".")}.`)
}
if (!expectedArchitecture.has(identity.architecture)) {
  throw new Error(`Unexpected Python architecture: ${identity.architecture}.`)
}

let python
if (process.platform === "win32") {
  // Windows venv launchers retain the absolute base-interpreter path in
  // pyvenv.cfg and fail with code 103 after the application is moved away
  // from the build runner. Copy the official setup-python installation so
  // the packaged python.exe resolves its standard library beside itself.
  cpSync(path.resolve(identity.basePrefix), runtimeRoot, { recursive: true })
  python = path.join(runtimeRoot, "python.exe")
} else {
  run(requestedBase, ["-m", "venv", runtimeRoot])
  python = path.join(runtimeRoot, "bin", "python3.12")
}
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
if (process.platform === "win32") {
  if (existsSync(path.join(runtimeRoot, "pyvenv.cfg"))) {
    throw new Error("The packaged Windows runtime must not contain a non-relocatable pyvenv.cfg.")
  }
  const runtimeIdentity = JSON.parse(capture(python, [
    "-c",
    "import json, sys; print(json.dumps({'executable': sys.executable, 'prefix': sys.prefix, 'basePrefix': sys.base_prefix}))",
  ]))
  const expectedRoot = path.resolve(runtimeRoot).toLowerCase()
  for (const [label, value] of Object.entries({
    executableRoot: path.dirname(runtimeIdentity.executable),
    prefix: runtimeIdentity.prefix,
    basePrefix: runtimeIdentity.basePrefix,
  })) {
    if (path.resolve(value).toLowerCase() !== expectedRoot) {
      throw new Error(`Windows runtime ${label} escaped the packaged root: ${value}`)
    }
  }
}
run(python, [
  "-c",
  "import joblib, soundfile, torch; print(f'Runtime ready: torch={torch.__version__} joblib={joblib.__version__} soundfile={soundfile.__version__}')",
])
