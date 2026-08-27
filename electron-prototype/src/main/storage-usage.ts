import { readdir, stat } from "node:fs/promises"
import path from "node:path"

import type { GenerationStorageUsage } from "../shared/contracts"

export async function readGenerationStorageUsage(root: string): Promise<GenerationStorageUsage> {
  let rootEntries
  try {
    rootEntries = await readdir(root, { withFileTypes: true })
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return { bytes: 0, folders: 0, files: 0 }
    throw error
  }

  const directories = rootEntries.filter((entry) => entry.isDirectory())
  const pending = directories.map((entry) => path.join(root, entry.name))
  const rootFiles = rootEntries.filter((entry) => entry.isFile()).map((entry) => path.join(root, entry.name))
  let bytes = 0
  let files = 0

  for (const filePath of rootFiles) {
    bytes += (await stat(filePath)).size
    files += 1
  }

  while (pending.length > 0) {
    const directory = pending.pop()
    if (!directory) continue
    const entries = await readdir(directory, { withFileTypes: true })
    for (const entry of entries) {
      const entryPath = path.join(directory, entry.name)
      if (entry.isDirectory()) pending.push(entryPath)
      else if (entry.isFile()) {
        bytes += (await stat(entryPath)).size
        files += 1
      }
    }
  }

  return { bytes, folders: directories.length, files }
}
