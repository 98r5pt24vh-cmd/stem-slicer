import { existsSync, readdirSync, statSync } from "node:fs"
import path from "node:path"

import type {
  AudioArtifact,
  ConvertHistoryEntry,
  ExtractionHistoryEntry,
  GenerationStorageUsage,
  HistoryOutputKind,
  QuickActivityHistorySnapshot,
} from "../shared/contracts"

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

function filesInTree(root: string): string[] {
  if (!existsSync(root)) return []
  const pending = [root]
  const files: string[] = []
  while (pending.length > 0) {
    const directory = pending.pop()
    if (!directory) continue
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const entryPath = path.join(directory, entry.name)
      if (entry.isDirectory()) pending.push(entryPath)
      else if (entry.isFile()) files.push(entryPath)
    }
  }
  return files
}

export function readHistoryStorageUsage(paths: string[]): GenerationStorageUsage {
  const uniquePaths = [...new Set(paths.filter(Boolean).map((item) => path.resolve(item)))]
    .filter((candidate, index, items) => !items.some((parent, parentIndex) => (
      parentIndex !== index
      && candidate.startsWith(`${parent}${path.sep}`)
    )))
  let bytes = 0
  let files = 0
  let folders = 0
  for (const target of uniquePaths) {
    if (!existsSync(target)) continue
    const targetStat = statSync(target)
    if (targetStat.isFile()) {
      bytes += targetStat.size
      files += 1
      continue
    }
    if (!targetStat.isDirectory()) continue
    folders += 1
    const nestedFiles = filesInTree(target)
    files += nestedFiles.length
    bytes += nestedFiles.reduce((sum, file) => sum + statSync(file).size, 0)
  }
  return { bytes, folders, files }
}

export function historyRoot(documentsRoot: string): string {
  return path.join(documentsRoot, "Stem Slicer")
}

export function isAllowedHistoryOutput(documentsRoot: string, kind: HistoryOutputKind, targetPath: string): boolean {
  const roots = kind === "generate"
    ? [path.join(historyRoot(documentsRoot), "Generated Loops")]
    : kind === "convert"
      ? [path.join(historyRoot(documentsRoot), "Quick Convert")]
      : [
          path.join(historyRoot(documentsRoot), "Quick Extract"),
          path.join(historyRoot(documentsRoot), "Extracted Layers"),
        ]
  const target = path.resolve(targetPath)
  return roots.some((root) => {
    const relative = path.relative(root, target)
    return Boolean(relative)
      && !relative.startsWith("..")
      && !path.isAbsolute(relative)
      && path.dirname(target) === path.resolve(root)
  })
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
      outputBytes: outputs.reduce((sum, output) => sum + statSync(output).size, 0),
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
