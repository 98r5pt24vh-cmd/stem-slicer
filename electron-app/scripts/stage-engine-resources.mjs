import { cpSync, existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs"
import path from "node:path"
import process from "node:process"
import { fileURLToPath } from "node:url"

const electronRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..")
const repositoryRoot = path.resolve(electronRoot, "..")
const manifestPath = path.join(electronRoot, "python", "engine-manifest.json")
const argumentsList = process.argv.slice(2)
const checkOnly = argumentsList.includes("--check")
const platformOption = argumentsList.find((argument) => argument.startsWith("--platform="))
const positionalArguments = argumentsList.filter((argument) => !argument.startsWith("--"))
const destinationRoot = path.resolve(positionalArguments[0] || path.join(electronRoot, ".packaging", "engine"))
const targetPlatform = platformOption?.slice("--platform=".length) || positionalArguments[1] || process.platform
const manifest = JSON.parse(readFileSync(manifestPath, "utf8"))

if (!Object.hasOwn(manifest.platformFiles, targetPlatform)) {
  throw new Error(`Unsupported engine target platform: ${targetPlatform}`)
}
if (!checkOnly && existsSync(destinationRoot) && readdirSync(destinationRoot).length > 0) {
  throw new Error(`Engine staging destination is not empty: ${destinationRoot}`)
}

const copyFile = (relativePath) => {
  const source = path.join(repositoryRoot, relativePath)
  if (!existsSync(source)) throw new Error(`Required engine file is missing: ${relativePath}`)
  if (checkOnly) return
  const destination = path.join(destinationRoot, relativePath)
  mkdirSync(path.dirname(destination), { recursive: true })
  cpSync(source, destination)
}

const copyDirectory = (relativePath) => {
  const source = path.join(repositoryRoot, relativePath)
  if (!existsSync(source)) throw new Error(`Required engine directory is missing: ${relativePath}`)
  if (checkOnly) return
  const destination = path.join(destinationRoot, relativePath)
  mkdirSync(path.dirname(destination), { recursive: true })
  cpSync(source, destination, { recursive: true })
}

if (!checkOnly) mkdirSync(destinationRoot, { recursive: true })
for (const relativePath of [...manifest.commonFiles, ...manifest.platformFiles[targetPlatform]]) {
  copyFile(relativePath)
}
for (const relativePath of manifest.externalDirectories) copyDirectory(relativePath)
if (!checkOnly) {
  writeFileSync(
    path.join(destinationRoot, "engine-manifest.json"),
    `${JSON.stringify({ ...manifest, stagedPlatform: targetPlatform }, null, 2)}\n`,
    "utf8",
  )
}

process.stdout.write(
  `${checkOnly ? "Verified" : "Staged"} ${manifest.commonFiles.length + manifest.platformFiles[targetPlatform].length} files and ${manifest.externalDirectories.length} external tree(s) for ${targetPlatform}.\n`,
)
