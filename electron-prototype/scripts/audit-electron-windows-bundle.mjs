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
  "resources/engine/models/layer_roles_v4_2.joblib",
  "resources/engine/models/layer_roles_v4_2.json",
  "resources/engine/vendor-windows/ffmpeg-bin/ffmpeg.exe",
  "resources/engine/vendor-windows/openkeyscan-analyzer/openkeyscan-analyzer.exe",
  "resources/engine/bin/bungee.exe",
  "resources/cloud/project.json",
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

for (const relativePath of [
  "resources/cloud/alpha-test-credentials.json",
  "resources/cloud/settings.json",
  "resources/cloud/session.enc",
]) {
  if (existsSync(path.join(applicationRoot, relativePath))) {
    throw new Error(`Private Cloud state leaked into the Windows bundle: ${relativePath}`)
  }
}

const cloudConfiguration = JSON.parse(readFileSync(path.join(applicationRoot, "resources/cloud/project.json"), "utf8"))
const cloudProjectUrl = new URL(String(cloudConfiguration.projectUrl || ""))
if (cloudProjectUrl.protocol !== "https:" || !cloudProjectUrl.hostname.endsWith(".supabase.co")) {
  throw new Error("The Windows bundle has an invalid Cloud project URL.")
}
const cloudPublishableKey = String(cloudConfiguration.publishableKey || "")
if ((!cloudPublishableKey.startsWith("sb_publishable_") && cloudPublishableKey.split(".").length !== 3)
  || cloudPublishableKey.startsWith("sb_secret_")) {
  throw new Error("The Windows bundle does not contain a safe Cloud publishable key.")
}

const packageJson = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"))
if (packageJson.productName !== "Slicer") throw new Error(`Unexpected product name: ${packageJson.productName}`)

process.stdout.write(`Validated Slicer ${packageJson.version} Windows bundle at ${applicationRoot}\n`)
