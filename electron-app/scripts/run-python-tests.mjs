import { existsSync } from "node:fs"
import path from "node:path"
import { spawnSync } from "node:child_process"
import process from "node:process"

const electronRoot = process.cwd()
const repositoryRoot = path.resolve(electronRoot, "..")

function firstExisting(candidates) {
  return candidates.find((candidate) => candidate && existsSync(candidate))
}

function run(command, args, options = {}) {
  const completed = spawnSync(command, args, {
    cwd: repositoryRoot,
    env: {
      ...process.env,
      STEM_SLICER_SOURCE_ROOT: repositoryRoot,
    },
    encoding: "utf8",
    stdio: "inherit",
    ...options,
  })
  if (completed.error) throw completed.error
  if (completed.status !== 0) process.exit(completed.status ?? 1)
}

const localRuntime = process.platform === "win32"
  ? [
      path.join(electronRoot, ".runtime", "python", "python.exe"),
      path.join(electronRoot, ".runtime", "python", "Scripts", "python.exe"),
    ]
  : [
      path.join(electronRoot, ".runtime", "python", "bin", "python3.12"),
      path.join(electronRoot, ".runtime", "python", "bin", "python3"),
    ]
const python = firstExisting([
  process.env.STEM_SLICER_PYTHON?.trim(),
  ...localRuntime,
])

if (!python) {
  throw new Error(
    "The Slicer Python runtime is missing. Run `pnpm run runtime:setup` before validation.",
  )
}

const expectedVersion = process.platform === "win32" ? "(3, 12, 10)" : "(3, 12, 13)"
const expectedArchitectures = process.platform === "win32" ? "{'AMD64', 'x86_64'}" : "{'arm64'}"
run(python, [
  "-c",
  [
    "import json, platform, sys",
    "import joblib, soundfile, torch",
    `assert sys.version_info[:3] == ${expectedVersion}, sys.version`,
    `assert platform.machine() in ${expectedArchitectures}, platform.machine()`,
    "payload = {'python': sys.version.split()[0], 'architecture': platform.machine(), 'torch': torch.__version__, 'joblib': joblib.__version__, 'soundfile': soundfile.__version__}",
    "print(json.dumps(payload, sort_keys=True))",
  ].join("; "),
])
run(python, ["-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v"])
run(python, ["-m", "unittest", "discover", "-s", "electron-app/python", "-p", "test_*.py", "-v"])
