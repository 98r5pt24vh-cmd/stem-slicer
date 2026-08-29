import type { AudioArtifact, ConvertHistoryEntry, ExtractionHistoryEntry } from "@/shared/contracts"

export type { ConvertHistoryEntry, ExtractionHistoryEntry } from "@/shared/contracts"

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string")
}

function isAudioArtifact(value: unknown): value is AudioArtifact {
  if (!value || typeof value !== "object") return false
  const artifact = value as Partial<AudioArtifact>
  return typeof artifact.path === "string"
    && typeof artifact.name === "string"
    && typeof artifact.displayName === "string"
    && typeof artifact.bpm === "number"
    && typeof artifact.key === "string"
    && typeof artifact.duration === "number"
    && typeof artifact.bytes === "number"
    && Array.isArray(artifact.peaks)
}

export function parseExtractionHistory(raw: string | null): ExtractionHistoryEntry[] {
  if (!raw) return []
  try {
    const parsed = JSON.parse(raw) as unknown
    if (!Array.isArray(parsed)) return []
    return parsed.filter((value): value is ExtractionHistoryEntry => {
      if (!value || typeof value !== "object") return false
      const entry = value as Partial<ExtractionHistoryEntry>
      return typeof entry.id === "string"
        && (entry.mode === "single" || entry.mode === "folder")
        && typeof entry.sourcePath === "string"
        && typeof entry.outputFolder === "string"
        && typeof entry.createdAt === "string"
        && typeof entry.sourceFileCount === "number"
        && typeof entry.outputCount === "number"
        && isStringArray(entry.outputs)
        && (entry.outputBytes === undefined || typeof entry.outputBytes === "number")
    })
  } catch {
    return []
  }
}

export function parseConvertHistory(raw: string | null): ConvertHistoryEntry[] {
  if (!raw) return []
  try {
    const parsed = JSON.parse(raw) as unknown
    if (!Array.isArray(parsed)) return []
    return parsed.filter((value): value is ConvertHistoryEntry => {
      if (!value || typeof value !== "object") return false
      const entry = value as Partial<ConvertHistoryEntry>
      return typeof entry.id === "string"
        && typeof entry.sourcePath === "string"
        && typeof entry.outputFolder === "string"
        && typeof entry.createdAt === "string"
        && isAudioArtifact(entry.artifact)
        && typeof entry.sourceBpm === "number"
        && typeof entry.sourceKey === "string"
        && typeof entry.targetBpm === "number"
        && typeof entry.targetKey === "string"
        && typeof entry.elapsedSeconds === "number"
    })
  } catch {
    return []
  }
}

export function prependUniqueActivity<T>(entries: T[], entry: T, identity: (item: T) => string): T[] {
  const entryIdentity = identity(entry)
  return [entry, ...entries.filter((item) => identity(item) !== entryIdentity)]
}
