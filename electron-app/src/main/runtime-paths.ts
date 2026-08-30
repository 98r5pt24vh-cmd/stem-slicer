import { existsSync, readdirSync } from "node:fs"
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
  ffmpegPath: string
}

function firstExistingPath(candidates: string[], fallback: string): string {
  return candidates.find((candidate) => existsSync(candidate)) ?? fallback
}

function imageIoFfmpeg(runtimeRoot: string): string | undefined {
  const binaries = path.join(
    runtimeRoot,
    "python",
    "lib",
    "python3.12",
    "site-packages",
    "imageio_ffmpeg",
    "binaries",
  )
  if (!existsSync(binaries)) return undefined
  try {
    return readdirSync(binaries)
      .filter((entry) => entry.startsWith("ffmpeg-") && !entry.endsWith(".exe"))
      .sort()
      .map((entry) => path.join(binaries, entry))
      .find((candidate) => existsSync(candidate))
  } catch {
    return undefined
  }
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
  const configuredFfmpeg = environment.STEM_SLICER_FFMPEG?.trim()

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
  const sourceRoot = configuredSourceRoot || (isPackaged
    ? path.join(resourcesPath, "engine")
    : path.resolve(appRoot, ".."))
  const executable = platform === "win32" ? "ffmpeg.exe" : "ffmpeg"
  const imageIoBinary = platform === "darwin" ? imageIoFfmpeg(runtimeRoot) : undefined
  const ffmpegCandidates = platform === "win32"
    ? [
        path.join(sourceRoot, "vendor-windows", "ffmpeg-bin", executable),
        path.join(runtimeRoot, "bin", executable),
      ]
    : [
        path.join(runtimeRoot, "bin", executable),
        ...(imageIoBinary ? [imageIoBinary] : []),
        ...(platform === "darwin"
          ? ["/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"]
          : ["/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg"]),
      ]
  const ffmpegPath = configuredFfmpeg || firstExistingPath(
    ffmpegCandidates,
    isPackaged ? ffmpegCandidates[0] : executable,
  )

  return {
    resourceRoot,
    workingDirectory: resourceRoot,
    bridgePath: path.join(resourceRoot, "python", "engine_bridge.py"),
    sourceRoot,
    pythonPath,
    runtimeBin: path.join(runtimeRoot, "bin"),
    ffmpegPath,
  }
}
