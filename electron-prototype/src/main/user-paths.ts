import { homedir } from "node:os"
import path from "node:path"

export interface UserPathOptions {
  platform?: NodeJS.Platform
  environment?: NodeJS.ProcessEnv
  homeDirectory?: string
}

export interface UserPaths {
  acceptedCachePath: string
  prototypeCachePath: string
  documentsRoot: string
  generatedOutputRoot: string
  defaultExtractionOutputPath: string
}

export function resolveUserPaths({
  platform = process.platform,
  environment = process.env,
  homeDirectory = homedir(),
}: UserPathOptions = {}): UserPaths {
  const pathApi = platform === "win32" ? path.win32 : path.posix
  const cacheBase = platform === "darwin"
    ? pathApi.join(homeDirectory, "Library", "Caches")
    : platform === "win32"
      ? environment.LOCALAPPDATA?.trim() || pathApi.join(homeDirectory, "AppData", "Local")
      : environment.XDG_CACHE_HOME?.trim() || pathApi.join(homeDirectory, ".cache")
  const cacheRoot = pathApi.join(cacheBase, "Stem Slicer")
  const documentsRoot = pathApi.join(homeDirectory, "Documents")

  return {
    acceptedCachePath: pathApi.join(cacheRoot, "1.9"),
    prototypeCachePath: pathApi.join(cacheRoot, "electron-prototype"),
    documentsRoot,
    generatedOutputRoot: pathApi.join(documentsRoot, "Stem Slicer", "Generated Loops"),
    defaultExtractionOutputPath: pathApi.join(documentsRoot, "Stem Slicer", "Extracted Layers", "Loop Pack Name"),
  }
}
