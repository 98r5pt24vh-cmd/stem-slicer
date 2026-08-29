interface StudioLayerNameInput {
  file: string
  bpm: number
  keyName: string
  layerIndex?: number
}

export interface StudioLayerName {
  loopName: string
  layerLabel: string
  fullLabel: string
}

function normalizedKeyToken(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replaceAll("♯", "#")
    .replaceAll("♭", "b")
    .replace(/\s+/g, "")
}

function expectedKeyTokens(keyName: string): Set<string> {
  const [tonic = "", mode = ""] = keyName.trim().split(/\s+/)
  const normalizedTonic = normalizedKeyToken(tonic)
  const normalizedMode = mode.toLowerCase()
  if (!normalizedTonic) return new Set()
  if (normalizedMode === "minor") {
    return new Set([`${normalizedTonic}m`, `${normalizedTonic}min`, `${normalizedTonic}minor`])
  }
  return new Set([normalizedTonic, `${normalizedTonic}maj`, `${normalizedTonic}major`])
}

function leadingKeyTokenCount(tokens: string[], keyName: string): number {
  if (tokens.length === 0) return 0
  const first = normalizedKeyToken(tokens[0])
  if (expectedKeyTokens(keyName).has(first)) return 1
  if (
    /^[a-g](?:#|b)?$/.test(first)
    && /^(?:m|maj|major|min|minor)$/.test(normalizedKeyToken(tokens[1] ?? ""))
  ) return 2
  return /^[a-g](?:#|b)?(?:m|maj|major|min|minor)?$/.test(first) ? 1 : 0
}

function layerNumberFromFile(stem: string): number | undefined {
  const match = stem.match(/(?:^|[_\s-])(?:layer\s*)?l?(\d+)$/i)
  return match ? Number(match[1]) : undefined
}

export function studioLayerName({ file, bpm, keyName, layerIndex }: StudioLayerNameInput): StudioLayerName {
  const stem = file.replace(/\.[^.]+$/, "")
  const detectedLayerIndex = layerIndex ?? layerNumberFromFile(stem)
  const sourceName = stem.replace(/(?:[_\s-])(?:layer\s*)?l?\d+$/i, "").trim()
  const tokens = sourceName.split(/\s+/).filter(Boolean)
  const exactBpmIndex = tokens.findIndex((token) => Number(token) === bpm && /^\d{2,3}$/.test(token))
  let bpmIndex = exactBpmIndex
  for (let index = tokens.length - 1; bpmIndex < 0 && index >= 0; index -= 1) {
    const token = tokens[index]
    if (/^\d{2,3}$/.test(token) && Number(token) >= 40 && Number(token) <= 300) bpmIndex = index
  }
  const nameTokens = (bpmIndex > 0 ? tokens.slice(0, bpmIndex) : tokens.slice())

  nameTokens.splice(0, leadingKeyTokenCount(nameTokens, keyName))
  if (nameTokens.length > 1 && /^\d+$/.test(nameTokens[0])) nameTokens.shift()

  const loopName = nameTokens.join(" ").trim() || sourceName || "Source loop"
  const layerLabel = detectedLayerIndex == null ? "Layer" : `Layer ${detectedLayerIndex}`
  return {
    loopName,
    layerLabel,
    fullLabel: `${loopName} · ${layerLabel}`,
  }
}
