import { existsSync } from "node:fs"
import path from "node:path"

export interface RuntimePathOptions {
  appRoot: string
  resourcesPath: string
  isPackaged: boolean
  platform?: NodeJS.Platform
  environment?: NodeJS.ProcessEnv
}

export interface RuntimePaths {
  resourceRoot: string
  workingDirectory: string
  bridgePath: string
  sourceRoot: string
  pythonPath: string
  runtimeBin: string
}

function firstExistingPath(candidates: string[], fallback: string): string {
  return candidates.find((candidate) => existsSync(candidate)) ?? fallback
}

export function resolveRuntimePaths({
  appRoot,
  resourcesPath,
  isPackaged,
  platform = process.platform,
  environment = process.env,
}: RuntimePathOptions): RuntimePaths {
  const resourceRoot = isPackaged ? resourcesPath : appRoot
  const runtimeRoot = path.join(resourceRoot, ".runtime")
  const configuredPython = environment.STEM_SLICER_PYTHON?.trim()
  const configuredSourceRoot = environment.STEM_SLICER_SOURCE_ROOT?.trim()

  const pythonCandidates = platform === "win32"
    ? [
        path.join(runtimeRoot, "python", "python.exe"),
        path.join(runtimeRoot, "python", "Scripts", "python.exe"),
      ]
    : [
        path.join(runtimeRoot, "python", "bin", "python3.12"),
        path.join(runtimeRoot, "python", "bin", "python3"),
      ]
  const pythonPath = configuredPython || firstExistingPath(
    pythonCandidates,
    isPackaged ? pythonCandidates[0] : platform === "win32" ? "python.exe" : "python3.12",
  )

  return {
    resourceRoot,
    workingDirectory: resourceRoot,
    bridgePath: path.join(resourceRoot, "python", "engine_bridge.py"),
    sourceRoot: configuredSourceRoot || (isPackaged
      ? path.join(resourcesPath, "engine")
      : path.resolve(appRoot, "..")),
    pythonPath,
    runtimeBin: path.join(runtimeRoot, "bin"),
  }
}
