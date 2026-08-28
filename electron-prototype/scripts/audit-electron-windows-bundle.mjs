import { existsSync, readFileSync, statSync } from "node:fs"
import path from "node:path"
import process from "node:process"
import { URL } from "node:url"

const applicationRoot = path.resolve(process.argv[2] || "")
if (!applicationRoot || !existsSync(applicationRoot)) {
  throw new Error(`Windows application root is missing: ${applicationRoot}`)
}

const requiredFiles = [
  "Slicer.exe",
  "resources/app.asar",
  "resources/python/engine_bridge.py",
  "resources/.runtime/python/python.exe",
  "resources/engine/engine.py",
  "resources/engine/generation_policy.py",
  "resources/engine/generation_renderer.py",
  "resources/engine/models/layer_roles_v3.joblib",
  "resources/engine/vendor-windows/ffmpeg-bin/ffmpeg.exe",
  "resources/engine/vendor-windows/openkeyscan-analyzer/openkeyscan-analyzer.exe",
  "resources/engine/bin/bungee.exe",
]

for (const relativePath of requiredFiles) {
  const absolutePath = path.join(applicationRoot, relativePath)
  if (!existsSync(absolutePath) || !statSync(absolutePath).isFile() || statSync(absolutePath).size <= 0) {
    throw new Error(`Required Windows payload is missing or empty: ${relativePath}`)
  }
}

const forbiddenBuildArtifacts = [
  "resources/engine/analyzer/.venv-build",
  "resources/engine/analyzer/build",
  "resources/engine/analyzer/dist",
  "resources/engine/analyzer/__pycache__",
]

for (const relativePath of forbiddenBuildArtifacts) {
  if (existsSync(path.join(applicationRoot, relativePath))) {
    throw new Error(`Temporary analyzer build artifact leaked into the Windows bundle: ${relativePath}`)
  }
}

const packageJson = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"))
if (packageJson.productName !== "Slicer") throw new Error(`Unexpected product name: ${packageJson.productName}`)

process.stdout.write(`Validated Slicer ${packageJson.version} Windows bundle at ${applicationRoot}\n`)
