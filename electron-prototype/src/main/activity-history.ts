import { existsSync, readdirSync, statSync } from "node:fs"
import path from "node:path"

import type { AudioArtifact, ConvertHistoryEntry, ExtractionHistoryEntry, QuickActivityHistorySnapshot } from "../shared/contracts"

const AUDIO_EXTENSIONS = new Set([".mp3", ".wav", ".aif", ".aiff", ".flac", ".m4a"])

function audioFiles(folder: string): string[] {
  if (!existsSync(folder)) return []
  return readdirSync(folder, { withFileTypes: true })
    .filter((entry) => entry.isFile() && AUDIO_EXTENSIONS.has(path.extname(entry.name).toLowerCase()))
    .map((entry) => path.join(folder, entry.name))
}

function activityFolders(root: string): string[] {
  if (!existsSync(root)) return []
  return readdirSync(root, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => path.join(root, entry.name))
}

function createdAtFor(folder: string, outputs: string[]): string {
  const timestamps = [statSync(folder).mtimeMs, ...outputs.map((output) => statSync(output).mtimeMs)]
  return new Date(Math.max(...timestamps)).toISOString()
}

function artifactFor(output: string): AudioArtifact {
  const name = path.basename(output)
  return {
    path: output,
    name,
    displayName: path.basename(output, path.extname(output)),
    bpm: 0,
    key: "—",
    duration: 0,
    bytes: statSync(output).size,
    peaks: [],
  }
}

export function readQuickActivityHistory(documentsRoot: string): QuickActivityHistorySnapshot {
  const extractRoot = path.join(documentsRoot, "Stem Slicer", "Quick Extract")
  const convertRoot = path.join(documentsRoot, "Stem Slicer", "Quick Convert")

  const extractions: ExtractionHistoryEntry[] = activityFolders(extractRoot).flatMap((folder) => {
    const outputs = audioFiles(folder)
    if (outputs.length === 0) return []
    return [{
      id: `single:${folder}`,
      mode: "single",
      sourcePath: path.basename(folder),
      outputFolder: folder,
      createdAt: createdAtFor(folder, outputs),
      sourceFileCount: 1,
      outputCount: outputs.length,
      outputs,
    }]
  })

  const conversions: ConvertHistoryEntry[] = activityFolders(convertRoot).flatMap((folder) => {
    const output = audioFiles(folder)[0]
    if (!output) return []
    return [{
      id: `convert:${output}`,
      sourcePath: path.basename(folder),
      outputFolder: folder,
      createdAt: createdAtFor(folder, [output]),
      artifact: artifactFor(output),
      sourceBpm: 0,
      sourceKey: "",
      targetBpm: 0,
      targetKey: "",
      elapsedSeconds: 0,
      recovered: true,
    }]
  })

  const newestFirst = <T extends { createdAt: string }>(left: T, right: T) => right.createdAt.localeCompare(left.createdAt)
  return { extractions: extractions.sort(newestFirst), conversions: conversions.sort(newestFirst) }
}
